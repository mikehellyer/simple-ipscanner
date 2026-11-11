"""Settings: how scans and watching work, and the beep."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit,
                               QSlider, QSpinBox, QVBoxLayout)

from simple_ipscanner.core.ping import parse_ports


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        s = settings
        layout = QVBoxLayout(self)

        scan = QGroupBox("Scanning")
        form = QFormLayout(scan)
        self.threads = QSpinBox()
        self.threads.setRange(1, 256)
        self.threads.setValue(s.threads)
        form.addRow("Addresses at once:", self.threads)
        self.timeout = QSpinBox()
        self.timeout.setRange(100, 10_000)
        self.timeout.setSingleStep(100)
        self.timeout.setSuffix(" ms")
        self.timeout.setValue(s.timeout_ms)
        form.addRow("Wait for a reply:", self.timeout)
        self.ports = QLineEdit(s.ports_text)
        self.ports.setPlaceholderText("none — e.g. 22, 80, 443, 8000-8080")
        form.addRow("Check these ports:", self.ports)
        self.tcp = QCheckBox("Also find devices that ignore ping (knock on common ports)")
        self.tcp.setChecked(s.tcp_fallback)
        form.addRow(self.tcp)
        self.names = QCheckBox("Look up hostnames")
        self.names.setChecked(s.resolve_names)
        form.addRow(self.names)
        layout.addWidget(scan)

        watch = QGroupBox("Watching")
        form = QFormLayout(watch)
        self.interval = QSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setSuffix(" s")
        self.interval.setValue(s.watch_interval_s)
        form.addRow("Check every:", self.interval)
        self.misses = QSpinBox()
        self.misses.setRange(1, 20)
        self.misses.setValue(s.misses_needed)
        form.addRow("Offline after missed replies:", self.misses)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(s.beep_volume)
        form.addRow("Beep volume:", self.volume)
        self.repeat = QCheckBox("Keep beeping until Silence is clicked")
        self.repeat.setChecked(s.beep_until_silenced)
        form.addRow(self.repeat)
        layout.addWidget(watch)

        self._error = QLabel()
        self._error.setStyleSheet("color: #c0392b;")
        self._error.hide()
        layout.addWidget(self._error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        try:
            parse_ports(self.ports.text())
        except ValueError as error:
            self._error.setText(f"Ports: {error}")
            self._error.show()
            return
        self.accept()

    def changes(self) -> dict:
        return {
            "threads": self.threads.value(),
            "timeout_ms": self.timeout.value(),
            "ports_text": self.ports.text().strip(),
            "tcp_fallback": self.tcp.isChecked(),
            "resolve_names": self.names.isChecked(),
            "watch_interval_s": self.interval.value(),
            "misses_needed": self.misses.value(),
            "beep_volume": self.volume.value(),
            "beep_until_silenced": self.repeat.isChecked(),
        }
