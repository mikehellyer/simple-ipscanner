"""The alarm beeps, made here as WAV files rather than shipped: falling
notes for "went offline", rising for "came online"."""
from __future__ import annotations

import io
import math
import struct
import wave

RATE = 22_050

OFFLINE_NOTES = [(988, 160), (0, 40), (740, 160), (0, 40), (494, 320)]
ONLINE_NOTES = [(523, 120), (0, 30), (659, 120), (0, 30), (784, 120), (0, 30), (1047, 240)]


def tone_wav(notes: list[tuple[float, int]], volume: float = 0.6) -> bytes:
    """A WAV of (frequency Hz, milliseconds) notes; 0 Hz is a rest. Each
    note fades in and out over a few ms so it doesn't click."""
    volume = max(0.0, min(1.0, volume))
    frames = bytearray()
    for freq, ms in notes:
        n = int(RATE * ms / 1000)
        fade = max(1, int(RATE * 0.008))
        for i in range(n):
            if freq <= 0:
                sample = 0.0
            else:
                env = min(1.0, i / fade, (n - 1 - i) / fade)
                sample = math.sin(2 * math.pi * freq * i / RATE) * env * volume
            frames += struct.pack("<h", int(sample * 32_000))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return out.getvalue()
