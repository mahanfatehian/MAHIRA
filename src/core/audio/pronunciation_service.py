from __future__ import annotations

import hashlib
import re
import wave
from pathlib import Path

from .model_manager import PiperModelManager


class PronunciationService:
    """
    German pronunciation generator with temporary WAV cache.

    Cache behavior:
    - files are stored in .mahira/audio_cache
    - same normalized text maps to same filename
    - if file exists, it is reused
    - caller can explicitly delete files when no longer needed
    - caller can clear all cache on startup to avoid stale files after crashes
    """

    def __init__(self, model_manager: PiperModelManager | None = None) -> None:
        self.model_manager = model_manager or PiperModelManager()
        self._project_root = self.model_manager.project_root
        self._cache_dir = self._project_root / ".mahira" / "audio_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def _normalize_text(self, text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _cache_key(self, text: str) -> str:
        normalized = self._normalize_text(text)
        raw = f"de::{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_cached_path(self, text: str) -> Path:
        return self.cache_dir / f"{self._cache_key(text)}.wav"

    def has_cached_audio(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        return self.get_cached_path(normalized).exists()

    def generate_wav(self, text: str, force: bool = False) -> Path:
        normalized = self._normalize_text(text)
        if not normalized:
            raise ValueError("Cannot generate pronunciation for empty text.")

        out_path = self.get_cached_path(normalized)

        if out_path.exists() and not force:
            return out_path

        voice = self.model_manager.get_german_voice()

        with wave.open(str(out_path), "wb") as wav_file:
            voice.synthesize_wav(normalized, wav_file)

        return out_path

    def delete_cached_audio(self, text: str) -> bool:
        """
        Delete cached WAV for the given text.
        Returns True if a file was deleted, False otherwise.
        """
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        path = self.get_cached_path(normalized)
        if path.exists():
            try:
                path.unlink()
                return True
            except Exception:
                return False
        return False

    def delete_cached_file(self, file_path: str | Path) -> bool:
        """
        Delete a specific cached WAV file path.
        Returns True if deleted, False otherwise.
        """
        path = Path(file_path)
        if path.exists():
            try:
                path.unlink()
                return True
            except Exception:
                return False
        return False

    def clear_all_cached_audio(self) -> int:
        """
        Delete all .wav files in .mahira/audio_cache.
        Returns the number of deleted files.
        """
        deleted = 0

        if not self.cache_dir.exists():
            return deleted

        for wav_file in self.cache_dir.glob("*.wav"):
            try:
                wav_file.unlink()
                deleted += 1
            except Exception:
                pass

        return deleted
