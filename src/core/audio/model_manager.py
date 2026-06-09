from __future__ import annotations

from pathlib import Path

from piper import PiperVoice


class PiperModelManager:
    """German-only Piper model manager."""

    def __init__(self) -> None:
        self._voice: PiperVoice | None = None
        self._project_root = self._detect_project_root()

    def _detect_project_root(self) -> Path:
        here = Path(__file__).resolve()
        # project_root/src/core/audio/model_manager.py
        # parents[0] = audio
        # parents[1] = core
        # parents[2] = src
        # parents[3] = project root
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
            / "audio"
            / "models"
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

    def get_german_voice(self) -> PiperVoice:
        if self._voice is None:
            self._voice = PiperVoice.load(
                str(self.german_model_path),
                config_path=str(self.german_config_path),
            )
        return self._voice
