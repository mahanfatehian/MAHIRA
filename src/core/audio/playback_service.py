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
        self._pending_play = False

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
        self._pending_play = True

        self.effect.setSource(QUrl.fromLocalFile(str(path)))

        # Some Windows/Qt builds need a tiny delay before QSoundEffect reports Ready.
        QTimer.singleShot(40, self._play_if_ready)

    def _play_if_ready(self) -> None:
        if not self._current_path or not self._pending_play:
            return

        status = self.effect.status()
        ready_status = getattr(QSoundEffect.Status, "Ready", None)
        loading_status = getattr(QSoundEffect.Status, "Loading", None)

        if ready_status is not None and status == ready_status:
            self._pending_play = False
            self.effect.play()
            return

        if loading_status is not None and status == loading_status:
            QTimer.singleShot(40, self._play_if_ready)
            return

        # Fallback for Qt builds where status timing is inconsistent.
        self._pending_play = False
        self.effect.play()

    def stop(self) -> None:
        self._pending_play = False
        if self.effect.isPlaying():
            self.effect.stop()

    def _on_playing_changed(self) -> None:
        is_playing = self.effect.isPlaying()

        if is_playing and self._current_path:
            self.started.emit(self._current_path)

        if self._was_playing and not is_playing:
            self.finished.emit()

        self._was_playing = is_playing

    def _on_status_changed(self) -> None:
        status = self.effect.status()
        error_status = getattr(QSoundEffect.Status, "Error", None)

        if error_status is not None and status == error_status:
            self._pending_play = False
            self.failed.emit("QSoundEffect failed to play audio.")
