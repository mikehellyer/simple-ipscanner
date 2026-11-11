"""The scan results table: one row per address, coloured by whether the
device is on, and highlighted if it's been switched off (or on) since
the last scan."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from simple_ipscanner.core.history import CAME, GONE
from simple_ipscanner.core.iprange import ip_sort_key
from simple_ipscanner.core.scanner import HostResult
from simple_ipscanner.core.watch import MODE_TEXT
from simple_ipscanner.gui import style

COLUMNS = ["IP address", "Ping", "Hostname", "Name", "MAC address", "Maker", "Open ports", "Beeps when",
           "Since last scan"]
IP, PING, HOST, NAME, MAC, MAKER, PORTS, WATCH, CHANGE = range(len(COLUMNS))
SORT_ROLE = Qt.UserRole + 1


@dataclass
class Row:
    ip: str
    result: Optional[HostResult] = None  # None until this address has been scanned
    change: Optional[str] = None  # GONE, CAME or None
    before: Optional[dict] = None  # the history entry from the last scan
    name: str = ""
    watch_mode: str = ""

    @property
    def alive(self) -> bool:
        return bool(self.result and self.result.alive)

    @property
    def mac(self) -> str:
        if self.result and self.result.mac:
            return self.result.mac
        return (self.before or {}).get("mac", "") if self.change == GONE else ""


def _when(stamp) -> str:
    if not stamp:
        return ""
    t = time.localtime(stamp)
    if time.strftime("%Y%m%d", t) == time.strftime("%Y%m%d"):
        return time.strftime("%H:%M", t)
    return time.strftime("%d %b %H:%M", t)


def ping_text(result: Optional[HostResult]) -> str:
    if result is None or not result.alive:
        return ""
    if result.method == "arp":
        return "ARP only"
    if result.ms is None:
        return "—"
    if result.ms < 1:
        return "<1 ms"
    return f"{result.ms:.0f} ms"


class ResultsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[Row] = []
        self._index: dict[str, int] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    # --- filling it

    def start(self, addresses: list[str], history, names) -> None:
        """A fresh scan: every address listed as not scanned yet, carrying
        what the last scan knew about it."""
        self.beginResetModel()
        self.rows = [Row(ip, before=history.get(ip)) for ip in addresses]
        self._index = {r.ip: i for i, r in enumerate(self.rows)}
        for r in self.rows:
            r.name = names(r.ip, (r.before or {}).get("mac", ""))
        self.endResetModel()

    def row_for(self, ip: str) -> Optional[Row]:
        i = self._index.get(ip)
        return None if i is None else self.rows[i]

    def set_result(self, result: HostResult, change: Optional[str], name: str) -> None:
        i = self._index.get(result.ip)
        if i is None:
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
            self.rows.append(Row(result.ip))
            i = self._index[result.ip] = len(self.rows) - 1
            self.endInsertRows()
        row = self.rows[i]
        row.result, row.change = result, change
        row.name = name or row.name
        self._changed(i)

    def set_name(self, ip: str, name: str) -> None:
        i = self._index.get(ip)
        if i is not None:
            self.rows[i].name = name
            self._changed(i)

    def set_watch_modes(self, modes: dict[str, str]) -> None:
        for i, row in enumerate(self.rows):
            mode = modes.get(row.ip, "")
            if mode != row.watch_mode:
                row.watch_mode = mode
                self._changed(i)

    def _changed(self, i: int) -> None:
        self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLUMNS) - 1))

    def scanned_results(self) -> list[HostResult]:
        return [r.result for r in self.rows if r.result is not None]

    # --- showing it

    def _text(self, row: Row, column: int) -> str:
        r, before = row.result, row.before or {}
        gone = row.change == GONE
        if column == IP:
            return row.ip + ("  (this computer)" if r and r.is_self else "")
        if column == PING:
            return ping_text(r)
        if column == HOST:
            return (r.hostname if r and r.alive else "") or (before.get("hostname", "") if gone else "")
        if column == NAME:
            return row.name
        if column == MAC:
            return row.mac
        if column == MAKER:
            return (r.vendor if r and r.alive else "") or (before.get("vendor", "") if gone else "")
        if column == PORTS:
            return ", ".join(str(p) for p in r.ports) if r and r.alive else ""
        if column == WATCH:
            return MODE_TEXT.get(row.watch_mode, "")
        if column == CHANGE:
            if gone:
                seen = _when(before.get("seen"))
                return "Switched off" + (f" (last seen {seen})" if seen else "")
            if row.change == CAME:
                return "Switched on"
        return ""

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, column = self.rows[index.row()], index.column()
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            text = self._text(row, column)
            if role == Qt.ToolTipRole:
                if column == PING and row.result and row.result.method.startswith("tcp:"):
                    return f"Didn't answer ping; answered on TCP port {row.result.method[4:]}"
                if column == PING and row.result and row.result.method == "arp":
                    return "Ignores ping, but answered the network's address lookup (ARP)"
                return None  # only the fixed notes above: a tooltip would render a hostname as HTML
            return text
        if role == Qt.DecorationRole and column == IP:
            if row.change == GONE:
                return style.dot(style.GONE)
            if row.result is None:
                return style.dot(style.FAINT, hollow=True)
            return style.dot(style.ON if row.alive else style.OFF)
        if role == Qt.BackgroundRole:
            if row.change == GONE:
                return QBrush(QColor(style.GONE_ROW))
            if row.change == CAME:
                return QBrush(QColor(style.CAME_ROW))
        if role == Qt.ForegroundRole:
            if row.change == GONE:
                return QBrush(QColor(style.GONE))
            if row.result is not None and not row.alive:
                return QBrush(QColor(style.MUTED))
        if role == Qt.FontRole and row.change is not None and column in (IP, CHANGE):
            font = QFont()
            font.setBold(True)
            return font
        if role == SORT_ROLE:
            if column == IP:
                return ip_sort_key(row.ip)
            if column == PING:
                r = row.result
                return r.ms if r and r.alive and r.ms is not None else (1e6 if row.alive else 1e9)
            if column == PORTS:
                return len(row.result.ports) if row.result else 0
            if column == CHANGE:
                return {GONE: 0, CAME: 1}.get(row.change, 2)
            return self._text(row, column).lower() or "￿"
        return None


class ResultsFilter(QSortFilterProxyModel):
    """"alive": devices that are on, plus any switched off since the last
    scan; "changes": only those switched off or on; "all": everything."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.show = "alive"
        self.setSortRole(SORT_ROLE)

    def set_show(self, show: str) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt 6.10+
            self.beginFilterChange()
            self.show = show
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.show = show
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        row = self.sourceModel().rows[source_row]
        if self.show == "all":
            return True
        if self.show == "changes":
            return row.change is not None
        return row.alive or row.change is not None
