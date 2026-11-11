"""MAC addresses from the OS's ARP table — filled in by the pings
themselves, so it's read after a scan rather than asked separately."""
from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

from simple_ipscanner.core.ping import system_tool

_MAC = re.compile(r"([0-9a-f]{1,2}[:-]){5}[0-9a-f]{1,2}", re.IGNORECASE)
_IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_EMPTY = {"00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}


def normalise_mac(mac: str) -> str:
    parts = re.split(r"[:-]", mac.strip())
    return ":".join(p.zfill(2) for p in parts).upper()


def parse_proc_arp(text: str) -> dict[str, str]:
    """Linux /proc/net/arp. Flags 0x0 are lookups that got no answer."""
    table = {}
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 4 and cols[2] != "0x0":
            mac = normalise_mac(cols[3])
            if mac not in _EMPTY:
                table[cols[0]] = mac
    return table


def parse_arp_a(text: str) -> dict[str, str]:
    """`arp -a` on macOS ("? (192.168.1.1) at a4:2b:…") and Windows
    ("  192.168.1.1   a4-2b-…   dynamic")."""
    table = {}
    for line in text.splitlines():
        ip_match, mac_match = _IP.search(line), _MAC.search(line)
        if ip_match and mac_match:
            mac = normalise_mac(mac_match.group(0))
            if mac not in _EMPTY and not mac.startswith("01:00:5E"):  # not multicast
                table[ip_match.group(1)] = mac
    return table


def parse_ip_neigh(text: str) -> dict[str, tuple[str, bool]]:
    """Linux `ip -4 neigh show`: IP → (MAC, confirmed). Only REACHABLE is
    confirmed — a STALE entry can be a device switched off minutes ago."""
    table = {}
    for line in text.splitlines():
        cols = line.split()
        if "lladdr" not in cols or not cols:
            continue
        mac = normalise_mac(cols[cols.index("lladdr") + 1])
        state = cols[-1].upper()
        if mac not in _EMPTY and state not in ("FAILED", "INCOMPLETE"):
            table[cols[0]] = (mac, state in ("REACHABLE", "PERMANENT"))
    return table


def read_neighbours() -> dict[str, tuple[str, bool]]:
    """IP → (MAC, confirmed reachable just now) for every neighbour the OS
    knows. Only Linux can say whether an entry is fresh; elsewhere none
    are counted as confirmed. Empty if it can't tell at all."""
    kwargs = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    if sys.platform.startswith("linux"):
        try:
            result = subprocess.run([system_tool("ip"), "-4", "neigh", "show"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return parse_ip_neigh(result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            return {ip: (mac, False) for ip, mac in parse_proc_arp(Path("/proc/net/arp").read_text()).items()}
        except OSError:
            return {}
    try:
        result = subprocess.run([system_tool("arp"), "-a"], capture_output=True, text=True, errors="replace", timeout=10, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return {ip: (mac, False) for ip, mac in parse_arp_a(result.stdout).items()}


def own_mac() -> str:
    """This computer's MAC (its own address is never in its ARP table).
    uuid.getnode() makes one up if it can't find one; that's flagged by
    the multicast bit, so it's left out."""
    node = uuid.getnode()
    if (node >> 40) & 1:
        return ""
    return ":".join(f"{(node >> s) & 0xFF:02X}" for s in range(40, -1, -8))
