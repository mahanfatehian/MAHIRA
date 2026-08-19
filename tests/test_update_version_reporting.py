"""A build must not claim a version it isn't.

_bundled_version fell back to a hardcoded "0.3.0" when assets/version.json was
absent. That number went stale the moment 0.4.0 shipped, so a source checkout
compared itself against the latest release as though it were 0.3.0 - and after
0.3.0 was superseded it would happily report "you are up to date" against an
older release than it was running.
"""

from __future__ import annotations

import json

import pytest

from core.updates import UpdateService, _version_tuple


def test_an_unknown_build_reports_a_dev_version():
    assert UpdateService.UNKNOWN_VERSION == "0.0.0-dev"


def test_an_explicit_version_always_wins():
    assert UpdateService("1.2.3").current_version == "1.2.3"


def test_the_environment_override_still_works(monkeypatch):
    monkeypatch.setenv("MAHIRA_VERSION", "9.9.9")
    assert UpdateService().current_version == "9.9.9"


def test_a_missing_version_file_falls_back_to_the_dev_version(monkeypatch, tmp_path):
    monkeypatch.delenv("MAHIRA_VERSION", raising=False)
    monkeypatch.setattr("mahira.config.resource_root", lambda: tmp_path)
    assert UpdateService().current_version == UpdateService.UNKNOWN_VERSION


def test_a_bundled_version_file_is_used(monkeypatch, tmp_path):
    monkeypatch.delenv("MAHIRA_VERSION", raising=False)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "version.json").write_text(json.dumps({"version": "0.5.0"}), encoding="utf-8")
    monkeypatch.setattr("mahira.config.resource_root", lambda: tmp_path)
    assert UpdateService().current_version == "0.5.0"


def test_a_corrupt_version_file_falls_back(monkeypatch, tmp_path):
    monkeypatch.delenv("MAHIRA_VERSION", raising=False)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "version.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("mahira.config.resource_root", lambda: tmp_path)
    assert UpdateService().current_version == UpdateService.UNKNOWN_VERSION


@pytest.mark.parametrize("released", ["0.3.0", "0.4.0", "0.5.0", "1.0.0"])
def test_every_real_release_looks_newer_than_a_dev_build(released):
    unknown = _version_tuple(UpdateService.UNKNOWN_VERSION)
    assert _version_tuple(released) > unknown


def test_a_dev_build_of_the_same_number_is_not_newer():
    assert not _version_tuple("0.5.0-dev") > _version_tuple("0.5.0")
