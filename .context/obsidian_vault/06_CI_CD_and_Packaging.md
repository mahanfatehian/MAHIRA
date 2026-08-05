# CI/CD and Packaging

## GitHub Actions
### `release.yml`
- builds release artifacts from tagged pushes/released commits
- runs packaging pipeline for Windows/macOS
- uploads installer/binary artifacts
- often gates on test pass + version correctness

### `tests.yml`
- runs unit and integration tests
- validates deterministic behavior across Python environments
- verifies DB/seed/core behavior before merge
- can include linting/static checks where configured

## Packaging
### PyInstaller
- bundles app into standalone executables
- includes Python runtime, Qt/PySide6 resources, and assets
- config includes hidden imports/resource files for offline reliability

### Inno Setup (Windows)
- wraps installer and shortcuts
- writes required runtime folders and first-run state layout
- ensures `.mahira/` and bundled defaults exist on fresh install

### macOS
- macOS binary/package signing conventions handled in release workflow
- app bundle packaging preserves local state paths and data permissions

## Large model assets and Git LFS
- ONNX Piper voice models and related large binaries should not be committed directly via regular git
- Git LFS tracks large artifacts (notably TTS models/voices)
- local/integration flows should tolerate LFS pointer availability and cache resolution

Related modules:
- [[01_Architecture_and_Stack]]
- [[02_Core_Engine_and_ML]]
