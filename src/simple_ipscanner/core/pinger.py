"""Pinging one device by hand, once a second, like `ping` in a terminal."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from simple_ipscanner.core.ping import PingReply, manual_ping


@dataclass
class PingStats:
    sent: int = 0
    received: int = 0
    times: list[float] = field(default_factory=list)

    def add(self, reply: PingReply) -> None:
        self.sent += 1
        if reply.alive:
            self.received += 1
            if reply.ms is not None:
                self.times.append(reply.ms)

    @property
    def loss_percent(self) -> float:
        return 0.0 if not self.sent else 100.0 * (self.sent - self.received) / self.sent

    def summary(self) -> str:
        if not self.sent:
            return ""
        text = f"{self.sent} sent, {self.received} received, {self.loss_percent:.0f}% lost"
        if self.times:
            text += (f" · min {min(self.times):g} / avg {sum(self.times) / len(self.times):.1f}"
                     f" / max {max(self.times):g} ms")
        return text


class ContinuousPinger(threading.Thread):
    """Pings `ip` every `interval_s` until halted (or `count` times),
    leaving (sequence number, PingReply) in `.results`."""

    def __init__(self, ip: str, interval_s: float = 1.0, timeout_ms: int = 1000, count: Optional[int] = None,
                 ping_fn=manual_ping):
        super().__init__(daemon=True, name=f"ping-{ip}")
        self.ip = ip
        self.interval_s = interval_s
        self.timeout_ms = timeout_ms
        self.count = count
        self.results: "queue.Queue[tuple[int, PingReply]]" = queue.Queue()
        self._halt = threading.Event()
        self._ping = ping_fn

    def halt(self) -> None:
        self._halt.set()

    def run(self) -> None:
        seq = 0
        while not self._halt.is_set() and (self.count is None or seq < self.count):
            seq += 1
            started = time.monotonic()
            reply = self._ping(self.ip, self.timeout_ms)
            if self._halt.is_set():
                break
            self.results.put((seq, reply))
            self._halt.wait(max(0.0, self.interval_s - (time.monotonic() - started)))
