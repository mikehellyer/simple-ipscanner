"""The Watching tab: devices being pinged every few seconds, each set to
beep when it goes offline, comes online, or either."""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from simple_ipscanner.core.watch import BOTH, DOWN, MODE_TEXT, OFFLINE, ONLINE, STATE_TEXT, UP, WatchList
from simple_ipscanner.gui import style

MODE_ORDER = [OFFLINE, ONLINE, BOTH]
HEADERS = ["State", "Name", "Address", "Beep when it…", "Since", "Last reply"]


def mode_choices() -> list[tuple[str, str]]:
    return [(OFFLINE, "Goes offline"), (ONLINE, "Comes online"), (BOTH, "Goes offline or comes online")]


class AddWatchDialog(QDialog):
    def __init__(self, ip: str = "", name: str = "", mode: str = OFFLINE, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Watch a device")
        form = QFormLayout(self)
        self.address = QLineEdit(ip)
        self.address.setPlaceholderText("e.g. 192.168.1.40")
        form.addRow("Address:", self.address)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("optional, e.g. Printer")
        form.addRow("Name:", self.name)
        self.mode = QComboBox()
        for key, text in mode_choices():
            self.mode.addItem(text, key)
        self.mode.setCurrentIndex(max(0, MODE_ORDER.index(mode) if mode in MODE_ORDER else 0))
        form.addRow("Beep when it:", self.mode)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        text = self.address.text().strip()
        if not text or " " in text:
            self.address.setFocus()
            return
        self.accept()

    def values(self) -> tuple[str, str, str]:
        return self.address.text().strip(), self.name.text().strip(), self.mode.currentData()


def _since(stamp) -> str:
    if not stamp:
        return ""
    seconds = int(time.time() - stamp)
    clock = time.strftime("%H:%M:%S", time.localtime(stamp))
    if seconds < 60:
        return f"{clock} (just now)"
    if seconds < 3600:
        return f"{clock} ({seconds // 60} min ago)"
    return f"{clock} ({seconds // 3600} h {seconds % 3600 // 60} min ago)"


class WatchPanel(QWidget):
    add_requested = Signal()
    remove_requested = Signal(str)
    mode_changed = Signal(str, str)
    ping_requested = Signal(str)
    test_beep = Signal()
    pause_toggled = Signal(bool)

    def __init__(self, watches: WatchList, parent=None):
        super().__init__(parent)
        self._watches = watches
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        bar = QHBoxLayout()
        add = QPushButton("Add device…")
        add.setObjectName("primary")
        add.clicked.connect(self.add_requested)
        bar.addWidget(add)
        self._remove = QPushButton("Stop watching")
        self._remove.clicked.connect(lambda: self._selected() and self.remove_requested.emit(self._selected()))
        bar.addWidget(self._remove)
        ping = QPushButton("Ping…")
        ping.clicked.connect(lambda: self._selected() and self.ping_requested.emit(self._selected()))
        bar.addWidget(ping)
        bar.addStretch(1)
        self._pause = QCheckBox("Pause watching")
        self._pause.toggled.connect(self.pause_toggled)
        bar.addWidget(self._pause)
        beep = QPushButton("Test beep")
        beep.clicked.connect(self.test_beep)
        bar.addWidget(beep)
        layout.addLayout(bar)

        self._hint = QLabel("No devices are being watched. Right-click a device in the scan results and pick "
                            "Watch, or click Add device.")
        self._hint.setProperty("role", "muted")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, len(HEADERS))
        self._table.setHorizontalHeaderLabels(HEADERS)
        self._table.verticalHeader().hide()
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.cellDoubleClicked.connect(lambda r, c: self.ping_requested.emit(self._ip_at(r)))
        layout.addWidget(self._table, stretch=1)
        self._ips: list[str] = []
        self.rebuild()

    def _ip_at(self, row: int) -> str:
        return self._ips[row] if 0 <= row < len(self._ips) else ""

    def _selected(self) -> str:
        rows = self._table.selectionModel().selectedRows()
        return self._ip_at(rows[0].row()) if rows else ""

    def rebuild(self) -> None:
        """After a device is added or removed."""
        self._ips = self._watches.ips()
        self._table.setRowCount(len(self._ips))
        for row, ip in enumerate(self._ips):
            watch = self._watches.items[ip]
            for col in range(len(HEADERS)):
                if col != 3:
                    self._table.setItem(row, col, QTableWidgetItem())
            combo = QComboBox()
            for key, text in mode_choices():
                combo.addItem(text, key)
            combo.setCurrentIndex(MODE_ORDER.index(watch.mode))
            combo.currentIndexChanged.connect(lambda _i, ip=ip, c=combo: self.mode_changed.emit(ip, c.currentData()))
            self._table.setCellWidget(row, 3, combo)
        self._hint.setVisible(not self._ips)
        self.refresh()

    def refresh(self) -> None:
        """After new check results (and every few seconds, for "since")."""
        for row, ip in enumerate(self._ips):
            watch = self._watches.items.get(ip)
            if watch is None:
                continue
            colour = {UP: style.ON, DOWN: style.GONE}.get(watch.state, style.WAITING)
            state = self._table.item(row, 0)
            state.setText(STATE_TEXT[watch.state])
            state.setIcon(style.dot(colour))
            self._table.item(row, 1).setText(watch.name)
            self._table.item(row, 2).setText(watch.ip)
            self._table.item(row, 4).setText(_since(watch.since))
            last = "—" if watch.last_ms is None else (
                "<1 ms" if watch.last_ms < 1 else f"{watch.last_ms:.0f} ms")
            self._table.item(row, 5).setText(last if watch.state == UP else "")

    def mode_text(self, ip: str) -> str:
        watch = self._watches.items.get(ip)
        return MODE_TEXT.get(watch.mode, "") if watch else ""

    def set_paused(self, paused: bool) -> None:
        self._pause.setChecked(paused)

