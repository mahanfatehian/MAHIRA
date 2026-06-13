from __future__ import annotations

from pathlib import Path

from db.seed_import import import_seed_csv


def load_all_seeds(repo, project_root: Path) -> None:
    seeds_root = project_root / "data" / "seeds"
    if not seeds_root.exists():
        return

    for lang_dir in sorted(seeds_root.iterdir()):
        if not lang_dir.is_dir():
            continue

        language_code = lang_dir.name.lower().strip()

        if hasattr(repo, "ensure_language"):
            repo.ensure_language(language_code)

        # Old-style flat files at seeds/{lang}/*.csv (no book/lektion)
        for csv_path in sorted(lang_dir.glob("*.csv")):
            import_seed_csv(repo, language_code, csv_path, book_slug=None, lektion_number=None)

        # New-style book directories at seeds/{lang}/{book_slug}/*.csv
        for book_dir in sorted(lang_dir.iterdir()):
            if not book_dir.is_dir():
                continue
            book_slug = book_dir.name.lower().strip()
            for csv_path in sorted(book_dir.glob("*.csv")):
                import_seed_csv(repo, language_code, csv_path, book_slug=book_slug, lektion_number=None)
