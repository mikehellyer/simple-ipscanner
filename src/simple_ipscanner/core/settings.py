"""Persisted user preferences, plus the names given to devices and the
watch list (devices.json)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir


@dataclass
class Settings:
    # The window's size and place, as Qt's saveGeometry() gives it (hex),
    # and the results table's column layout.
    geometry: str = ""
    header_state: str = ""
    # The last range scanned ("" = this computer's network).
    range_text: str = ""
    # Scanning
    threads: int = 64
    timeout_ms: int = 1000
    ports_text: str = ""
    tcp_fallback: bool = True
    resolve_names: bool = True
    # Which rows to show: "alive" (on, plus changes), "all", or "changes".
    show: str = "alive"
    # Watching
    watch_interval_s: int = 5
    misses_needed: int = 2
    beep_volume: int = 70  # percent
    beep_until_silenced: bool = False


def config_dir() -> Path:
    return Path(user_config_dir("Simple-IPScanner"))


def default_config_path() -> Path:
    return config_dir() / "settings.json"


class SettingsStore:
    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or default_config_path()
        self.settings = Settings()
        self.load()

    @property
    def directory(self) -> Path:
        return self._config_path.parent

    def update(self, **changes) -> None:
        for name, value in changes.items():
            if not hasattr(self.settings, name):
                raise AttributeError(name)
            setattr(self.settings, name, value)
        self.save()

    def load(self) -> None:
        try:
            data = json.loads(self._config_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        defaults = Settings()
        for f in fields(Settings):
            if f.name not in data:
                continue
            value, default = data[f.name], getattr(defaults, f.name)
            if type(value) is not type(default):
                continue
            setattr(self.settings, f.name, value)
        s = self.settings
        s.threads = min(256, max(1, s.threads))
        s.timeout_ms = min(10_000, max(100, s.timeout_ms))
        s.watch_interval_s = min(3600, max(1, s.watch_interval_s))
        s.misses_needed = min(20, max(1, s.misses_needed))
        s.beep_volume = min(100, max(0, s.beep_volume))
        if s.show not in ("alive", "all", "changes"):
            s.show = "alive"

    def save(self) -> None:
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(json.dumps(asdict(self.settings), indent=2))
        except OSError:
            pass


class DeviceBook:
    """Names given to devices — kept against the MAC where there is one,
    so a name follows a device whose IP changes — and the watch list."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self.names: dict[str, str] = {}
        self.watches: list[dict] = []
        if path is not None:
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                data = {}
            if isinstance(data, dict):
                if isinstance(data.get("names"), dict):
                    self.names = {str(k): str(v) for k, v in data["names"].items()}
                if isinstance(data.get("watches"), list):
                    self.watches = data["watches"]

    def name_for(self, ip: str, mac: str = "") -> str:
        # A name given to this address itself wins over one for its MAC.
        if ip in self.names:
            return self.names[ip]
        return self.names.get(mac, "") if mac else ""

    def set_name(self, ip: str, mac: str, name: str, mac_shared: bool = False) -> None:
        """Name a device. Normally the name goes against its MAC, so it
        follows the device to a new IP. But when other addresses answer
        with the same MAC (one machine with Wi-Fi and a cable, say — see
        ResultsModel.shared_with), it goes against this address alone, so
        naming one doesn't rename the others; an empty name is then kept
        too, to hide the MAC's name for just this address."""
        name = name.strip()
        if mac_shared and mac:
            self.names[ip] = name
        else:
            for key in (mac, ip):
                if key:
                    self.names.pop(key, None)
            if name:
                self.names[mac or ip] = name
        self.save()

    def save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"names": self.names, "watches": self.watches}, indent=2))
        except OSError:
            pass
