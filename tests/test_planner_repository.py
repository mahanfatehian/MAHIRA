from __future__ import annotations



OBJECTIVES = ("vocab", "grammar", "sentences", "listening")


def _repo(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "planner-repository.db"
    init_db(db)
    return Repo(db)


def _seed_all_objectives(repo):
    book_id = repo.ensure_book("menschen", "Menschen")
    lektion_id = repo.ensure_lektion(book_id, "A1", 2, "Freunde")
    decks = {
        objective: repo.upsert_deck(
            "A1", objective, f"{objective}.csv", f"sha-{objective}", lektion_id
        )[0]
        for objective in OBJECTIVES
    }
    items = {
        "vocab": repo.insert_vocab(
            decks["vocab"], "noun", "Haus", "das", "n", "Häuser", "house"
        ),
        "grammar": repo.insert_grammar(
            decks["grammar"], "Ich ___ hier.", "bin", "sein", None, None, None
        ),
        "sentences": repo.insert_sentence(
            decks["sentences"], "Ich bin hier.", None, None, None
        ),
        "listening": repo.insert_listening(
            decks["listening"], "Ich bin hier.", "Wo?", "hier", None, None, None
        ),
    }
    return decks, items


def test_planner_inventory_filters_future_recent_buried_and_suspended(tmp_path):
    repo = _repo(tmp_path)
    decks, items = _seed_all_objectives(repo)
    now = 1_800_000_000

    # One state-less vocabulary card remains new.
    new_vocab = repo.insert_vocab(
        decks["vocab"], "noun", "Tag", "der", "m", "Tage", "day"
    )
    future = repo.insert_vocab(
        decks["vocab"], "verb", "gehen", "", "", "", "go"
    )
    recent = repo.insert_vocab(
        decks["vocab"], "verb", "lernen", "", "", "", "learn"
    )
    suspended = repo.insert_vocab(
        decks["vocab"], "verb", "sehen", "", "", "", "see"
    )
    buried = repo.insert_vocab(
        decks["vocab"], "verb", "hören", "", "", "", "hear"
    )
    # Each objective's seeded item is due outside the cooldown.
    state_specs = {
        "vocab": ("vocab_states", "vocab_id"),
        "grammar": ("grammar_states", "grammar_id"),
        "sentences": ("sentence_states", "sentence_id"),
        "listening": ("listening_states", "listening_id"),
    }
    with repo._conn() as conn:
        for objective, item_id in items.items():
            table, fk = state_specs[objective]
            conn.execute(
                f"INSERT INTO {table}({fk}, due_at, last_review_at) VALUES(?,?,?)",
                (item_id, now, now - 43_200),
            )

        conn.execute(
            "INSERT INTO vocab_states(vocab_id,due_at,last_review_at) VALUES(?,?,?)",
            (future, now + 1, now - 100_000),
        )
        conn.execute(
            "INSERT INTO vocab_states(vocab_id,due_at,last_review_at) VALUES(?,?,?)",
            (recent, now, now - 43_199),
        )
        conn.execute(
            "INSERT INTO vocab_states(vocab_id,due_at,last_review_at,suspended) VALUES(?,?,?,1)",
            (suspended, now, now - 100_000),
        )
        conn.execute(
            "INSERT INTO vocab_states(vocab_id,due_at,last_review_at,buried_until) VALUES(?,?,?,?)",
            (buried, now, now - 100_000, now + 1),
        )

    inventory = repo.planner_inventory(now)

    assert [(row.objective, row.item_id, row.bucket) for row in inventory] == [
        ("vocab", items["vocab"], "due"),
        ("vocab", new_vocab, "new"),
        ("grammar", items["grammar"], "due"),
        ("sentences", items["sentences"], "due"),
        ("listening", items["listening"], "due"),
    ]
    assert all(row.level == "A1" for row in inventory)
    assert all(row.book_slug == "menschen" for row in inventory)
    assert all(row.lektion_number == 2 for row in inventory)


def test_daily_plan_usage_counts_exact_primary_lanes_and_half_open_day(tmp_path):
    repo = _repo(tmp_path)
    _decks, items = _seed_all_objectives(repo)
    start, end = 1_800_000_000, 1_800_086_400
    table_specs = {
        "vocab": ("reviews", "vocab_id", "recognition"),
        "grammar": ("grammar_reviews", "grammar_id", "production"),
        "sentences": ("sentence_reviews", "sentence_id", "builder"),
        "listening": ("listening_reviews", "listening_id", "comprehension"),
    }
    buckets = {"vocab": "due", "grammar": "new", "sentences": "extra", "listening": "legacy"}
    with repo._conn() as conn:
        for objective, item_id in items.items():
            table, fk, mode = table_specs[objective]
            conn.execute(
                f"INSERT INTO {table}({fk},created_at,practice_mode,was_checked,was_skipped,selection_bucket) "
                "VALUES(?,?,?,?,?,?)",
                (item_id, start, mode, 1, 0, buckets[objective]),
            )
            for created_at, bad_mode, checked, skipped in (
                (end, mode, 1, 0),
                (start + 1, f"other-{mode}", 1, 0),
                (start + 2, mode, 0, 0),
                (start + 3, mode, 1, 1),
            ):
                conn.execute(
                    f"INSERT INTO {table}({fk},created_at,practice_mode,was_checked,was_skipped) "
                    "VALUES(?,?,?,?,?)",
                    (item_id, created_at, bad_mode, checked, skipped),
                )

    usage = {row.objective: row for row in repo.daily_plan_usage(start, end)}

    assert {objective: usage[objective].completed for objective in OBJECTIVES} == {
        objective: 1 for objective in OBJECTIVES
    }
    assert (usage["vocab"].due, usage["vocab"].new) == (1, 0)
    assert (usage["grammar"].due, usage["grammar"].new) == (0, 1)
    assert (usage["sentences"].due, usage["sentences"].new) == (0, 0)
    assert (usage["listening"].due, usage["listening"].new) == (0, 0)
