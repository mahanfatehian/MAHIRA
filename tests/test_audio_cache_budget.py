"""The audio cache must keep what the learner already waited for.

Clips average ~30 KB on a real install, so a 256-file cap bound the cache at
about 8 MB - 6% of the 128 MiB byte budget the class documents. Words the
learner had already paid a synthesis for were evicted and had to be rendered
again, which is exactly the stall the speaker is meant to avoid.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.audio.pronunciation_service import PronunciationService


class _Service(PronunciationService):
    def __init__(self, cache_dir: Path):
        self._cache_dir = cache_dir
        self._project_root = Path(".")


@pytest.fixture()
def service(tmp_path):
    cache = tmp_path / "audio_cache"
    cache.mkdir()
    return _Service(cache)


def _clip(service, name: str, size: int = 30 * 1024, age: float = 0.0):
    path = service.cache_dir / f"{name}.wav"
    path.write_bytes(b"\0" * size)
    if age:
        stamp = time.time() - age
        import os

        os.utime(path, (stamp, stamp))
    return path


def test_the_byte_budget_is_the_binding_limit():
    """At the measured mean clip size the file cap must not bind first."""
    mean_clip_bytes = 30 * 1024
    file_cap_bytes = PronunciationService.MAX_CACHE_FILES * mean_clip_bytes
    assert file_cap_bytes > PronunciationService.MAX_CACHE_BYTES / 4, (
        "the file cap still evicts long before the byte budget is reached"
    )


def test_a_realistic_lesson_of_audio_is_not_evicted(service):
    """Two full books of vocabulary is well inside the intended budget."""
    for i in range(600):
        _clip(service, f"w{i:04d}")
    service._prune_cache()
    assert len(list(service.cache_dir.glob("*.wav"))) == 600


def test_the_file_cap_is_still_enforced(service):
    for i in range(PronunciationService.MAX_CACHE_FILES + 40):
        _clip(service, f"w{i:05d}", size=64, age=i)
    service._prune_cache()
    remaining = list(service.cache_dir.glob("*.wav"))
    assert len(remaining) <= PronunciationService.MAX_CACHE_FILES


def test_the_byte_budget_is_still_enforced(service):
    big = PronunciationService.MAX_CACHE_BYTES // 8
    for i in range(12):
        _clip(service, f"big{i}", size=big, age=i)
    service._prune_cache()
    total = sum(p.stat().st_size for p in service.cache_dir.glob("*.wav"))
    assert total <= PronunciationService.MAX_CACHE_BYTES


def test_the_freshly_rendered_clip_is_never_evicted(service):
    """It is what the caller is about to play."""
    big = PronunciationService.MAX_CACHE_BYTES // 4
    for i in range(8):
        _clip(service, f"old{i}", size=big, age=1000 + i)
    protege = _clip(service, "just-rendered", size=big, age=9999)
    service._prune_cache(protect=protege)
    assert protege.exists()


def test_the_oldest_clips_go_first(service):
    for i in range(10):
        _clip(service, f"clip{i}", size=32 * 1024 * 1024, age=i * 100)
    service._prune_cache()
    survivors = {p.name for p in service.cache_dir.glob("*.wav")}
    assert "clip0.wav" in survivors, "most recently used must survive"
    assert "clip9.wav" not in survivors, "least recently used must go"


def test_pruning_a_missing_directory_is_safe(tmp_path):
    service = _Service(tmp_path / "gone")
    assert service._prune_cache() == 0
