from __future__ import annotations

import pytest


NOW = 1_800_000_000
DAY = 86_400


def _library(tmp_path):
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "recent-failures.db"
    init_db(db)
    repo = Repo(db)

    alpha = repo.ensure_book("alpha", "Alpha")
    alpha_lesson = repo.ensure_lektion(alpha, "A1", 1, "Alpha One")
    beta = repo.ensure_book("beta", "Beta")
    beta_lesson = repo.ensure_lektion(beta, "A1", 1, "Beta One")
    alpha_deck, _ = repo.upsert_deck(
        "A1", "vocab", "alpha.csv", "alpha-sha", lektion_id=alpha_lesson
    )
    beta_deck, _ = repo.upsert_deck(
        "A1", "vocab", "beta.csv", "beta-sha", lektion_id=beta_lesson
    )
    ids = [
        repo.insert_vocab(
            alpha_deck, "noun", word, article, gender, plural, meaning
        )
        for word, article, gender, plural, meaning in (
            ("Haus", "das", "n", "Haeuser", "house"),
            ("Stadt", "die", "f", "Staedte", "city"),
            ("Tag", "der", "m", "Tage", "day"),
        )
    ]
    foreign = repo.insert_vocab(
        beta_deck, "noun", "Zeit", "die", "f", "Zeiten", "time"
    )
    for item_id in (*ids, foreign):
        repo.ensure_state(item_id)
    return repo, ids, foreign


def _review(
    repo,
    item_id: int,
    *,
    created_at: int,
    rating: int | None = 0,
    lane: str = "recognition",
    tags: str | None = None,
):
    with repo._conn() as conn:
        conn.execute(
            """
            INSERT INTO reviews(
                vocab_id, created_at, rating, practice_mode, error_tags
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, created_at, rating, lane, tags),
        )


def test_recent_failures_use_exact_context_lane_tag_and_latest_unique_card(tmp_path):
    from core.insights import InsightsService, RecentFailure

    repo, (haus, stadt, tag), foreign = _library(tmp_path)
    _review(repo, haus, created_at=NOW - 3 * DAY, tags=" article , spelling ")
    _review(repo, haus, created_at=NOW - 2 * DAY, tags="spelling")
    _review(repo, haus, created_at=NOW - DAY, tags="word_order")
    _review(
        repo,
        haus,
        created_at=NOW,
        lane="production",
        tags="article",
    )
    _review(repo, stadt, created_at=NOW, tags="article_missing")
    _review(repo, tag, created_at=NOW + 1, rating=1, tags="article")
    _review(repo, tag, created_at=NOW + 5, tags="article")
    _review(repo, foreign, created_at=NOW + 2, tags="article")
    with repo._conn() as conn:
        conn.execute(
            "UPDATE vocab_states SET suspended=1 WHERE vocab_id=?",
            (haus,),
        )

    insights = InsightsService(repo)
    rows = insights.recent_failures(
        level="A1",
        book_slug=" ALPHA ",
        lektion_number=1,
        objective="vocab",
        practice_mode="recognition",
        limit=20,
        now=NOW,
    )
    assert all(isinstance(row, RecentFailure) for row in rows)
    assert [row.item_id for row in rows] == [stadt, haus]
    assert rows[1].error_tags == "word_order"
    assert rows[1].failure_count == 3
    assert rows[1].is_leech is True
    assert rows[1].leech_window_days == 30
    assert rows[1].suspended is True

    exact_tag = insights.recent_failures(
        level="A1",
        book_slug="alpha",
        lektion_number=1,
        objective="vocab",
        practice_mode="recognition",
        tag="article",
        limit=20,
        now=NOW,
    )
    assert [row.item_id for row in exact_tag] == [haus]
    assert exact_tag[0].last_failed_at == NOW - 3 * DAY
    assert exact_tag[0].failure_count == 3

    production = insights.recent_failures(
        level="A1",
        book_slug="alpha",
        lektion_number=1,
        objective="vocab",
        practice_mode="production",
        now=NOW,
    )
    assert [(row.item_id, row.practice_mode) for row in production] == [
        (haus, "production")
    ]
    assert production[0].failure_count == 1

    beta_rows = insights.recent_failures(
        level="A1",
        book_slug="beta",
        lektion_number=1,
        objective="vocab",
        practice_mode="recognition",
        now=NOW + 2,
    )
    assert [row.item_id for row in beta_rows] == [foreign]


def test_recent_failures_exclude_future_burial_but_include_expired_and_validate(tmp_path):
    from core.insights import InsightsService

    repo, (haus, stadt, _tag), _foreign = _library(tmp_path)
    _review(repo, haus, created_at=NOW - 1, tags="spelling")
    _review(repo, stadt, created_at=NOW, tags="spelling")
    with repo._conn() as conn:
        conn.execute(
            "UPDATE vocab_states SET buried_until=? WHERE vocab_id=?",
            (NOW + 1, stadt),
        )
    insights = InsightsService(repo)
    kwargs = dict(
        level="A1",
        book_slug="alpha",
        lektion_number=1,
        objective="vocab",
        practice_mode="recognition",
        now=NOW,
    )
    assert [row.item_id for row in insights.recent_failures(**kwargs)] == [haus]

    with repo._conn() as conn:
        conn.execute(
            "UPDATE vocab_states SET buried_until=? WHERE vocab_id=?",
            (NOW, stadt),
        )
    assert [row.item_id for row in insights.recent_failures(**kwargs)] == [
        stadt,
        haus,
    ]
    assert [row.item_id for row in insights.recent_failures(**kwargs, limit=1)] == [
        stadt
    ]

    with pytest.raises(ValueError, match="supplied together"):
        insights.recent_failures(level="A1")
    with pytest.raises(ValueError, match="supplied together"):
        insights.recent_failures(objective="vocab")
    with pytest.raises(ValueError, match="Invalid error tag"):
        insights.recent_failures(tag="article,spelling")
    with pytest.raises(ValueError, match="lektion_number must be an integer"):
        insights.recent_failures(level="A1", book_slug="alpha", lektion_number=True)
    with pytest.raises(ValueError, match="limit must be an integer"):
        insights.recent_failures(limit=True)


def test_recent_failures_read_rating_zero_from_every_primary_review_table(tmp_path):
    from core.insights import InsightsService
    from db.init_db import init_db
    from db.repo import Repo

    db = tmp_path / "all-objectives.db"
    init_db(db)
    repo = Repo(db)
    vocab_deck, _ = repo.upsert_deck("A1", "vocab", "v.csv", "v")
    grammar_deck, _ = repo.upsert_deck("A1", "grammar", "g.csv", "g")
    sentence_deck, _ = repo.upsert_deck("A1", "sentences", "s.csv", "s")
    listening_deck, _ = repo.upsert_deck("A1", "listening", "l.csv", "l")
    vocab_id = repo.insert_vocab(
        vocab_deck, "noun", "Haus", "das", "n", "Haeuser", "house"
    )
    grammar_id = repo.insert_grammar(
        grammar_deck, "Ich ___ Deutsch.", "lerne", None, None, None, None
    )
    sentence_id = repo.insert_sentence(
        sentence_deck, "Ich lerne Deutsch.", "I learn German.", None, None
    )
    listening_id = repo.insert_listening(
        listening_deck, "Ich lerne.", "Was?", "Deutsch", None, None, None
    )
    repo.ensure_state(vocab_id)
    repo.ensure_grammar_state(grammar_id)
    repo.ensure_sentence_state(sentence_id)
    repo.ensure_listening_state(listening_id)

    rows = (
        ("reviews", "vocab_id", vocab_id, "recognition", "meaning_correct"),
        ("grammar_reviews", "grammar_id", grammar_id, "production", "correct"),
        ("sentence_reviews", "sentence_id", sentence_id, "builder", "correct"),
        ("listening_reviews", "listening_id", listening_id, "comprehension", "correct"),
    )
    with repo._conn() as conn:
        for table, foreign_key, item_id, lane, correctness in rows:
            conn.execute(
                f"INSERT INTO {table}({foreign_key},created_at,rating,practice_mode,{correctness}) "
                "VALUES(?,?,0,?,1)",
                (item_id, NOW - 10, lane),
            )
            conn.execute(
                f"INSERT INTO {table}({foreign_key},created_at,rating,practice_mode,{correctness}) "
                "VALUES(?,?,2,?,0)",
                (item_id, NOW - 1, lane),
            )

    failures = InsightsService(repo).recent_failures(now=NOW)
    assert {
        (row.objective, row.practice_mode): row.last_failed_at for row in failures
    } == {
        ("vocab", "recognition"): NOW - 10,
        ("grammar", "production"): NOW - 10,
        ("sentences", "builder"): NOW - 10,
        ("listening", "comprehension"): NOW - 10,
    }


def test_leech_window_is_inclusive_and_counts_each_lane_separately(tmp_path):
    from core.insights import InsightsService

    repo, (haus, _stadt, _tag), _foreign = _library(tmp_path)
    for created_at in (NOW - 30 * DAY, NOW - 1, NOW):
        _review(repo, haus, created_at=created_at)
    for created_at in (NOW - 2, NOW - 1):
        _review(repo, haus, created_at=created_at, lane="production")
    _review(repo, haus, created_at=NOW - 30 * DAY - 1, lane="production")

    insights = InsightsService(repo)
    recognition = insights.recent_failures(
        objective="vocab", practice_mode="recognition", now=NOW
    )[0]
    production = insights.recent_failures(
        objective="vocab", practice_mode="production", now=NOW
    )[0]
    assert (recognition.failure_count, recognition.is_leech) == (3, True)
    assert (production.failure_count, production.is_leech) == (2, False)


def test_tag_and_context_filter_before_limit(tmp_path):
    from core.insights import InsightsService

    repo, (haus, stadt, tag), foreign = _library(tmp_path)
    _review(repo, haus, created_at=NOW - 10, tags="article")
    _review(repo, stadt, created_at=NOW - 3, tags="spelling")
    _review(repo, tag, created_at=NOW - 2, tags="spelling")
    _review(repo, foreign, created_at=NOW - 1, tags="article")

    rows = InsightsService(repo).recent_failures(
        level="A1",
        book_slug="alpha",
        lektion_number=1,
        objective="vocab",
        practice_mode="recognition",
        tag="article",
        limit=1,
        now=NOW,
    )
    assert [row.item_id for row in rows] == [haus]
