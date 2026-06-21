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

        self._ready_status = getattr(QSoundEffect.Status, "Ready", None)
        self._error_status = getattr(QSoundEffect.Status, "Error", None)

        self._current_path: str | None = None
        self._was_playing = False
        self._pending_play = False
        self._poll_left = 0

    def set_volume(self, volume: float) -> None:
        volume = max(0.0, min(1.0, float(volume)))
        self.effect.setVolume(volume)

    def _is_ready(self) -> bool:
        return self._ready_status is not None and self.effect.status() == self._ready_status

    def play_file(self, file_path: str | Path) -> None:
        path = Path(file_path).resolve()

        if not path.exists():
            self.failed.emit(f"Audio file does not exist:\n{path}")
            return

        self.stop()
        url = QUrl.fromLocalFile(str(path))
        self._current_path = str(path)
        self._pending_play = True

        # Same clip already loaded: play immediately. Re-setting the same source
        # does not reload, so no statusChanged would arrive to drive it.
        if self.effect.source() == url and self._is_ready():
            self._pending_play = False
            self.effect.play()
            return

        # New clip: load it, then play ONLY once this source reports Ready.
        #
        # Driving playback off statusChanged -> Ready (see _on_status_changed),
        # with the timer as a safety net, is what fixes the long-standing bug
        # where switching word -> example played the *word* on the first click:
        # right after setSource() the effect could still report the PREVIOUS
        # clip as Ready, and the old code would play() that stale buffer.
        self.effect.setSource(url)
        self._poll_left = 60  # up to ~3s of 50ms polls, then give up gracefully
        QTimer.singleShot(50, self._poll_ready)

    def _poll_ready(self) -> None:
        # Safety net for builds where statusChanged is unreliable. It only ever
        # plays once the NEW source is genuinely Ready, never a stale one.
        if not self._pending_play:
            return  # already played via statusChanged
        if self._is_ready():
            self._pending_play = False
            self.effect.play()
            return
        self._poll_left -= 1
        if self._poll_left > 0:
            QTimer.singleShot(50, self._poll_ready)
        else:
            self._pending_play = False
            self.failed.emit("Audio took too long to load.")

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

        if self._error_status is not None and status == self._error_status:
            self._pending_play = False
            self.failed.emit("QSoundEffect failed to play audio.")
            return

        # The Ready that follows a setSource() belongs to the NEW clip, so this
        # is the correct, race-free moment to start playback.
        if self._ready_status is not None and status == self._ready_status and self._pending_play:
            self._pending_play = False
            self.effect.play()
