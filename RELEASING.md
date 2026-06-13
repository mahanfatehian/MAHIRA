# Releasing MAHIRA

MAHIRA is a **German‑only** learning app and ships as a desktop app for
**Windows 10/11** and **macOS**. Installers are built automatically by GitHub
Actions and published as GitHub Releases.

German content is bundled under `data/seeds/<book>/<level>/…` and is fully
folder‑driven — adding a book/level/Lektion is just files on disk (see the
project README), so no packaging change is needed when content grows.

## Self-contained by design

MAHIRA never writes to `%APPDATA%`, `~/Library/Application Support`, or any other
per-user/OS location. **All runtime state lives in a `.mahira` folder next to the
executable** (the installation folder):

```
<install folder>/
├─ MAHIRA(.exe)            # or MAHIRA.app on macOS
├─ data/                   # bundled German seeds (data/seeds/<book>/<level>/) + pages (read-only)
├─ assets/                 # bundled logo + Piper voice models (read-only)
└─ .mahira/                # created on first run (writable)
   ├─ mahira.db            # SQLite database
   ├─ ml_models/           # scikit-learn ranker models
   ├─ run.log
   └─ crash.log
```

Path resolution lives in [`src/mahira/config.py`](src/mahira/config.py):

- `resource_root()` — read-only bundled resources (`data/`, `assets/`, `schema.sql`).
  Frozen → PyInstaller's `sys._MEIPASS`; from source → repo root.
- `data_root()` — writable state. Frozen → the executable's directory; from
  source → repo root. Override with the `MAHIRA_DATA_DIR` environment variable.

Because the Windows installer is **per-user** (installs into
`%LOCALAPPDATA%\Programs\MAHIRA`), the `.mahira` folder beside the exe is always
writable without admin rights.

> macOS note: data is written inside `MAHIRA.app/Contents/MacOS/.mahira`. This
> keeps everything in one bundle. If you place the app in a read-only location,
> set `MAHIRA_DATA_DIR` to a writable folder.

## What's in this repo for packaging

| File | Purpose |
|------|---------|
| `packaging/mahira.spec` | PyInstaller build (onedir; `.app` on macOS) |
| `packaging/windows/mahira.iss` | Inno Setup per-user installer script |
| `.github/workflows/release.yml` | CI: builds Win + macOS, publishes Release |
| `requirements-build.txt` | Runtime deps + PyInstaller |

## Build locally (optional)

From the repository root, in your virtualenv:

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

   The workflow then builds Windows + macOS and creates a **draft** GitHub
   Release with these assets attached:

   - `MAHIRA-Setup-<ver>-win64.exe` (Windows installer)
   - `MAHIRA-<ver>-win64-portable.zip` (Windows portable, unzip & run)
   - `MAHIRA-<ver>-macos.dmg` (macOS disk image)
   - `MAHIRA-<ver>-macos.zip`

3. **Review & publish:** GitHub → **Releases** → open the draft → edit notes →
   **Publish release**. (It's created as a draft so nothing goes public until you
   click publish.)

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

- **macOS architecture:** `macos-latest` runners are Apple Silicon (arm64), so
  the `.app`/`.dmg` are arm64. Add a `macos-13` job for an Intel build if needed.
- **Audio (Piper TTS):** the voice models are bundled, but PyInstaller may need
  extra hooks for `piper`/`onnxruntime` data on some setups. If pronunciation
  audio fails in a packaged build, that's the first place to look.
