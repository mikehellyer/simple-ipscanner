"""Scanning a range: many addresses at once on a pool of threads, results
left in a queue for the window to pick up as they come."""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Optional

from simple_ipscanner.core import arp, ping, vendors


@dataclass
class HostResult:
    ip: str
    alive: bool = False
    ms: Optional[float] = None
    ttl: Optional[int] = None
    method: str = ""  # "ping", "tcp:<port>" or "arp" — what answered
    hostname: str = ""
    mac: str = ""
    vendor: str = ""
    ports: list[int] = field(default_factory=list)
    is_self: bool = False


@dataclass
class ScanOptions:
    threads: int = 64
    timeout_ms: int = 1000
    ports: list[int] = field(default_factory=list)
    tcp_fallback: bool = True
    resolve_names: bool = True


def probe_host(ip: str, options: ScanOptions, own_ip: Optional[str] = None) -> HostResult:
    reply = ping.is_alive(ip, options.timeout_ms, options.tcp_fallback)
    result = HostResult(ip, reply.alive, reply.ms, reply.ttl, reply.method if reply.alive else "")
    if reply.alive:
        complete_alive(result, options)
    result.is_self = ip == own_ip
    return result


def complete_alive(result: HostResult, options: ScanOptions) -> None:
    if options.resolve_names:
        result.hostname = ping.resolve_hostname(result.ip)
    if options.ports:
        result.ports = ping.open_ports(result.ip, options.ports)


def scan_one(ip: str, options: ScanOptions, own_ip: Optional[str] = None) -> HostResult:
    """Scan a single address again, MAC and all (for "Rescan")."""
    result = probe_host(ip, options, own_ip)
    mac, confirmed = arp.read_neighbours().get(ip, ("", False))
    if result.is_self:
        mac = arp.own_mac() or mac
    if not result.alive and confirmed:
        result.alive, result.method = True, "arp"
        complete_alive(result, options)
    if result.alive and mac:
        result.mac, result.vendor = mac, vendors.vendor_for(mac)
    return result


class Scanner(threading.Thread):
    """Start it, then drain `.results` (HostResults; an address can come
    through twice, the second time with its MAC filled in). `.finished`
    is set once nothing more will arrive."""

    def __init__(self, addresses: list[str], options: ScanOptions, own_ip: Optional[str] = None):
        super().__init__(daemon=True, name="scanner")
        self.addresses = addresses
        self.options = options
        self.own_ip = own_ip
        self.results: "queue.Queue[HostResult]" = queue.Queue()
        self.finished = threading.Event()
        self.cancelled = threading.Event()
        self.started_at = 0.0
        self.ended_at = 0.0
        self.scanned: set[str] = set()
        self._lock = threading.Lock()

    @property
    def done_count(self) -> int:
        with self._lock:
            return len(self.scanned)

    def cancel(self) -> None:
        self.cancelled.set()

    def _one(self, ip: str) -> Optional[HostResult]:
        if self.cancelled.is_set():
            return None
        result = probe_host(ip, self.options, self.own_ip)
        with self._lock:
            self.scanned.add(ip)
        self.results.put(result)
        return result

    def run(self) -> None:
        self.started_at = time.time()
        found: dict[str, HostResult] = {}
        try:
            with ThreadPoolExecutor(max_workers=max(1, self.options.threads)) as pool:
                for result in pool.map(self._one, self.addresses):
                    if result is not None:
                        found[result.ip] = result
            self._add_macs(found)
        finally:
            self.ended_at = time.time()
            self.finished.set()

    def _add_macs(self, found: dict[str, HostResult]) -> None:
        """Fill in MACs from the ARP table the pings just filled — and on
        Linux, count a device that answered ARP just now as on, even if it
        ignored the ping (phones do)."""
        neighbours = arp.read_neighbours()
        own_mac = arp.own_mac()
        late: list[HostResult] = []
        for ip, sent in found.items():
            # A fresh copy each time: the first one is already in the
            # window's hands, and it has to see what changed.
            result = replace(sent, ports=list(sent.ports))
            mac, confirmed = neighbours.get(ip, ("", False))
            if result.is_self and own_mac:
                mac = own_mac
            is_late = not result.alive and confirmed and not self.cancelled.is_set()
            if is_late:
                result.alive, result.method = True, "arp"
            if result.alive and mac:
                result.mac = mac
                result.vendor = vendors.vendor_for(mac)
            if is_late:
                late.append(result)
            elif result.mac:
                self.results.put(result)
        if late:
            with ThreadPoolExecutor(max_workers=max(1, min(16, self.options.threads))) as pool:
                for result in pool.map(lambda r: (complete_alive(r, self.options), r)[1], late):
                    self.results.put(result)
