from __future__ import annotations

from contextlib import nullcontext
import hashlib
import os
import re
import uuid
import wave
from pathlib import Path

from .model_manager import PiperModelManager


class PronunciationService:
    """
    German pronunciation generator with a bounded, reusable WAV cache.

    Cache behavior:
    - files are stored in .mahira/audio_cache
    - same normalized text maps to same filename
    - if file exists, it is reused
    - least-recently-used files are pruned beyond 256 clips / 128 MiB
    - callers can still explicitly delete clips or clear the cache
    """

    MAX_CACHE_FILES = 256
    MAX_CACHE_BYTES = 128 * 1024 * 1024

    def __init__(self, model_manager: PiperModelManager | None = None) -> None:
        self.model_manager = model_manager or PiperModelManager()
        self._project_root = self.model_manager.project_root
        # The cache holds WRITABLE WAVs, so it must live under the writable data
        # root (<data_root>/.mahira), NOT the read-only resource root. On a frozen
        # macOS .app the two diverge — resource_root() is inside the read-only /
        # App-Translocated bundle — so caching there would fail every synthesis.
        self._cache_dir = self._writable_cache_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _writable_cache_dir() -> Path:
        try:
            from mahira.config import data_root, STATE_DIRNAME
            return data_root() / STATE_DIRNAME / "audio_cache"
        except Exception:
            # From-source fallback: the repo root (where data_root resolves too).
            return Path(__file__).resolve().parents[3] / ".mahira" / "audio_cache"

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def _normalize_text(self, text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _cache_key(self, text: str, length_scale: float | None = None) -> str:
        normalized = self._normalize_text(text)
        raw = f"de::{normalized}"
        # A non-default speed gets its own cache slot so 0.75x / 1.25x renders
        # never collide with the normal-speed file. length_scale=None keeps the
        # original key, so existing caches and normal playback are unaffected.
        if length_scale is not None:
            raw = f"{raw}::ls{length_scale:.3f}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_cached_path(self, text: str, length_scale: float | None = None) -> Path:
        return self.cache_dir / f"{self._cache_key(text, length_scale)}.wav"

    def has_cached_audio(self, text: str, length_scale: float | None = None) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        return self.get_cached_path(normalized, length_scale).exists()

    def generate_wav(
        self,
        text: str,
        force: bool = False,
        length_scale: float | None = None,
    ) -> Path:
        """Render `text` to a cached WAV.

        length_scale controls speaking speed: 1.0 is normal, >1.0 is slower,
        <1.0 is faster (it is Piper's duration multiplier, i.e. 1.0 / speed).
        None means "use the model default" and keeps the original cache key.
        """
        normalized = self._normalize_text(text)
        if not normalized:
            raise ValueError("Cannot generate pronunciation for empty text.")

        out_path = self.get_cached_path(normalized, length_scale)

        if out_path.exists() and not force:
            self._mark_cache_used(out_path)
            return out_path

        syn_config = None
        if length_scale is not None:
            try:
                from piper import SynthesisConfig
                syn_config = SynthesisConfig(length_scale=float(length_scale))
            except Exception:
                syn_config = None  # older piper: fall back to default speed

        # Render to a temp file and move it into place only on success. Writing
        # straight to out_path would leave a 0-byte WAV there if synthesize_wav
        # raises — and the cache-hit check above would then serve that empty file
        # forever, silencing the word until the whole cache is cleared.
        # Real managers expose one process-wide lock; the fallback keeps the
        # service compatible with duck-typed managers used by callers and tests.
        # Accept either a lock property or a context-manager factory.
        synthesis_lock = getattr(self.model_manager, "synthesis_lock", None)
        if callable(synthesis_lock):
            synthesis_lock = synthesis_lock()
        synthesis_guard = synthesis_lock or nullcontext()

        with synthesis_guard:
            # Another page may have rendered this same cache key while this
            # worker waited. Avoid duplicate work unless force asks for it.
            if out_path.exists() and not force:
                self._mark_cache_used(out_path)
                return out_path

            voice = self.model_manager.get_german_voice()
            # The synthesis lock is process-local. A unique temp path prevents
            # two MAHIRA instances rendering the same key from clobbering or
            # deleting one another's in-progress WAV before atomic replace.
            tmp_path = out_path.with_name(
                f"{out_path.name}.{uuid.uuid4().hex}.part"
            )
            try:
                with wave.open(str(tmp_path), "wb") as wav_file:
                    if syn_config is not None:
                        voice.synthesize_wav(normalized, wav_file, syn_config=syn_config)
                    else:
                        voice.synthesize_wav(normalized, wav_file)
                try:
                    tmp_path.replace(out_path)
                except PermissionError:
                    # On Windows, two processes publishing the same key can
                    # race after both finish rendering. Keep the first complete
                    # result instead of failing the second caller.
                    if force or not out_path.is_file():
                        raise
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                self._mark_cache_used(out_path)
                self._prune_cache(protect=out_path)
            except Exception:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
                raise

        return out_path

    @staticmethod
    def _mark_cache_used(path: Path) -> None:
        """Refresh mtime so pruning behaves like a small on-disk LRU."""
        try:
            os.utime(path, None)
        except OSError:
            pass

    def _prune_cache(self, *, protect: Path | None = None) -> int:
        """Bound pronunciation storage without penalizing repeat playback."""
        entries: list[tuple[float, int, Path]] = []
        for path in self.cache_dir.glob("*.wav"):
            try:
                stat = path.stat()
                entries.append((stat.st_mtime, stat.st_size, path))
            except OSError:
                continue
        entries.sort(key=lambda item: item[0], reverse=True)

        kept_files = 0
        kept_bytes = 0
        deleted = 0
        protected = protect.resolve() if protect is not None else None
        for _mtime, size, path in entries:
            try:
                is_protected = protected is not None and path.resolve() == protected
            except OSError:
                is_protected = False
            fits = (
                kept_files < self.MAX_CACHE_FILES
                and kept_bytes + size <= self.MAX_CACHE_BYTES
            )
            if is_protected or fits:
                kept_files += 1
                kept_bytes += size
                continue
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
        return deleted

    def delete_cached_audio(self, text: str, length_scale: float | None = None) -> bool:
        """
        Delete cached WAV for the given text (at the given speed, if any).
        Returns True if a file was deleted, False otherwise.

        `length_scale` must match the value used when the clip was generated; a
        slow/fast render lives under a different cache key than the normal-speed
        one, so omitting it would silently miss those files.
        """
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        path = self.get_cached_path(normalized, length_scale)
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
