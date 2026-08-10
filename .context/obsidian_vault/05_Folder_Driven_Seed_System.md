# Folder-Driven Seed System

MAHIRA content is read-only, disk-driven data under
`data/seeds/<book_slug>/<level>/`; book/level availability is never hardcoded.

## File identity

- Preferred filename:
  `<lektion>_<objective>__<Title>__<Topic>.csv`.
- Objectives: `vocab`, `grammar`, `sentences`, `listening`.
- The level comes from the lowercase CEFR folder; filename-level and legacy
  flat layouts remain supported.
- One logical `(book, level, Lektion, objective)` deck may have one source.

## Optional book manifest

`data/seeds/<book_slug>/manifest.json` may contain `title`, non-negative
`order`, and a book-local relative `cover`. The parser rejects unknown or
duplicate keys, unsafe/symlink paths, unsupported/corrupt image types, invalid
UTF-8, and traversal. Missing/malformed runtime metadata falls back to the
slug, deterministic ordering, conventional cover, then initials.

## Validation gate

`src/db/seed_validation.py` is the shared source/CI/runtime preflight:

```powershell
$env:PYTHONPATH = "src"
python -m mahira validate-seeds data/seeds
```

It performs no learner-state writes. Errors include noncanonical layout,
invalid filenames/metadata, headers, CSV shape/encoding, empty card-creation
fields, importer-equivalent duplicates, noun article/gender mismatches, and
invalid manifests. CI and release workflows run this command before tests or
packaging.

## Import lifecycle

1. `prepare_seed_csv()` snapshots and normalizes every CSV in memory.
2. `plan_seed_import()` compares hashes/metadata through SQLite `mode=ro`;
   missing databases are never created.
3. Unchanged decks are skipped. Any changed batch requires one verified
   `pre-seed-import` backup.
4. All changes apply in one `Repo.transaction()`; a failure rolls back the
   complete batch.
5. `Repo.sync_*_seed()` matches exact identities first, then only unambiguous
   one-to-one anchors. Matched cards keep IDs, FSRS state, reviews, and flags;
   ambiguous cards never inherit unrelated history.

`load_all_seeds(..., dry_run=True)` returns the same plan without backup or
mutation. Removed cards cascade their owned state/reviews and explicitly clear
non-FK `card_flags`.

See [[01_Architecture_and_Stack]], [[03_Database_and_Schema]],
[[04_UI_and_Frontend]], and [[07_Development_Safety_Invariants]].
