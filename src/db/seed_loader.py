from __future__ import annotations

from pathlib import Path

from db.seed_import import import_seed_csv


def load_all_seeds(repo, project_root: Path) -> None:
    seeds_root = project_root / "data" / "seeds"
    if not seeds_root.exists():
        return

    for lang_dir in seeds_root.iterdir():
        if not lang_dir.is_dir():
            continue

        language_code = lang_dir.name.lower().strip()

        # prevents FK errors on decks(language_code) -> languages(code)
        if hasattr(repo, "ensure_language"):
            repo.ensure_language(language_code)

        for csv_path in sorted(lang_dir.glob("*.csv")):
            import_seed_csv(repo, language_code, csv_path)
