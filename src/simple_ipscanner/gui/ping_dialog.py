"""The ping window: ping one device by hand, once a second, and watch the
replies come in."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout)

from simple_ipscanner.core import ping
from simple_ipscanner.core.pinger import ContinuousPinger, PingStats


class PingDialog(QDialog):
    watch_requested = Signal(str)

    def __init__(self, ip: str = "", label: str = "", timeout_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"Ping {label or ip}" if ip else "Ping a device")
        self.resize(560, 420)
        self._timeout_ms = timeout_ms
        self._pinger: ContinuousPinger | None = None
        self._stats = PingStats()

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Device:"))
        self._address = QLineEdit(ip)
        self._address.setPlaceholderText("IP address or hostname")
        self._address.returnPressed.connect(self._toggle)
        top.addWidget(self._address, stretch=1)
        top.addWidget(QLabel("Every"))
        self._interval = QSpinBox()
        self._interval.setRange(1, 60)
        self._interval.setValue(1)
        self._interval.setSuffix(" s")
        top.addWidget(self._interval)
        self._button = QPushButton("Start")
        self._button.setObjectName("primary")
        self._button.clicked.connect(self._toggle)
        top.addWidget(self._button)
        layout.addLayout(top)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(5000)
        self._log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        layout.addWidget(self._log, stretch=1)

        bottom = QHBoxLayout()
        self._stats_label = QLabel()
        self._stats_label.setProperty("role", "muted")
        bottom.addWidget(self._stats_label, stretch=1)
        watch = QPushButton("Watch this device…")
        watch.clicked.connect(lambda: self.watch_requested.emit(self._address.text().strip()))
        bottom.addWidget(watch)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        bottom.addWidget(clear)
        layout.addLayout(bottom)

        if not ping.icmp_available():
            self._log.appendPlainText("(ICMP ping isn't available here, so this knocks on common TCP ports instead)")

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._drain)
        if ip:
            QTimer.singleShot(0, self._start)

    def _toggle(self) -> None:
        if self._pinger is None:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        target = self._address.text().strip()
        if not target or " " in target:
            self._address.setFocus()
            return
        self.setWindowTitle(f"Ping {target}")
        self._log.appendPlainText(f"Pinging {target}…")
        self._pinger = ContinuousPinger(target, float(self._interval.value()), self._timeout_ms)
        self._pinger.start()
        self._timer.start()
        self._button.setText("Stop")
        self._button.setObjectName("stop")
        self._button.style().polish(self._button)
        self._address.setEnabled(False)
        self._interval.setEnabled(False)

    def _stop(self) -> None:
        if self._pinger is not None:
            self._pinger.halt()
            self._drain()
            self._pinger = None
        self._timer.stop()
        self._button.setText("Start")
        self._button.setObjectName("primary")
        self._button.style().polish(self._button)
        self._address.setEnabled(True)
        self._interval.setEnabled(True)
        if self._stats.sent:
            self._log.appendPlainText(f"— {self._stats.summary()}")

    def _drain(self) -> None:
        if self._pinger is None:
            return
        while not self._pinger.results.empty():
            seq, reply = self._pinger.results.get()
            self._stats.add(reply)
            stamp = time.strftime("%H:%M:%S")
            self._log.appendPlainText(f"{stamp}  #{seq:<4} {reply.text}")
        self._stats_label.setText(self._stats.summary())

    def _clear(self) -> None:
        self._log.clear()
        self._stats = PingStats()
        self._stats_label.clear()

    def closeEvent(self, event) -> None:
        self._stop()
        super().closeEvent(event)

    def done(self, result) -> None:  # Esc
        self._stop()
        super().done(result)
