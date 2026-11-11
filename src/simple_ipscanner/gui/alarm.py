"""The alarm: a beep (falling notes for "went offline", rising for "came
online") and a red banner saying which device, with a Silence button."""
from __future__ import annotations

import time
from pathlib import Path

from platformdirs import user_cache_dir
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from simple_ipscanner.core import sound
from simple_ipscanner.core.watch import UP

REPEAT_EVERY_MS = 3000


class Beeper:
    """Plays the two alarm sounds. Falls back to the system bell if Qt's
    sound playback isn't available."""

    def __init__(self, volume_percent: int = 70):
        self._effects = {}
        self._volume = volume_percent / 100
        try:
            from PySide6.QtMultimedia import QSoundEffect
        except ImportError:
            return
        folder = Path(user_cache_dir("Simple-IPScanner"))
        for kind, notes in (("offline", sound.OFFLINE_NOTES), ("online", sound.ONLINE_NOTES)):
            path = folder / f"{kind}.wav"
            try:
                folder.mkdir(parents=True, exist_ok=True)
                path.write_bytes(sound.tone_wav(notes, 0.9))
            except OSError:
                continue
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setVolume(self._volume)
            self._effects[kind] = effect

    def set_volume(self, volume_percent: int) -> None:
        self._volume = volume_percent / 100
        for effect in self._effects.values():
            effect.setVolume(self._volume)

    def play(self, kind: str, times: int = 1) -> None:
        effect = self._effects.get(kind)
        if effect is None or effect.status() == effect.Status.Error:
            QApplication.beep()
            return
        effect.setLoopCount(max(1, times))
        effect.play()

    def stop(self) -> None:
        for effect in self._effects.values():
            effect.stop()


class AlarmBanner(QWidget):
    """Shows the latest alerts until dismissed; while it's up, the beep can
    keep repeating (if that's switched on) until Silence is clicked."""

    silenced = Signal()

    def __init__(self, beeper: Beeper, parent=None):
        super().__init__(parent)
        self._beeper = beeper
        self._lines: list[str] = []
        self._kind = "offline"
        self.repeat = False
        self.setObjectName("alarm")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#alarm { background: #fde3e0; border-radius: 8px; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self._label = QLabel()
        self._label.setStyleSheet("color: #b02a20; font-weight: 600;")
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        layout.addWidget(self._label, stretch=1)
        self._silence = QPushButton("Silence")
        self._silence.setObjectName("stop")
        self._silence.clicked.connect(self.silence)
        layout.addWidget(self._silence)
        close = QPushButton("×")
        close.setFlat(True)
        close.setFixedWidth(28)
        close.setStyleSheet("color: #b02a20; font-weight: 600; border: none; background: transparent;")
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)

        self._repeat_timer = QTimer(self)
        self._repeat_timer.setInterval(REPEAT_EVERY_MS)
        self._repeat_timer.timeout.connect(lambda: self._beeper.play(self._kind))
        self.hide()

    def raise_alarm(self, event) -> None:
        self._kind = "online" if event.went == UP else "offline"
        self._lines.insert(0, f"{time.strftime('%H:%M:%S', time.localtime(event.at))}  {event.text()}")
        del self._lines[5:]
        self._label.setText("\n".join(self._lines))
        self._beeper.play(self._kind, times=1 if self.repeat else 3)
        if self.repeat:
            self._repeat_timer.start()
        self._silence.setVisible(self.repeat)
        self.show()
        window = self.window()
        if window is not None:
            QApplication.alert(window)  # flash the taskbar entry

    def silence(self) -> None:
        self._repeat_timer.stop()
        self._beeper.stop()
        self._silence.hide()
        self.silenced.emit()

    def dismiss(self) -> None:
        self.silence()
        self._lines.clear()
        self.hide()
