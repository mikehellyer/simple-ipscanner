"""What each address looked like at the last scan, so the next one can
say which devices have been switched off (or on) since."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

GONE = "gone"  # on at the last scan, off now
CAME = "came"  # off at the last scan, on now

CHANGE_TEXT = {GONE: "Switched off since last scan", CAME: "Switched on since last scan"}


class ScanHistory:
    """Per address: whether it was on at its last scan, and, for any that
    have ever been on, its name and MAC and when it was last seen — so a
    device that's gone can still be shown by name."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self.entries: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        kinds = {"alive": bool, "scanned": (int, float), "seen": (int, float), "hostname": str, "mac": str,
                 "vendor": str}
        for ip, entry in data.items():
            if isinstance(entry, dict):
                self.entries[ip] = {k: v for k, v in entry.items() if k in kinds and isinstance(v, kinds[k])}

    def save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self.entries, indent=1))
        except OSError:
            pass

    def get(self, ip: str) -> Optional[dict]:
        return self.entries.get(ip)

    def change_for(self, ip: str, alive_now: bool) -> Optional[str]:
        """GONE, CAME or None, against the last time this address was
        scanned. An address never scanned before has no change."""
        before = self.entries.get(ip)
        if before is None:
            return None
        was = bool(before.get("alive"))
        if was and not alive_now:
            return GONE
        if alive_now and not was:
            return CAME
        return None

    def record(self, results, when: Optional[float] = None) -> None:
        """Remember this scan: `results` are HostResults for just the
        addresses actually scanned (a stopped scan doesn't forget the
        rest)."""
        when = time.time() if when is None else when
        for r in results:
            entry = dict(self.entries.get(r.ip, {}))
            entry["alive"] = r.alive
            entry["scanned"] = when
            if r.alive:
                entry["seen"] = when
                if r.hostname:
                    entry["hostname"] = r.hostname
                if r.mac:
                    entry["mac"] = r.mac
                    entry["vendor"] = r.vendor
            self.entries[r.ip] = entry
        self.save()

    def forget(self) -> None:
        self.entries = {}
        self.save()
