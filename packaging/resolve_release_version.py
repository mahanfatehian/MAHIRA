from __future__ import annotations

import os
from pathlib import Path
import re


DEFAULT_VERSION = "0.1.0-dev"
VERSION_PATTERN = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


def resolve_version(ref_type: str, ref_name: str, input_version: str) -> str:
    """Resolve a tag or manual-build version without evaluating shell text."""
    if (ref_type or "").strip().lower() == "tag":
        ref = (ref_name or "").strip()
        if not ref.startswith("v"):
            raise ValueError("Release tags must start with 'v'.")
        version = ref[1:]
    else:
        version = (input_version or "").strip() or DEFAULT_VERSION

    if VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("Version must use a safe X.Y.Z SemVer-style format.")
    return version


def main() -> None:
    version = resolve_version(
        os.environ.get("GITHUB_REF_TYPE", ""),
        os.environ.get("GITHUB_REF_NAME", ""),
        os.environ.get("INPUT_VERSION", ""),
    )
    env_file = os.environ.get("GITHUB_ENV")
    if not env_file:
        raise RuntimeError("GITHUB_ENV is unavailable.")

    with Path(env_file).open("a", encoding="utf-8") as stream:
        stream.write(f"VERSION={version}\nMAHIRA_VERSION={version}\n")


if __name__ == "__main__":
    main()
