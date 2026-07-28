from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "resolve_release_version.py"
SPEC = importlib.util.spec_from_file_location("mahira_release_version", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_version)


@pytest.mark.parametrize(
    ("ref_type", "ref_name", "manual", "expected"),
    [
        ("tag", "v1.2.3", "ignored", "1.2.3"),
        ("tag", "v1.2.3-rc.1+build.7", "ignored", "1.2.3-rc.1+build.7"),
        ("branch", "dev", "0.4.0-dev", "0.4.0-dev"),
        ("branch", "main", "", "0.1.0-dev"),
    ],
)
def test_release_version_accepts_supported_formats(
    ref_type,
    ref_name,
    manual,
    expected,
):
    assert release_version.resolve_version(ref_type, ref_name, manual) == expected


@pytest.mark.parametrize(
    ("ref_type", "ref_name", "manual"),
    [
        ("tag", "v$(whoami)", ""),
        ("tag", "v1.2.3;echo-owned", ""),
        ("tag", "v1.2", ""),
        ("tag", "1.2.3", ""),
        ("branch", "main", "1.2.3\nEVIL=value"),
    ],
)
def test_release_version_rejects_unsafe_or_invalid_values(
    ref_type,
    ref_name,
    manual,
):
    with pytest.raises(ValueError):
        release_version.resolve_version(ref_type, ref_name, manual)


def test_release_version_writes_both_environment_values(tmp_path, monkeypatch):
    env_file = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v2.0.0")
    monkeypatch.setenv("INPUT_VERSION", "ignored")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    release_version.main()

    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "VERSION=2.0.0",
        "MAHIRA_VERSION=2.0.0",
    ]
