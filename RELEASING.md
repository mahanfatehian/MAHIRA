# Releasing MAHIRA

MAHIRA is a **German‑only** learning app and ships as a desktop app for
**Windows 10/11** and **macOS**. Installers are built automatically by GitHub
Actions and published as GitHub Releases.

German content is bundled under `data/seeds/<book>/<level>/…` and is fully
folder‑driven — adding a book/level/Lektion is just files on disk (see the
project README), so no packaging change is needed when content grows.

## Upgrade-safe state by design

Bundled resources are read-only and learner state is outside replaceable app
directories. Upgrades and uninstall therefore preserve FSRS history, profiles,
settings, backups, and logs:

```
<state root>/.mahira/
   ├─ mahira.db            # SQLite database
   ├─ profiles/            # independent learner databases
   ├─ backups/             # verified migration/manual backups
   ├─ ml_models/           # scikit-learn ranker models
   ├─ settings.json
   ├─ run.log
   └─ crash.log
```

Path resolution lives in [`src/mahira/config.py`](src/mahira/config.py):

- `resource_root()` — read-only bundled resources (`data/`, `assets/`, `schema.sql`).
  Frozen → PyInstaller's `sys._MEIPASS`; from source → repo root.
- `data_root()` — writable state. Windows → `%LOCALAPPDATA%/MAHIRA`; macOS →
  `~/Library/Application Support/MAHIRA`; frozen Linux → `$XDG_DATA_HOME/MAHIRA`
  or `~/.local/share/MAHIRA`; from source → repo root. Override with the
  `MAHIRA_DATA_DIR` environment variable.

Pre-0.4 Windows state beside the executable is copied into the new state root on
first launch. Every schema change creates a verified backup first.

## What's in this repo for packaging

| File | Purpose |
|------|---------|
| `packaging/mahira.spec` | PyInstaller build (onedir; `.app` on macOS) |
| `packaging/windows/mahira.iss` | Inno Setup per-user installer script |
| `.github/workflows/release.yml` | CI: builds Win + macOS, publishes Release |
| `requirements-build.txt` | Runtime deps + PyInstaller |

## Git LFS (required)

The model files (`assets/models/**/*.onnx` — the Piper voice + the meaning-match
model) are stored in **Git LFS**. The build bundles them, so LFS objects must be
present:

```bash
git lfs install
git lfs pull
```

CI handles this automatically — both build jobs check out with `lfs: true` and
verify the model is a real file (not a pointer stub) before building.

## Build locally (optional)

From the repository root, in your virtualenv (after `git lfs pull`):

```bash
pip install -r requirements-build.txt
pyinstaller packaging/mahira.spec --noconfirm
```

- Windows output: `dist/MAHIRA/MAHIRA.exe`
- macOS output: `dist/MAHIRA.app`

To build the Windows installer locally you also need
[Inno Setup 6](https://jrsoftware.org/isdl.php):

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=0.1.0 packaging\windows\mahira.iss
# -> dist\installer\MAHIRA-Setup-0.1.0-win64.exe
```

## Publishing a release on GitHub

You do **not** need to create a release manually — the workflow does it. Steps:

1. **Test the build first (no release):** GitHub → **Actions** → *Build & Release*
   → **Run workflow**. This builds both OSes and uploads the installers as
   *workflow artifacts* (download them from the run page). No Release is created.

2. **Cut a real release:** create and push a version tag from `main`:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

   The workflow then builds Windows + macOS and **publishes** a GitHub Release
   (using `RELEASE_NOTES.md` as the description) with these assets attached:

   - `MAHIRA-Setup-<ver>-win64.exe` (Windows installer)
   - `MAHIRA-<ver>-macos-arm64.dmg` (macOS, Apple Silicon)

3. **Verify:** GitHub → **Releases** → confirm the new version shows both assets
   and the notes from `RELEASE_NOTES.md`. (The release is published directly on a
   `vX.Y.Z` tag — `draft: false` — so update `RELEASE_NOTES.md` before tagging.)

### Versioning tip
The version comes from the tag (`v0.1.0` → `0.1.0`). Update
`CFBundleShortVersionString` in `packaging/mahira.spec` if you want the macOS
bundle to report a matching version.

## Code signing / Gatekeeper (not configured)

These builds are **unsigned** (no paid Apple/Microsoft certificates required):

- **Windows:** SmartScreen may warn on first run → *More info → Run anyway*.
- **macOS:** Gatekeeper will block an unsigned app. Users right-click the app →
  **Open**, or run once:
  `xattr -dr com.apple.quarantine /Applications/MAHIRA.app`.

Add signing later by setting `codesign_identity`/`entitlements_file` in the spec
and notarizing in the macOS job.

## Known caveats

- **macOS architecture:** the macOS job runs on `macos-14` (latest stable,
  Apple Silicon → arm64) only. Intel Macs are **not** supported — an arm64 app
  will not launch on Intel ("not supported on this Mac"). This is a deliberate
  trade for fast (~6 min) builds; add a `macos-13` matrix entry back if you ever
  need an x86_64 build.
- **macOS signing:** builds are unsigned but **ad‑hoc signed** in CI
  (`codesign --sign -`) so the app launches without a "damaged" error.
  Gatekeeper still requires right‑click → **Open** on first launch (or
  `xattr -dr com.apple.quarantine /Applications/MAHIRA.app`).
- **Audio (Piper TTS):** voice models live in Git LFS and are bundled by the
  spec. The CI jobs fail fast if the model wasn't pulled (an LFS pointer stub).
  If pronunciation audio fails in a packaged build, check `piper`/`onnxruntime`
  data collection in `packaging/mahira.spec` first.
