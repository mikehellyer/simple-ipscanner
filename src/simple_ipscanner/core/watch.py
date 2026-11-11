"""Watching devices: pinging each one every few seconds, and deciding when
it has really gone offline or come online (and whether that's worth a
beep)."""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Optional

from simple_ipscanner.core import ping

# What to beep for.
OFFLINE, ONLINE, BOTH = "offline", "online", "both"
MODE_TEXT = {OFFLINE: "Goes offline", ONLINE: "Comes online", BOTH: "Either"}

UNKNOWN, UP, DOWN = "unknown", "up", "down"
STATE_TEXT = {UNKNOWN: "Checking…", UP: "Online", DOWN: "Offline"}


@dataclass
class Watch:
    ip: str
    mode: str = OFFLINE
    name: str = ""
    state: str = UNKNOWN
    since: Optional[float] = None
    last_ms: Optional[float] = None
    last_check: Optional[float] = None
    misses: int = 0

    def label(self) -> str:
        return f"{self.name} ({self.ip})" if self.name else self.ip


@dataclass
class WatchEvent:
    watch: Watch
    went: str  # UP or DOWN
    alert: bool  # whether this watch's mode asks for a beep
    at: float

    def text(self) -> str:
        return f"{self.watch.label()} {'came online' if self.went == UP else 'went offline'}"


class WatchList:
    """The watched devices and their states. One reply brings a device
    online; it only counts as offline after `misses_needed` checks in a
    row go unanswered, so a single lost ping doesn't set off the alarm."""

    def __init__(self, misses_needed: int = 2):
        self.misses_needed = max(1, misses_needed)
        self.items: dict[str, Watch] = {}

    def add(self, ip: str, mode: str = OFFLINE, name: str = "") -> Watch:
        watch = self.items.get(ip)
        if watch is None:
            watch = self.items[ip] = Watch(ip, mode, name)
        else:
            watch.mode = mode
            watch.name = name or watch.name
        return watch

    def remove(self, ip: str) -> None:
        self.items.pop(ip, None)

    def ips(self) -> list[str]:
        return list(self.items)

    def observe(self, ip: str, alive: bool, ms: Optional[float] = None,
                now: Optional[float] = None) -> Optional[WatchEvent]:
        """Take one check's result. Returns an event when the device has
        changed state — never on the first check, which only finds out
        where things stand."""
        watch = self.items.get(ip)
        if watch is None:
            return None
        now = time.time() if now is None else now
        watch.last_check = now
        if alive:
            watch.misses = 0
            watch.last_ms = ms
            new_state = UP
        else:
            watch.misses += 1
            watch.last_ms = None
            if watch.state == UP and watch.misses < self.misses_needed:
                return None
            new_state = DOWN
        if new_state == watch.state:
            return None
        before = watch.state
        watch.state, watch.since = new_state, now
        if before == UNKNOWN:
            return None
        alert = watch.mode == BOTH or (watch.mode == OFFLINE and new_state == DOWN) or (
            watch.mode == ONLINE and new_state == UP)
        return WatchEvent(watch, new_state, alert, now)

    def to_json(self) -> list[dict]:
        return [{"ip": w.ip, "mode": w.mode, "name": w.name} for w in self.items.values()]

    def load_json(self, data) -> None:
        if not isinstance(data, list):
            return
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("ip"), str) and ping.is_valid_target(item["ip"]):
                mode = item.get("mode") if item.get("mode") in MODE_TEXT else OFFLINE
                self.add(item["ip"], mode, str(item.get("name", "")))


class WatchMonitor(threading.Thread):
    """Checks every target every `interval` seconds and leaves
    (ip, alive, ms) in `.results`. Targets can change while it runs."""

    def __init__(self, interval_s: float = 5, timeout_ms: int = 1000):
        super().__init__(daemon=True, name="watch-monitor")
        self.interval_s = interval_s
        self.timeout_ms = timeout_ms
        self.results: "queue.Queue[tuple[str, bool, Optional[float]]]" = queue.Queue()
        self._targets: list[str] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._halt = threading.Event()  # (not `_stop`: that's Thread's own)
        self.paused = False

    def set_targets(self, ips: list[str]) -> None:
        with self._lock:
            self._targets = list(ips)

    def check_now(self) -> None:
        self._wake.set()

    def halt(self) -> None:
        self._halt.set()
        self._wake.set()

    def _check(self, ip: str) -> None:
        reply = ping.is_alive(ip, self.timeout_ms)
        if not self._halt.is_set():
            self.results.put((ip, reply.alive, reply.ms))

    def run(self) -> None:
        with ThreadPoolExecutor(max_workers=16) as pool:
            while not self._halt.is_set():
                with self._lock:
                    targets = list(self._targets)
                if targets and not self.paused:
                    list(pool.map(self._check, targets))
                self._wake.wait(self.interval_s)
                self._wake.clear()


def watch_as_dict(watch: Watch) -> dict:
    return asdict(watch)
