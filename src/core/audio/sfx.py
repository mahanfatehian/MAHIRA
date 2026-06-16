"""Offline game sound effects for Blitz.

No audio assets are shipped — the effects are *synthesized* with numpy on first
use and cached as small WAVs under the app's writable state dir, then played
through a pool of pre-loaded `QSoundEffect`s so rapid combo hits overlap instead
of cutting each other off.

Everything degrades to silence rather than raising: if numpy, QtMultimedia, or
the audio device is unavailable, `SfxEngine` simply no-ops. That keeps the game
playable on a machine with no sound stack.
"""

from __future__ import annotations

import wave
from pathlib import Path

# Bump when the synthesis below changes so stale cached WAVs are regenerated.
_SFX_VERSION = "v1"
_RATE = 44100

# A major-pentatonic ladder; the hit pitch climbs this as the combo grows, so a
# long streak literally sounds like it's ascending.
_PENTATONIC = [523.25, 587.33, 659.25, 783.99, 880.00, 1046.50, 1174.66, 1318.51]


def _sfx_dir() -> Path:
    try:
        from mahira.config import STATE_DIRNAME, data_root

        d = data_root() / STATE_DIRNAME / "sfx"
    except Exception:
        d = Path.home() / ".mahira" / "sfx"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Synthesis (numpy). Pure: produces float32 arrays in [-1, 1].
# --------------------------------------------------------------------------- #
def _synthesize_all(out_dir: Path) -> dict[str, Path]:
    """Generate every SFX WAV that is missing and return name -> path."""
    import numpy as np

    rng = np.random.default_rng(7)  # deterministic so cached files are stable

    def ping(freq: float, dur: float = 0.16, decay: float = 22.0, shimmer: bool = True):
        n = int(_RATE * dur)
        t = np.arange(n) / _RATE
        w = np.sin(2 * np.pi * freq * t)
        if shimmer:
            w = w + 0.30 * np.sin(2 * np.pi * freq * 2 * t)
            w = w + 0.12 * np.sin(2 * np.pi * freq * 3 * t)
        env = np.exp(-t * decay)
        a = int(_RATE * 0.004)
        if a > 0:
            env[:a] *= np.linspace(0.0, 1.0, a)
        return w * env

    def mix(parts: list[tuple[float, "np.ndarray"]]) -> "np.ndarray":
        total = int(max((off + len(s) / _RATE) for off, s in parts) * _RATE) + 1
        buf = np.zeros(total, dtype=np.float64)
        for off, s in parts:
            i = int(off * _RATE)
            buf[i:i + len(s)] += s
        return buf

    sounds: dict[str, "np.ndarray"] = {}

    # Hit ladder — one bright ping per pentatonic step.
    for i, freq in enumerate(_PENTATONIC, start=1):
        sounds[f"hit{i}"] = ping(freq, dur=0.16, decay=20.0)

    # Miss — a short descending thud with a noise transient.
    n = int(_RATE * 0.26)
    t = np.arange(n) / _RATE
    f = np.linspace(200.0, 90.0, n)
    phase = 2 * np.pi * np.cumsum(f) / _RATE
    body = np.sin(phase) * 0.8
    noise = (rng.random(n) * 2 - 1) * 0.25 * np.exp(-t * 30.0)
    sounds["miss"] = (body + noise) * np.exp(-t * 9.0)

    # Milestone — a quick triumphant arpeggio.
    sounds["milestone"] = mix([
        (0.00, ping(659.25, 0.20, 16.0)),
        (0.07, ping(880.00, 0.20, 16.0)),
        (0.14, ping(1174.66, 0.28, 13.0)),
    ])

    # Start — a rising sweep.
    n = int(_RATE * 0.28)
    t = np.arange(n) / _RATE
    f = np.linspace(320.0, 920.0, n)
    phase = 2 * np.pi * np.cumsum(f) / _RATE
    env = np.minimum(1.0, t / 0.02) * np.exp(-t * 4.0)
    sounds["start"] = np.sin(phase) * env

    # Finish — a four-note victory motif.
    sounds["finish"] = mix([
        (0.00, ping(523.25, 0.22, 12.0)),
        (0.12, ping(659.25, 0.22, 12.0)),
        (0.24, ping(783.99, 0.22, 12.0)),
        (0.36, ping(1046.50, 0.42, 9.0)),
    ])

    # Prune WAVs from a previous _SFX_VERSION so a bump doesn't leak stale files
    # (this dir is dedicated to SFX, so a blanket sweep is safe).
    suffix = f".{_SFX_VERSION}.wav"
    try:
        for stale in out_dir.glob("*.wav"):
            if not stale.name.endswith(suffix):
                stale.unlink(missing_ok=True)
    except Exception:
        pass

    paths: dict[str, Path] = {}
    for name, samples in sounds.items():
        path = out_dir / f"{name}.{_SFX_VERSION}.wav"
        paths[name] = path
        if path.exists():
            continue
        _write_wav(path, samples)
    return paths


def _write_wav(path: Path, samples) -> None:
    import numpy as np

    peak = float(np.max(np.abs(samples))) or 1.0
    data = (np.clip(samples / peak * 0.85, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(_RATE)
        wav_file.writeframes(data.tobytes())


# --------------------------------------------------------------------------- #
# Playback engine (Qt). Degrades to silence on any failure.
# --------------------------------------------------------------------------- #
class SfxEngine:
    """Pre-loads each cached effect into its own `QSoundEffect` and plays them on
    demand. Distinct combo notes use distinct effect objects, so a fast streak
    overlaps naturally."""

    def __init__(self, parent=None, volume: float = 0.6) -> None:
        self._ok = False
        self._muted = False
        self._volume = float(volume)
        self._effects: dict[str, object] = {}
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect

            paths = _synthesize_all(_sfx_dir())
            for name, path in paths.items():
                eff = QSoundEffect(parent)
                eff.setSource(QUrl.fromLocalFile(str(path)))
                eff.setVolume(self._volume)
                self._effects[name] = eff
            self._ok = bool(self._effects)
        except Exception:
            self._ok = False

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))
        for eff in self._effects.values():
            try:
                eff.setVolume(self._volume)
            except Exception:
                pass

    def _play(self, name: str) -> None:
        if not self._ok or self._muted:
            return
        eff = self._effects.get(name)
        if eff is None:
            return
        try:
            eff.play()
        except Exception:
            pass

    def play_hit(self, combo: int) -> None:
        idx = min(max(int(combo), 1), len(_PENTATONIC))
        self._play(f"hit{idx}")

    def play_miss(self) -> None:
        self._play("miss")

    def play_milestone(self) -> None:
        self._play("milestone")

    def play_start(self) -> None:
        self._play("start")

    def play_finish(self) -> None:
        self._play("finish")
