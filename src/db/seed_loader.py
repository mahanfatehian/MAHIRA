from __future__ import annotations

from pathlib import Path

from db.seed_import import import_seed_csv


def load_all_seeds(repo, project_root: Path) -> None:
    """
    German-only seed layout:

      data/seeds/<book_slug>/{level}_{lektion}_{objective}.csv   (book decks)
      data/seeds/*.csv                                           (legacy flat decks)
    """
    seeds_root = project_root / "data" / "seeds"
    if not seeds_root.exists():
        return

    # Legacy flat files directly under data/seeds/ (no book/lektion)
    for csv_path in sorted(seeds_root.glob("*.csv")):
        import_seed_csv(repo, csv_path, book_slug=None, lektion_number=None)

    # Book directories at data/seeds/<book_slug>/*.csv
    for book_dir in sorted(seeds_root.iterdir()):
        if not book_dir.is_dir():
            continue
        book_slug = book_dir.name.lower().strip()
        for csv_path in sorted(book_dir.glob("*.csv")):
            import_seed_csv(repo, csv_path, book_slug=book_slug, lektion_number=None)
