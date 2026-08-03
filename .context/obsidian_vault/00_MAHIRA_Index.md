# MAHIRA Context Vault Index

MAHIRA is an **offline-first PySide6 desktop app** for German learning with a spaced-repetition engine (FSRS 4.5 + ML rank augmentation), folder-driven seed content, and local SQLite state in `.mahira/`.

## Core orientation
- [[01_Architecture_and_Stack]]
- [[02_Core_Engine_and_ML]]
- [[03_Database_and_Schema]]
- [[04_UI_and_Frontend]]
- [[05_Folder_Driven_Seed_System]]
- [[06_CI_CD_and_Packaging]]

## Where to look first
- Application behavior and runtime: [[01_Architecture_and_Stack]]
- Review logic, scheduling, and priority: [[02_Core_Engine_and_ML]]
- Persistence, migrations, and backups: [[03_Database_and_Schema]]
- UX/navigation and widgets: [[04_UI_and_Frontend]]
- Content import pipeline: [[05_Folder_Driven_Seed_System]]
- Build/CI/release automation: [[06_CI_CD_and_Packaging]]

## High-level execution model
1. App bootstrap reads configuration and opens a persistent workspace under `.mahira/`.
2. UI pages request work via repositories/services in the core/db layer.
3. Core computes review due sets and priorities.
4. Audio and seed systems stay local/offline by design.
5. State writes go only to local storage; no mandatory network dependency.

See related modules:
- [[02_Core_Engine_and_ML]]
- [[03_Database_and_Schema]]
- [[04_UI_and_Frontend]]
- [[05_Folder_Driven_Seed_System]]
