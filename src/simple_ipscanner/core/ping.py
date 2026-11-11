"""Is a device there? Asked the way Angry IP Scanner does: an ICMP ping
(through the system's own `ping`, which needs no admin rights), and for
devices that ignore pings, a knock on a few common TCP ports — even a
refused connection proves something answered."""
from __future__ import annotations

import ipaddress
import ntpath
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

# Tried when a ping goes unanswered. 62078 is iPhones' sync port and 7000
# AirPlay; phones in particular ignore pings but answer one of these.
PROBE_PORTS = (80, 443, 22, 445, 62078, 7000)

_TIME = re.compile(r"[=<]\s*([\d]+(?:[.,]\d+)?)\s*ms", re.IGNORECASE)
_TTL = re.compile(r"ttl[=:]\s*(\d+)", re.IGNORECASE)


@dataclass
class PingReply:
    alive: bool
    ms: Optional[float] = None  # round trip; None if unknown or no reply
    ttl: Optional[int] = None
    method: str = ""  # "ping" or "tcp:<port>" — what got an answer
    text: str = ""  # one line for the ping window


_HOSTNAME = re.compile(
    r"^(?=.{1,253}\.?$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$"
)


def is_valid_target(text: str) -> bool:
    """An IPv4 address or a plain hostname — nothing that `ping` could
    mistake for an option (like "-f"), whether typed in or read back from
    a settings file."""
    try:
        ipaddress.IPv4Address(text)
        return True
    except ValueError:
        return bool(_HOSTNAME.match(text or ""))


def system_tool(name: str, platform: str = sys.platform) -> str:
    """The full path of a system program. On Windows a bare "ping" is
    looked for in the current folder first, so a ping.exe left there
    would run instead; System32 is where the real one lives."""
    if platform == "win32":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return ntpath.join(root, "System32", f"{name.upper()}.EXE")
    return shutil.which(name) or name


def ping_command(ip: str, timeout_ms: int, platform: str = sys.platform) -> list[str]:
    if not is_valid_target(ip):
        raise ValueError(f"not an address or hostname: {ip!r}")
    ping = system_tool("ping", platform)
    if platform == "win32":
        return [ping, "-n", "1", "-w", str(max(1, timeout_ms)), ip]
    if platform == "darwin":
        return [ping, "-n", "-c", "1", "-W", str(max(1, timeout_ms)), ip]
    # Linux iputils: -W is in seconds (fractions allowed on any recent one).
    return [ping, "-n", "-c", "1", "-W", f"{max(0.2, timeout_ms / 1000):g}", ip]


def parse_ping_output(output: str, returncode: int) -> PingReply:
    """Read one ping's output. Windows says "Reply from … Destination host
    unreachable" with exit code 0, so a reply only counts if it has a TTL
    — which every real echo reply shows, in any language."""
    ttl_match = _TTL.search(output)
    if returncode != 0 or not ttl_match:
        return PingReply(False, text="no reply")
    time_match = _TIME.search(output)
    ms = float(time_match.group(1).replace(",", ".")) if time_match else None
    if ms is not None and re.search(r"<\s*1\s*ms", output):
        ms = 0.5
    ttl = int(ttl_match.group(1))
    parts = ["reply"]
    if ms is not None:
        parts.append("time <1 ms" if ms == 0.5 else f"time {ms:g} ms")
    parts.append(f"TTL {ttl}")
    return PingReply(True, ms, ttl, "ping", ", ".join(parts))


def icmp_ping(ip: str, timeout_ms: int = 1000) -> PingReply:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: no console flashing up
    try:
        command = ping_command(ip, timeout_ms)
    except ValueError:
        return PingReply(False, text="not a valid address")
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace",
            timeout=timeout_ms / 1000 + 3, **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        return PingReply(False, text="no reply")
    return parse_ping_output(result.stdout + result.stderr, result.returncode)


@lru_cache(maxsize=1)
def icmp_available() -> bool:
    """Whether the system ping works here at all (it can't inside some
    sandboxes, which strip its permission to send ICMP). Without it,
    devices are found by TCP and ARP alone."""
    return icmp_ping("127.0.0.1", 1000).alive


def tcp_ping(ip: str, timeout_ms: int = 1000) -> PingReply:
    """A ping by TCP knock, for when ICMP isn't available."""
    return tcp_probe(ip, timeout_s=min(1.0, max(0.15, timeout_ms / 1000)))


def manual_ping(ip: str, timeout_ms: int = 1000) -> PingReply:
    """The ping window's ping: ICMP, or a TCP knock where that can't run."""
    return icmp_ping(ip, timeout_ms) if icmp_available() else tcp_ping(ip, timeout_ms)


def tcp_probe(ip: str, ports=PROBE_PORTS, timeout_s: float = 0.3) -> PingReply:
    """Knock on each port; an accepted *or refused* connection both mean
    the device is on (a refusal is the device itself saying no)."""
    for port in ports:
        start = time.perf_counter()
        try:
            with socket.create_connection((ip, port), timeout=timeout_s):
                pass
        except ConnectionRefusedError:
            pass
        except OSError:
            continue
        ms = (time.perf_counter() - start) * 1000
        return PingReply(True, round(ms, 1), None, f"tcp:{port}", f"answered on TCP port {port}, {ms:.1f} ms")
    return PingReply(False, text="no reply")


def is_alive(ip: str, timeout_ms: int = 1000, tcp_fallback: bool = True) -> PingReply:
    reply = icmp_ping(ip, timeout_ms) if icmp_available() else PingReply(False, text="no reply")
    # Without ICMP the TCP knock is the only way left, wanted or not.
    if reply.alive or (icmp_available() and not tcp_fallback):
        return reply
    probe = tcp_probe(ip, timeout_s=min(0.5, max(0.15, timeout_ms / 3000)))
    return probe if probe.alive else reply


def open_ports(ip: str, ports, timeout_s: float = 0.4) -> list[int]:
    """The ports in `ports` that accept a connection."""
    found = []
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=timeout_s):
                found.append(port)
        except OSError:
            pass
    return found


def parse_ports(text: str) -> list[int]:
    """"22, 80, 8000-8010" → [22, 80, 8000, …]. Raises ValueError."""
    ports: list[int] = []
    for piece in text.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "-" in piece:
            a, b = (int(x) for x in piece.split("-", 1))
            if a > b:
                a, b = b, a
            if b - a > 1000:
                raise ValueError(f"{piece} is too many ports")
            ports.extend(range(a, b + 1))
        else:
            ports.append(int(piece))
    for p in ports:
        if not 1 <= p <= 65535:
            raise ValueError(f"{p} isn't a port number")
    return sorted(set(ports))


def resolve_hostname(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return ""
    return "" if name == ip else name
