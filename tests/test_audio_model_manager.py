"""Shared Piper voice loading and cross-page synthesis serialization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time


def _make_voice_files(root):
    model = root / "assets" / "models" / "piper" / "de_DE-thorsten-high.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fake model")
    model.with_suffix(".onnx.json").write_text("{}", encoding="utf-8")


def _configure_fake_voice(monkeypatch, tmp_path, voice):
    from core.audio import model_manager as manager_module

    manager_cls = manager_module.PiperModelManager
    _make_voice_files(tmp_path)
    monkeypatch.setattr(manager_cls, "_detect_project_root", lambda self: tmp_path)
    monkeypatch.setattr(manager_cls, "_shared_voices", {})

    load_calls = []

    def fake_load(path, *, config_path):
        load_calls.append((path, config_path))
        # Release the GIL long enough for concurrent callers to contend on the
        # manager's load lock. Without the lock, this loads more than once.
        time.sleep(0.03)
        return voice

    monkeypatch.setattr(manager_module.PiperVoice, "load", fake_load)
    return manager_cls, load_calls


def test_concurrent_managers_share_one_loaded_voice(monkeypatch, tmp_path):
    voice = object()
    manager_cls, load_calls = _configure_fake_voice(monkeypatch, tmp_path, voice)
    managers = [manager_cls() for _ in range(8)]

    with ThreadPoolExecutor(max_workers=len(managers)) as pool:
        loaded = list(pool.map(lambda manager: manager.get_german_voice(), managers))

    assert loaded == [voice] * len(managers)
    assert len(load_calls) == 1


def test_pronunciation_services_serialize_shared_voice_calls(monkeypatch, tmp_path):
    from core.audio.pronunciation_service import PronunciationService

    state_lock = threading.Lock()
    active = 0
    max_active = 0

    class FakeVoice:
        def synthesize_wav(self, text, wav_file, **kwargs):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.04)
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16_000)
                wav_file.writeframes(b"\x00\x00")
            finally:
                with state_lock:
                    active -= 1

    manager_cls, load_calls = _configure_fake_voice(
        monkeypatch, tmp_path, FakeVoice()
    )
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        PronunciationService,
        "_writable_cache_dir",
        staticmethod(lambda: cache_dir),
    )
    services = [PronunciationService(manager_cls()), PronunciationService(manager_cls())]

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(
            pool.map(
                lambda pair: pair[0].generate_wav(pair[1]),
                zip(services, ("Guten Morgen", "Guten Abend")),
            )
        )

    assert max_active == 1
    assert len(load_calls) == 1
    assert all(path.exists() for path in paths)


def test_waiting_service_reuses_same_text_cache(monkeypatch, tmp_path):
    from core.audio.pronunciation_service import PronunciationService

    syntheses = 0

    class FakeVoice:
        def synthesize_wav(self, text, wav_file, **kwargs):
            nonlocal syntheses
            syntheses += 1
            time.sleep(0.03)
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(b"\x00\x00")

    manager_cls, _ = _configure_fake_voice(monkeypatch, tmp_path, FakeVoice())
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        PronunciationService,
        "_writable_cache_dir",
        staticmethod(lambda: cache_dir),
    )
    services = [PronunciationService(manager_cls()), PronunciationService(manager_cls())]

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda service: service.generate_wav("Hallo"), services))

    assert paths[0] == paths[1]
    assert syntheses == 1
    assert paths[0].exists()


def test_independent_services_use_unique_temp_files(monkeypatch, tmp_path):
    import wave
    from core.audio.pronunciation_service import PronunciationService

    barrier = threading.Barrier(2)
    rendered_paths = []
    rendered_paths_lock = threading.Lock()

    class Voice:
        def synthesize_wav(self, _text, wav_file, **_kwargs):
            with rendered_paths_lock:
                rendered_paths.append(wav_file._file.name)
            barrier.wait(timeout=3)
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(b"\x00\x00")

    class Manager:
        project_root = tmp_path

        def __init__(self):
            self.synthesis_lock = threading.Lock()

        def get_german_voice(self):
            return Voice()

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        PronunciationService,
        "_writable_cache_dir",
        staticmethod(lambda: cache_dir),
    )
    services = [PronunciationService(Manager()), PronunciationService(Manager())]

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda service: service.generate_wav("Hallo"), services))

    assert paths[0] == paths[1]
    assert len(set(rendered_paths)) == 2
    assert all(str(path).endswith(".part") for path in rendered_paths)
    with wave.open(str(paths[0]), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.readframes(1) == b"\x00\x00"
    assert list(cache_dir.glob("*.part")) == []


def test_generate_wav_reuses_concurrent_process_winner(monkeypatch, tmp_path):
    from pathlib import Path
    import wave
    from core.audio.pronunciation_service import PronunciationService

    class Voice:
        def synthesize_wav(self, _text, wav_file, **_kwargs):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(b"\x00\x00")

    class Manager:
        project_root = tmp_path
        synthesis_lock = threading.Lock()

        def get_german_voice(self):
            return Voice()

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        PronunciationService,
        "_writable_cache_dir",
        staticmethod(lambda: cache_dir),
    )

    def concurrent_winner(source, target):
        target.write_bytes(source.read_bytes())
        raise PermissionError("simulated Windows publish race")

    monkeypatch.setattr(Path, "replace", concurrent_winner)
    path = PronunciationService(Manager()).generate_wav("Hallo")

    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.readframes(1) == b"\x00\x00"
    assert list(cache_dir.glob("*.part")) == []


def test_pronunciation_cache_is_bounded_by_recent_use(monkeypatch, tmp_path):
    import os
    from core.audio.pronunciation_service import PronunciationService

    class Manager:
        project_root = tmp_path

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        PronunciationService,
        "_writable_cache_dir",
        staticmethod(lambda: cache_dir),
    )
    service = PronunciationService(Manager())
    service.MAX_CACHE_FILES = 2
    service.MAX_CACHE_BYTES = 10_000

    paths = []
    for i in range(4):
        path = cache_dir / f"{i}.wav"
        path.write_bytes(b"RIFF" + bytes([i]))
        os.utime(path, (i + 1, i + 1))
        paths.append(path)

    assert service._prune_cache(protect=paths[-1]) == 2
    assert [path.exists() for path in paths] == [False, False, True, True]
