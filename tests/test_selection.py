"""Session assembly: highest-priority items are never dropped, and new
material is guaranteed a coverage quota."""

import random

from core.session import SessionService


def _session(eps=0.0, coverage=0.3):
    """A SessionService shell exercising only the pure assembly helpers
    (no DB / no Qt / no ML model)."""
    s = object.__new__(SessionService)
    s.rng = random.Random(0)
    s.ml_exploration_eps = eps
    s.unseen_coverage_fraction = coverage
    return s


# ranked is LOW priority first / HIGH priority last (the rank_* contract), so
# id 50 is the most urgent item and id 1 the least.
RANKED = list(range(1, 51))
FULL = list(range(1, 51))


def test_session_size_capped_at_limit():
    s = _session()
    q = s._assemble_queue(full_ids=FULL, unseen_ids=[], ranked_ids=RANKED, limit=10)
    assert len(q) == 10


def test_small_deck_returns_everything():
    s = _session()
    full = [1, 2, 3]
    q = s._assemble_queue(full_ids=full, unseen_ids=[], ranked_ids=[1, 2, 3], limit=10)
    assert sorted(q) == [1, 2, 3]


def test_highest_priority_item_never_dropped():
    s = _session()
    q = s._assemble_queue(full_ids=FULL, unseen_ids=[], ranked_ids=RANKED, limit=10)
    # The most-at-risk item (highest priority == last in ranked) MUST be present
    # and must be popped first (end of queue).
    assert 50 in q
    assert q[-1] == 50


def test_top_priority_block_selected_when_no_unseen():
    s = _session()
    q = s._assemble_queue(full_ids=FULL, unseen_ids=[], ranked_ids=RANKED, limit=10)
    assert sorted(q) == list(range(41, 51))


def test_unseen_coverage_quota_enforced():
    s = _session(coverage=0.3)
    # Unseen items (1..5) are the LOWEST priority, so a pure top-10 would
    # exclude them. The coverage quota must force some in anyway.
    unseen = [1, 2, 3, 4, 5]
    q = s._assemble_queue(full_ids=FULL, unseen_ids=unseen, ranked_ids=RANKED, limit=10)
    assert len(q) == 10
    in_q_unseen = [i for i in q if i in unseen]
    assert len(in_q_unseen) >= 3  # quota = round(10 * 0.3)
    # The most urgent seen item is still kept despite making room for coverage.
    assert 50 in q


def test_coverage_does_not_exceed_available_unseen():
    s = _session(coverage=0.5)
    unseen = [1]  # only one unseen item exists
    q = s._assemble_queue(full_ids=FULL, unseen_ids=unseen, ranked_ids=RANKED, limit=10)
    assert len(q) == 10
    assert 1 in q  # the single unseen item is covered
    assert 50 in q  # urgent item retained


def test_fresh_deck_introduced_in_natural_order():
    """All-unseen deck: items should be introduced lowest-id-first."""
    s = _session(coverage=0.3)
    full = list(range(1, 21))
    # On a fresh deck every item ties on priority; the ranker tie-break puts the
    # earliest id last (popped first). Simulate that contract:
    ranked = list(reversed(full))  # 20,19,...,1  -> id 1 is last == first popped
    q = s._assemble_queue(full_ids=full, unseen_ids=full, ranked_ids=ranked, limit=5)
    assert len(q) == 5
    assert q[-1] == 1  # lowest id introduced first


def test_exploration_disabled_is_deterministic():
    s1 = _session(eps=0.0)
    s2 = _session(eps=0.0)
    q1 = s1._assemble_queue(full_ids=FULL, unseen_ids=[], ranked_ids=RANKED, limit=10)
    q2 = s2._assemble_queue(full_ids=FULL, unseen_ids=[], ranked_ids=RANKED, limit=10)
    assert q1 == q2
