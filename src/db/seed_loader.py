from __future__ import annotations

from pathlib import Path

from db.seed_import import import_seed_csv, CEFR_LEVELS


def load_all_seeds(repo, project_root: Path) -> None:
    with repo.transaction():
        _load_all_seeds(repo, project_root)


def _load_all_seeds(repo, project_root: Path) -> None:
    """
    German-only, fully folder-driven seed layout. The CEFR level is taken from
    the directory, never hardcoded, so which levels (and therefore which books)
    exist is determined entirely by what folders are present on disk:

      data/seeds/<book_slug>/<level>/<lektion>_<objective>[__Title__Topic].csv
        e.g. data/seeds/starten_wir/a1/1_vocab__Super!__Greetings....csv
             data/seeds/starten_wir/a2/1_grammar.csv
             data/seeds/sicher/b1/1_vocab.csv

    A book appears at a level if and only if it has a <level> folder with
    content there. Drop in data/seeds/sicher/b1/... and "Sicher" shows up under
    B1; "Starten Wir" never appears under B1 because it has no b1 folder. No
    code change is needed to add a book or a level.

    Backward-compatible fallbacks (still imported if present):
      - data/seeds/<book_slug>/<level>_<lektion>_<objective>.csv  (flat, level in filename)
      - data/seeds/<level>_<objective>.csv                        (legacy book-less decks)
    """
    seeds_root = project_root / "data" / "seeds"
    if not seeds_root.exists():
        return

    # Legacy flat files directly under data/seeds/ (book-less; level from filename).
    for csv_path in sorted(seeds_root.glob("*.csv")):
        import_seed_csv(repo, csv_path, book_slug=None, lektion_number=None, level=None)

    for book_dir in sorted(seeds_root.iterdir()):
        if not book_dir.is_dir():
            continue
        book_slug = book_dir.name.lower().strip()

        # Preferred: per-level subfolders (level comes from the folder name).
        for level_dir in sorted(book_dir.iterdir()):
            if not level_dir.is_dir():
                continue
            level = level_dir.name.lower().strip()
            if level not in CEFR_LEVELS:
                continue
            for csv_path in sorted(level_dir.glob("*.csv")):
                import_seed_csv(
                    repo, csv_path, book_slug=book_slug, lektion_number=None, level=level
                )

        # Backward-compat: CSVs sitting directly in the book folder, with the
        # level encoded in the filename (the old "a1_1_vocab.csv" layout).
        for csv_path in sorted(book_dir.glob("*.csv")):
            import_seed_csv(repo, csv_path, book_slug=book_slug, lektion_number=None, level=None)
