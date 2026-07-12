from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import ClassVar

from piper import PiperVoice


class PiperModelManager:
    """German-only Piper model manager.

    Manager objects are intentionally cheap and may be owned by several UI
    pages. The heavyweight Piper voice is shared by resolved model/config path,
    however, so those pages do not each load their own copy into memory.
    """

    _voice_load_lock: ClassVar[RLock] = RLock()
    _synthesis_lock: ClassVar[RLock] = RLock()
    _shared_voices: ClassVar[dict[tuple[str, str], PiperVoice]] = {}

    def __init__(self) -> None:
        self._voice: PiperVoice | None = None
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

    def get_german_voice(self) -> PiperVoice:
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
