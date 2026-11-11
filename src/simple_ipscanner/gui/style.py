"""The look: a plain light window, blue for actions, green for devices
that are on, and red for ones that have gone off."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QStyleFactory

INK = "#1d1f24"
MUTED = "#6b7079"
FAINT = "#b8bcc4"
LINE = "#dfe2e7"
PAPER = "#ffffff"
PAGE = "#f3f4f7"
ACCENT = "#2f6fdf"
ACCENT_SOFT = "#bcd0f5"

ON = "#1e9e5a"
OFF = "#9aa0a8"
GONE = "#d0362b"
GONE_ROW = "#fde3e0"
CAME_ROW = "#dcf3e5"
WAITING = "#e0a020"

STYLE = f"""
QWidget {{ color: {INK}; font-size: 10pt; }}
QMainWindow {{ background: {PAGE}; }}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="title"] {{ font-size: 12pt; font-weight: 700; }}
QPushButton {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 6px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: {FAINT}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; padding: 6px 22px; }}
QPushButton#primary:disabled {{ background: {ACCENT_SOFT}; }}
QPushButton#stop {{ background: {GONE}; color: white; border: none; font-weight: 600; padding: 6px 22px; }}
QLineEdit, QSpinBox, QComboBox {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 6px; padding: 4px 8px; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QTableView, QTableWidget {{ background: {PAPER}; border: 1px solid {LINE}; gridline-color: {LINE};
    selection-background-color: {ACCENT}; selection-color: white; }}
QHeaderView::section {{ background: {PAGE}; border: none; border-right: 1px solid {LINE};
    border-bottom: 1px solid {LINE}; padding: 4px 6px; font-weight: 600; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 7px 16px; color: {MUTED}; font-weight: 600;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom-color: {ACCENT}; }}
QPlainTextEdit {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 6px; }}
QGroupBox {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px; margin-top: 12px;
    padding: 12px 10px 8px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; font-weight: 700; }}
QStatusBar {{ background: {PAPER}; color: {MUTED}; border-top: 1px solid {LINE}; }}
QProgressBar {{ border: 1px solid {LINE}; border-radius: 4px; background: {PAGE}; max-height: 10px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QMenu {{ background: {PAPER}; color: {INK}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QToolTip {{ background: {PAPER}; color: {INK}; border: 1px solid {LINE}; padding: 4px; }}
"""


def apply(app: QApplication) -> None:
    """A light look whatever the desktop's theme, so it reads the same on
    every machine."""
    app.setStyle(QStyleFactory.create("Fusion"))
    palette = QPalette()
    for role, colour in ((QPalette.Window, PAGE), (QPalette.Base, PAPER), (QPalette.AlternateBase, "#f8f9fb"),
                         (QPalette.Text, INK), (QPalette.WindowText, INK), (QPalette.Button, PAPER),
                         (QPalette.ButtonText, INK), (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
                         (QPalette.ToolTipBase, PAPER), (QPalette.ToolTipText, INK), (QPalette.PlaceholderText, MUTED),
                         (QPalette.Link, ACCENT)):
        palette.setColor(role, QColor(colour))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


_dots: dict[str, QIcon] = {}


def dot(colour: str, hollow: bool = False) -> QIcon:
    """A small round status light."""
    key = colour + ("o" if hollow else "")
    if key not in _dots:
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(colour)
        if hollow:
            p.setPen(c)
            p.setBrush(Qt.NoBrush)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(c)
        p.drawEllipse(2, 2, 10, 10)
        p.end()
        _dots[key] = QIcon(pixmap)
    return _dots[key]
