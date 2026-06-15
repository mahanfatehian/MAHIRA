# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MAHIRA (German learning app).

Build (run from the repository root):
    pyinstaller packaging/mahira.spec --noconfirm

Produces a self-contained "onedir" build in dist/MAHIRA:
    - Windows: dist/MAHIRA/MAHIRA.exe  (+ bundled libs)
    - macOS:   dist/MAHIRA.app

Everything the app generates at runtime (SQLite DB, ML models, logs) is written
to a `.mahira` folder NEXT TO THE EXECUTABLE — see src/mahira/config.py:data_root.
Nothing is written to %APPDATA% / ~/Library / any per-user OS location.
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# SPECPATH is the directory containing this spec file (packaging/).
ROOT = Path(SPECPATH).resolve().parent

APP_NAME = "MAHIRA"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# Version comes from the CI tag (MAHIRA_VERSION); falls back for local builds.
# A leading "v" and any pre-release suffix are stripped for the macOS plist,
# which requires a numeric dotted version (e.g. "1.2.3").
_raw_version = os.environ.get("MAHIRA_VERSION", "0.1.0").lstrip("vV")
APP_VERSION = _raw_version.split("-")[0] or "0.1.0"

# ---------------------------------------------------------------------------
# Bundled (read-only) resources — resolved at runtime via config.resource_root()
# ---------------------------------------------------------------------------
datas = [
    (str(ROOT / "data"), "data"),                       # seeds/ + pages/
    (str(ROOT / "assets"), "assets"),                   # logo + piper voices + MiniLM model
    (str(ROOT / "src" / "db" / "schema.sql"), "src/db"),  # DB schema
]

# Heavy / dynamically-imported packages need explicit collection.
hiddenimports = []
for pkg in ("sklearn", "scipy", "piper", "onnxruntime", "tokenizers"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

for pkg in ("sklearn", "piper", "onnxruntime", "tokenizers"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Icon (optional). Windows uses .ico, macOS uses .icns.
# ---------------------------------------------------------------------------
ICON = None
if IS_WIN and (ROOT / "assets" / "logo.ico").exists():
    ICON = str(ROOT / "assets" / "logo.ico")
elif IS_MAC and (ROOT / "assets" / "logo.icns").exists():
    ICON = str(ROOT / "assets" / "logo.icns")

block_cipher = None

a = Analysis(
    [str(ROOT / "src" / "mahira" / "__main__.py")],
    pathex=[str(ROOT), str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # GUI app: no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier="com.mahira.app",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
