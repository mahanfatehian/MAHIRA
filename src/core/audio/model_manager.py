from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from piper import PiperVoice


class PiperUnavailableError(RuntimeError):
    """Raised when the offline speech stack cannot be loaded or is missing."""


def _load_piper_voice_class() -> type:
    """Import piper only when a voice is first needed.

    A top-level `from piper import PiperVoice` made every review page that
    imports core.audio fail at construction time if piper/onnxruntime is
    missing, even though the README calls TTS optional. Deferring the import
    keeps study usable without audio.
    """
    try:
        from piper import PiperVoice
    except Exception as exc:  # noqa: BLE001 - surface as a clean domain error
        raise PiperUnavailableError(
            "Offline pronunciation is unavailable "
            f"({type(exc).__name__}: {exc}). "
            "Study continues without audio."
        ) from exc
    return PiperVoice


class PiperModelManager:
    """German-only Piper model manager.

    Manager objects are intentionally cheap and may be owned by several UI
    pages. The heavyweight Piper voice is shared by resolved model/config path,
    however, so those pages do not each load their own copy into memory.
    """

    _voice_load_lock: ClassVar[RLock] = RLock()
    _synthesis_lock: ClassVar[RLock] = RLock()
    _shared_voices: ClassVar[dict[tuple[str, str], Any]] = {}

    def __init__(self) -> None:
        self._voice: Any | None = None
        self._voice_key: tuple[str, str] | None = None
        self._project_root = self._detect_project_root()

    def _detect_project_root(self) -> Path:
        # Voice models are read-only bundled resources under assets/models/piper.
        # Resolve via the shared resource root so it works both from source and
        # from a packaged (frozen) build.
        try:
            from mahira.config import resource_root
            return resource_root()
        except Exception:
            here = Path(__file__).resolve()
            # project_root/src/core/audio/model_manager.py -> parents[3] = root
            if len(here.parents) >= 4:
                return here.parents[3]
            return Path.cwd()

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def german_model_path(self) -> Path:
        path = (
            self.project_root
            / "assets"
            / "models"
            / "piper"
            / "de_DE-thorsten-high.onnx"
        )
        if not path.exists():
            raise FileNotFoundError(f"German Piper model not found:\n{path}")
        return path

    @property
    def german_config_path(self) -> Path:
        path = self.german_model_path.with_suffix(".onnx.json")
        if not path.exists():
            raise FileNotFoundError(f"German Piper config not found:\n{path}")
        return path

    @property
    def synthesis_lock(self) -> RLock:
        """Process-wide guard for calls into the shared Piper voice.

        Piper/ONNX inference is not assumed to be safe when the same voice is
        called concurrently from independent audio workers. PronunciationService
        holds this lock only while rendering.
        """
        return self._synthesis_lock

    def is_available(self) -> bool:
        """True when the piper package and the bundled German model are present."""
        try:
            _load_piper_voice_class()
            _ = self.german_model_path
            _ = self.german_config_path
            return True
        except Exception:
            return False

    def voice_is_loaded(self) -> bool:
        """True when a first synthesis would not have to load the model."""
        if self._voice is not None:
            return True
        try:
            key = (
                str(self.german_model_path.resolve()),
                str(self.german_config_path.resolve()),
            )
        except Exception:
            return False
        return key in self._shared_voices

    def prewarm(self) -> None:
        """Load the voice now, swallowing any failure.

        Loading the ~114 MB model takes about 3.2 seconds. Paying that on the
        first click means the learner presses the speaker, hears nothing for
        several seconds, decides it is broken and clicks again - by which time
        the model is loaded and it plays. Warming it while they are reading the
        page turns the first click into an ordinary ~290 ms render, or an
        instant cache hit.

        Synchronous and safe to call from any thread: get_german_voice already
        double-checks under a process-wide lock, so concurrent callers load the
        voice exactly once. Callers that must not block should run this on a
        background thread. Failure is the same "audio unavailable" case every
        caller already handles, so nothing is raised.
        """
        if self.voice_is_loaded():
            return
        try:
            self.get_german_voice()
        except Exception:
            pass

    def get_german_voice(self) -> PiperVoice:
        PiperVoice = _load_piper_voice_class()
        model_path = self.german_model_path.resolve()
        config_path = self.german_config_path.resolve()
        key = (str(model_path), str(config_path))

        # Preserve the fast instance-local path while all instances ultimately
        # point at the same class-level voice.
        if self._voice is not None and self._voice_key == key:
            return self._voice

        # Double-checked loading under a process-wide lock keeps simultaneous
        # first clicks on different pages from loading multiple ~114 MB voices.
        with self._voice_load_lock:
            voice = self._shared_voices.get(key)
            if voice is None:
                voice = PiperVoice.load(
                    str(model_path),
                    config_path=str(config_path),
                )
                self._shared_voices[key] = voice

        self._voice = voice
        self._voice_key = key
        return voice
