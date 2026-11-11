"""Turning what's typed in the range box into a list of addresses, and
working out this computer's own network to offer as the default."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional

# Bigger than this and a scan would take hours; /16 is the most anyone
# sensibly scans by hand.
MAX_ADDRESSES = 65_536
# The biggest network offered as "my network" without asking: a /22 is
# 1022 hosts. Anything bigger falls back to this computer's own /24.
MAX_AUTO_PREFIX = 22


class RangeError(ValueError):
    """The range text couldn't be understood (the message says why)."""


def _addr(text: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(text.strip())
    except ValueError:
        raise RangeError(f"“{text.strip()}” isn't an IP address") from None


def _part(text: str) -> list[ipaddress.IPv4Address]:
    text = text.strip()
    if not text:
        return []
    if "/" in text:
        try:
            net = ipaddress.IPv4Network(text, strict=False)
        except ValueError:
            raise RangeError(f"“{text}” isn't a network like 192.168.1.0/24") from None
        if net.num_addresses > MAX_ADDRESSES:
            raise RangeError(f"{text} has {net.num_addresses:,} addresses — the most is {MAX_ADDRESSES:,}")
        hosts = list(net.hosts())
        return hosts or [net.network_address]
    if "-" in text:
        start_text, end_text = (s.strip() for s in text.split("-", 1))
        start = _addr(start_text)
        if end_text.isdigit():
            # 192.168.1.10-50: the end is just the last number
            end_last = int(end_text)
            if end_last > 255:
                raise RangeError(f"“{end_text}” is more than 255")
            end = ipaddress.IPv4Address(int(start) & 0xFFFFFF00 | end_last)
        else:
            end = _addr(end_text)
        if int(end) < int(start):
            start, end = end, start
        count = int(end) - int(start) + 1
        if count > MAX_ADDRESSES:
            raise RangeError(f"that's {count:,} addresses — the most is {MAX_ADDRESSES:,}")
        return [ipaddress.IPv4Address(n) for n in range(int(start), int(end) + 1)]
    return [_addr(text)]


def parse_range(text: str) -> list[str]:
    """Addresses for text such as "192.168.1.1 - 192.168.1.254",
    "192.168.1.1-254", "192.168.1.0/24" or "10.0.0.5", several separated
    by commas. In order, without repeats."""
    seen: dict[int, ipaddress.IPv4Address] = {}
    for piece in text.replace(";", ",").split(","):
        for a in _part(piece):
            seen.setdefault(int(a), a)
            if len(seen) > MAX_ADDRESSES:
                raise RangeError(f"that's more than {MAX_ADDRESSES:,} addresses")
    if not seen:
        raise RangeError("type a range to scan, like 192.168.1.1 - 192.168.1.254")
    return [str(seen[n]) for n in sorted(seen)]


def ip_sort_key(ip: str) -> int:
    try:
        return int(ipaddress.IPv4Address(ip))
    except ValueError:
        return 0


@dataclass
class LocalNetwork:
    address: str  # this computer's IP on it
    network: ipaddress.IPv4Network
    interface: str = ""

    def range_text(self) -> str:
        net = self.network
        if net.prefixlen < MAX_AUTO_PREFIX:
            net = ipaddress.IPv4Network(f"{self.address}/24", strict=False)
        hosts = list(net.hosts())
        if not hosts:
            return self.address
        return f"{hosts[0]} - {hosts[-1]}"


def local_address() -> Optional[str]:
    """The IP this computer uses to reach the outside world. Connecting a
    UDP socket sends nothing; it only makes the OS pick a route."""
    for target in ("192.0.2.1", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 9))
                address = s.getsockname()[0]
        except OSError:
            continue
        if address and not address.startswith("127."):
            return address
    return None


def local_network() -> Optional[LocalNetwork]:
    """This computer's network, with its real netmask where psutil can
    tell it (else assumed to be a /24)."""
    address = local_address()
    if address is None:
        return None
    try:
        import psutil

        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and a.address == address and a.netmask:
                    return LocalNetwork(address, ipaddress.IPv4Network(f"{address}/{a.netmask}", strict=False), name)
    except Exception:
        pass
    return LocalNetwork(address, ipaddress.IPv4Network(f"{address}/24", strict=False))
