from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QSoundEffect


class PlaybackService(QObject):
    started = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.effect = QSoundEffect(self)
        self.effect.setLoopCount(1)
        self.effect.setVolume(1.0)

        self.effect.playingChanged.connect(self._on_playing_changed)
        self.effect.statusChanged.connect(self._on_status_changed)

        self._current_path: str | None = None
        self._was_playing = False

    def set_volume(self, volume: float) -> None:
        volume = max(0.0, min(1.0, float(volume)))
        self.effect.setVolume(volume)

    def play_file(self, file_path: str | Path) -> None:
        path = Path(file_path).resolve()

        if not path.exists():
            self.failed.emit(f"Audio file does not exist:\n{path}")
            return

        self.stop()

        self._current_path = str(path)

        url = QUrl.fromLocalFile(str(path))
        self.effect.setSource(url)

        # Small delayed play helps ensure source is loaded on some systems
        QTimer.singleShot(50, self._play_loaded)

    def _play_loaded(self) -> None:
        if not self._current_path:
            return

        self.effect.play()
        self.started.emit(self._current_path)

    def stop(self) -> None:
        if self.effect.isPlaying():
            self.effect.stop()

    def _on_playing_changed(self) -> None:
        is_playing = self.effect.isPlaying()

        if self._was_playing and not is_playing:
            self.finished.emit()

        self._was_playing = is_playing

    def _on_status_changed(self) -> None:
        status = self.effect.status()

        if status == QSoundEffect.Error:
            self.failed.emit("QSoundEffect failed to play audio.")
