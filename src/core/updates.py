from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass


RELEASE_API = "https://api.github.com/repos/mahanfatehian/MAHIRA/releases/latest"


@dataclass(frozen=True)
class UpdateResult:
    current: str
    latest: str
    available: bool
    page_url: str


def _version_tuple(value: str) -> tuple[int, int, int, int]:
    text = (value or "").strip()
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if match is None:
        return (0, 0, 0, 0)

    core = tuple(int(part or 0) for part in match.groups())
    suffix = text[match.end():].strip()
    qualifier = suffix.lstrip("._").casefold()
    is_prerelease = suffix.startswith("-") or qualifier.startswith(
        ("a", "alpha", "b", "beta", "rc", "dev", "pre", "preview")
    )
    return (*core, 0 if is_prerelease else 1)


class UpdateService:
    def __init__(self, current_version: str | None = None):
        self.current_version = current_version or os.environ.get("MAHIRA_VERSION") or self._bundled_version()

    @staticmethod
    def _bundled_version() -> str:
        try:
            from mahira.config import resource_root
            payload = json.loads((resource_root() / "assets" / "version.json").read_text(encoding="utf-8"))
            return str(payload.get("version") or "0.3.0")
        except (OSError, ValueError, TypeError):
            return "0.3.0"

    def check(self, timeout: float = 5.0) -> UpdateResult:
        request = urllib.request.Request(
            RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "MAHIRA-update-check"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        latest = str(payload.get("tag_name") or "").lstrip("vV")
        if not latest:
            raise RuntimeError("The release service returned no version")
        return UpdateResult(
            current=self.current_version,
            latest=latest,
            available=_version_tuple(latest) > _version_tuple(self.current_version),
            page_url=str(payload.get("html_url") or "https://github.com/mahanfatehian/MAHIRA/releases"),
        )
