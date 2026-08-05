# Folder-Driven Seed System

MAHIRA content is disk-driven, not hardcoded.

## Directory model
`data/seeds/<book>/<level>/`

- `<book>`: content collection (course/module family)
- `<level>`: level or proficiency tier (A1, A2, B1, B2, etc.)
- files: CSV seed tables loaded at runtime

This design lets maintainers add/edit curriculum by filesystem changes only.

## Lektion and topic parsing
CSV filenames encode structure:
- Lektion index is parsed from filename tokens
- lesson/topic labels are extracted from file naming convention
- parser keeps title parsing independent from UI strings

If a file is renamed/moved:
- discovery changes reflect automatically on next load
- no Python code changes needed for new books/levels

## Runtime behavior
1. Discover seed folders recursively in `data/seeds/...`
2. Validate CSV schema minimally (headers + records)
3. Build deck/topic metadata from path and filename
4. Seed importer writes cards/rows into SQLite with stable identity mapping

## Why it scales
- adds new materials by copy/paste conventions
- supports localized/country-specific decks
- reduces merge conflict risk in code during content updates

Cross-links:
- [[01_Architecture_and_Stack]]
- [[03_Database_and_Schema]]
- [[04_UI_and_Frontend]]
