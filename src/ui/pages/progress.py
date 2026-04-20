from __future__ import annotations

import time
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QGridLayout, QGroupBox
)

from core.session import SessionService


class ProgressCard(QGroupBox):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setStyleSheet("""
            QGroupBox {
                font-size: 13px;
                font-weight: 900;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 12px;
                background-color: #151515;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px 0 8px;
            }
        """)

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(6)
        self.layout.setContentsMargins(12, 16, 12, 12)

        self.value_label = QLabel("0")
        self.value_label.setStyleSheet("""
            QLabel {
                font-size: 26px;
                font-weight: 900;
                color: #FFFFFF;
                qproperty-alignment: AlignCenter;
            }
        """)

        self.description_label = QLabel("")
        self.description_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #B0B0B0;
                qproperty-alignment: AlignCenter;
            }
        """)

        self.layout.addWidget(self.value_label)
        self.layout.addWidget(self.description_label)
        self.layout.addStretch(1)

    def set_value(self, value, description: str = ""):
        self.value_label.setText(str(value))
        self.description_label.setText(description)


class ProgressPage(QWidget):
    go_learn = Signal()

    def __init__(self, session: SessionService):
        super().__init__()
        self.session = session

        self.setObjectName("ProgressPage")
        self.setStyleSheet("""
            #ProgressPage { background-color: #0F0F0F; color: #E6E6E6; }
            #ProgressPage QLabel { background: transparent; }
        """)

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(14)

        header_layout = QHBoxLayout()
        self.title = QLabel("Progress")
        self.title.setStyleSheet("font-size:16px; font-weight:800; color:#FFFFFF;")

        btn_learn = QPushButton("Back to Practice")
        btn_learn.setStyleSheet("""
            QPushButton {
                background-color: #163A5C;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 900;
            }
            QPushButton:hover { background-color: #1B4B78; border: 1px solid #FFFFFF; }
        """)
        btn_learn.clicked.connect(self.go_learn.emit)

        header_layout.addWidget(self.title)
        header_layout.addStretch(1)
        header_layout.addWidget(btn_learn)

        session_group = QGroupBox("Current Context")
        session_group.setStyleSheet("""
            QGroupBox {
                font-size: 13px;
                font-weight: 900;
                color: #FFFFFF;
                border: 1px solid #2E2E2E;
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 12px;
                background-color: #151515;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px 0 8px;
            }
        """)

        session_layout = QGridLayout(session_group)
        session_layout.setSpacing(12)
        session_layout.setContentsMargins(12, 16, 12, 12)

        self.language_label = QLabel("Language: --")
        self.level_label = QLabel("Level: --")
        self.objective_label = QLabel("Objective: --")

        for label in (self.language_label, self.level_label, self.objective_label):
            label.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    color: #E6E6E6;
                    padding: 8px 10px;
                    background-color: #101010;
                    border: 1px solid #2A2A2A;
                    border-radius: 10px;
                }
            """)

        session_layout.addWidget(self.language_label, 0, 0)
        session_layout.addWidget(self.level_label, 0, 1)
        session_layout.addWidget(self.objective_label, 1, 0)

        stats_group = QGroupBox("Statistics")
        stats_group.setStyleSheet(session_group.styleSheet())

        stats_layout = QGridLayout(stats_group)
        stats_layout.setSpacing(14)
        stats_layout.setContentsMargins(12, 16, 12, 12)

        self.due_card = ProgressCard("Due Now")
        self.reviewed_today_card = ProgressCard("Reviewed (24h)")
        self.reviewed_total_card = ProgressCard("Total Reviews")
        self.unseen_card = ProgressCard("Unseen")
        self.total_card = ProgressCard("Total Cards")
        self.mastery_card = ProgressCard("Mastery")

        stats_layout.addWidget(self.due_card, 0, 0)
        stats_layout.addWidget(self.reviewed_today_card, 0, 1)
        stats_layout.addWidget(self.reviewed_total_card, 0, 2)
        stats_layout.addWidget(self.unseen_card, 1, 0)
        stats_layout.addWidget(self.total_card, 1, 1)
        stats_layout.addWidget(self.mastery_card, 1, 2)

        perf_group = QGroupBox("Summary")
        perf_group.setStyleSheet(session_group.styleSheet())

        perf_layout = QVBoxLayout(perf_group)
        perf_layout.setSpacing(10)
        perf_layout.setContentsMargins(12, 16, 12, 12)

        self.performance_label = QLabel("")
        self.performance_label.setStyleSheet("font-size:12px; color:#CCCCCC; line-height:1.4;")
        self.performance_label.setWordWrap(True)
        perf_layout.addWidget(self.performance_label)

        main_layout.addLayout(header_layout)
        main_layout.addWidget(session_group)
        main_layout.addWidget(stats_group)
        main_layout.addWidget(perf_group)
        main_layout.addStretch(1)

    # --------- DB helpers ----------
    def _conn(self):
        return self.session.repo._conn()

    def _normalized_objective(self) -> str:
        obj = (getattr(self.session.state, "objective", None) or "").lower().strip()
        if obj == "grammer":
            obj = "grammar"
        return obj

    # ----- vocab helpers -----
    def _deck_vocab_count(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "deck_vocab_count"):
            return int(repo.deck_vocab_count(deck_id))
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM vocab WHERE deck_id=?", (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def _due_count(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "due_count"):
            return int(repo.due_count(deck_id))
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM vocab v
                JOIN vocab_states s ON s.vocab_id=v.id
                WHERE v.deck_id=? AND s.due_at<=?
            """, (deck_id, now)).fetchone()
            return int(row["c"]) if row else 0

    def _reviewed_last_24h(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "reviewed_last_24h"):
            return int(repo.reviewed_last_24h(deck_id))
        since = int(time.time()) - 24 * 3600
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM reviews r
                JOIN vocab v ON v.id = r.vocab_id
                WHERE v.deck_id=? AND r.created_at>=?
            """, (deck_id, since)).fetchone()
            return int(row["c"]) if row else 0

    def _unseen_count(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "unseen_count"):
            return int(repo.unseen_count(deck_id))
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM vocab v
                LEFT JOIN vocab_states s ON s.vocab_id=v.id
                WHERE v.deck_id=? AND s.id IS NULL
            """, (deck_id,)).fetchone()
            return int(row["c"]) if row else self._deck_vocab_count(deck_id)

    def _get_total_reviews(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as c
                FROM reviews r
                JOIN vocab v ON r.vocab_id = v.id
                WHERE v.deck_id = ?
            """, (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def _calculate_mastery(self, deck_id: int, total_cards: int) -> int:
        if total_cards <= 0:
            return 0

        with self._conn() as conn:
            reviewed_row = conn.execute("""
                SELECT COUNT(DISTINCT v.id) as reviewed_count
                FROM vocab v
                JOIN reviews r ON v.id = r.vocab_id
                WHERE v.deck_id = ?
            """, (deck_id,)).fetchone()
            reviewed_count = int(reviewed_row["reviewed_count"]) if reviewed_row else 0
            seen_pct = (reviewed_count / total_cards) * 100

            stats = conn.execute("""
                SELECT
                    SUM(CASE WHEN meaning_correct IS NOT NULL THEN 1 ELSE 0 END) as m_app,
                    SUM(CASE WHEN meaning_correct = 1 THEN 1 ELSE 0 END) as m_ok,
                    SUM(CASE WHEN gender_correct IS NOT NULL THEN 1 ELSE 0 END) as g_app,
                    SUM(CASE WHEN gender_correct = 1 THEN 1 ELSE 0 END) as g_ok,
                    SUM(CASE WHEN plural_correct IS NOT NULL THEN 1 ELSE 0 END) as p_app,
                    SUM(CASE WHEN plural_correct = 1 THEN 1 ELSE 0 END) as p_ok
                FROM reviews r
                JOIN vocab v ON r.vocab_id = v.id
                WHERE v.deck_id = ?
            """, (deck_id,)).fetchone()

            if not stats:
                return int(min(100, max(0, seen_pct)))

            app = int(stats["m_app"] or 0) + int(stats["g_app"] or 0) + int(stats["p_app"] or 0)
            ok = int(stats["m_ok"] or 0) + int(stats["g_ok"] or 0) + int(stats["p_ok"] or 0)

            if app <= 0:
                return int(min(100, max(0, seen_pct)))

            success_pct = (ok / app) * 100
            blended = (seen_pct * 0.4) + (success_pct * 0.6)
            return int(min(100, max(0, blended)))

    # ----- grammar helpers -----
    def _deck_grammar_count(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "deck_grammar_count"):
            return int(repo.deck_grammar_count(deck_id))
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM grammar WHERE deck_id=?", (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def _grammar_due_count(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "grammar_due_count"):
            return int(repo.grammar_due_count(deck_id))
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM grammar g
                JOIN grammar_states s ON s.grammar_id=g.id
                WHERE g.deck_id=? AND s.due_at<=?
            """, (deck_id, now)).fetchone()
            return int(row["c"]) if row else 0

    def _grammar_reviewed_last_24h(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "grammar_reviewed_last_24h"):
            return int(repo.grammar_reviewed_last_24h(deck_id))
        since = int(time.time()) - 24 * 3600
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM grammar_reviews r
                JOIN grammar g ON g.id = r.grammar_id
                WHERE r.created_at >= ?
                  AND g.deck_id = ?
            """, (since, deck_id)).fetchone()
            return int(row["c"]) if row else 0

    def _grammar_unseen_count(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "grammar_unseen_count"):
            return int(repo.grammar_unseen_count(deck_id))
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM grammar g
                LEFT JOIN grammar_states s ON s.grammar_id=g.id
                WHERE g.deck_id=? AND s.id IS NULL
            """, (deck_id,)).fetchone()
            return int(row["c"]) if row else self._deck_grammar_count(deck_id)

    def _get_total_grammar_reviews(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as c
                FROM grammar_reviews r
                JOIN grammar g ON r.grammar_id = g.id
                WHERE g.deck_id = ?
            """, (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def _calculate_grammar_mastery(self, deck_id: int, total_cards: int) -> int:
        if total_cards <= 0:
            return 0
        with self._conn() as conn:
            reviewed_row = conn.execute("""
                SELECT COUNT(DISTINCT g.id) as reviewed_count
                FROM grammar g
                JOIN grammar_reviews r ON g.id = r.grammar_id
                WHERE g.deck_id = ?
            """, (deck_id,)).fetchone()
            reviewed_count = int(reviewed_row["reviewed_count"]) if reviewed_row else 0
            seen_pct = (reviewed_count / total_cards) * 100

            stats = conn.execute("""
                SELECT
                    SUM(CASE WHEN r.correct IS NOT NULL THEN 1 ELSE 0 END) as app,
                    SUM(CASE WHEN r.correct = 1 THEN 1 ELSE 0 END) as ok
                FROM grammar_reviews r
                JOIN grammar g ON r.grammar_id = g.id
                WHERE g.deck_id = ?
            """, (deck_id,)).fetchone()

            if not stats:
                return int(min(100, max(0, seen_pct)))

            app = int(stats["app"] or 0)
            ok = int(stats["ok"] or 0)

            if app <= 0:
                return int(min(100, max(0, seen_pct)))

            success_pct = (ok / app) * 100
            blended = (seen_pct * 0.4) + (success_pct * 0.6)
            return int(min(100, max(0, blended)))

    # ----- sentence helpers -----
    def _sentence_total(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "deck_sentence_count"):
            return int(repo.deck_sentence_count(deck_id))
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM sentences WHERE deck_id=?",
                (deck_id,),
            ).fetchone()
            return int(row["c"]) if row else 0

    def _sentence_due(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "sentence_due_count"):
            return int(repo.sentence_due_count(deck_id))
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM sentences s
                JOIN sentence_states st ON st.sentence_id = s.id
                WHERE s.deck_id = ?
                  AND st.due_at <= ?
            """, (deck_id, now)).fetchone()
            return int(row["c"]) if row else 0

    def _sentence_unseen(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "sentence_unseen_count"):
            return int(repo.sentence_unseen_count(deck_id))
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM sentences s
                LEFT JOIN sentence_states st ON st.sentence_id = s.id
                WHERE s.deck_id = ?
                  AND st.id IS NULL
            """, (deck_id,)).fetchone()
            return int(row["c"]) if row else self._sentence_total(deck_id)

    def _sentence_reviews_24h(self, deck_id: int) -> int:
        repo = self.session.repo
        if hasattr(repo, "sentence_reviewed_last_24h"):
            return int(repo.sentence_reviewed_last_24h(deck_id))
        since = int(time.time()) - 24 * 3600
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM sentence_reviews r
                JOIN sentences s ON s.id = r.sentence_id
                WHERE s.deck_id = ?
                  AND r.created_at >= ?
            """, (deck_id, since)).fetchone()
            return int(row["c"]) if row else 0

    def _sentence_reviews_total(self, deck_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS c
                FROM sentence_reviews r
                JOIN sentences s ON s.id = r.sentence_id
                WHERE s.deck_id = ?
            """, (deck_id,)).fetchone()
            return int(row["c"]) if row else 0

    def _calculate_sentence_mastery(self, deck_id: int, total_cards: int) -> int:
        if total_cards <= 0:
            return 0

        with self._conn() as conn:
            reviewed_row = conn.execute("""
                SELECT COUNT(DISTINCT s.id) AS reviewed_count
                FROM sentences s
                JOIN sentence_reviews r ON r.sentence_id = s.id
                WHERE s.deck_id = ?
            """, (deck_id,)).fetchone()
            reviewed_count = int(reviewed_row["reviewed_count"]) if reviewed_row else 0
            seen_pct = (reviewed_count / total_cards) * 100

            stats = conn.execute("""
                SELECT
                    COUNT(*) AS app,
                    SUM(CASE WHEN r.rating >= 2 THEN 1 ELSE 0 END) AS ok
                FROM sentence_reviews r
                JOIN sentences s ON s.id = r.sentence_id
                WHERE s.deck_id = ?
            """, (deck_id,)).fetchone()

            if not stats:
                return int(min(100, max(0, seen_pct)))

            app = int(stats["app"] or 0)
            ok = int(stats["ok"] or 0)

            if app <= 0:
                return int(min(100, max(0, seen_pct)))

            success_pct = (ok / app) * 100
            blended = (seen_pct * 0.4) + (success_pct * 0.6)
            return int(min(100, max(0, blended)))

    # ---------- UI ----------
    def _set_empty(self, msg: str) -> None:
        self.due_card.set_value(0, "")
        self.reviewed_today_card.set_value(0, "")
        self.reviewed_total_card.set_value(0, "")
        self.unseen_card.set_value(0, "")
        self.total_card.set_value(0, "")
        self.mastery_card.set_value(0, "")
        self.performance_label.setText(msg)

    def on_show(self):
        deck_id = None
        if hasattr(self.session, "active_deck_id"):
            deck_id = self.session.active_deck_id()

        self.language_label.setText(
            f"Language: {(getattr(self.session.state, 'language_code', None) or '--').upper()}"
        )
        self.level_label.setText(f"Level: {getattr(self.session.state, 'level', None) or '--'}")
        self.objective_label.setText(f"Objective: {getattr(self.session.state, 'objective', None) or '--'}")

        if not deck_id:
            self._set_empty("No active deck. Select language, level, and objective.")
            return

        obj = self._normalized_objective()
        is_grammar = (obj == "grammar")

        if obj == "sentences":
            total = self._sentence_total(deck_id)
            if total == 0:
                self._set_empty("This deck is empty.")
                return

            total_due = self._sentence_due(deck_id)
            reviewed_today = self._sentence_reviews_24h(deck_id)
            unseen = self._sentence_unseen(deck_id)
            total_reviews = self._sentence_reviews_total(deck_id)
            mastery = self._calculate_sentence_mastery(deck_id, total)

            self.due_card.set_value(total_due, "items waiting")
            self.reviewed_today_card.set_value(reviewed_today, "reviews in 24h")
            self.reviewed_total_card.set_value(total_reviews, "all-time reviews")
            self.unseen_card.set_value(unseen, "new to learn")
            self.total_card.set_value(total, "cards in deck")
            self.mastery_card.set_value(f"{mastery}%", "mastery level")

            learned = total - unseen
            learned_percent = (learned / total) * 100 if total else 0
            due_percent = (total_due / total) * 100 if total else 0
            reviewed_percent = (reviewed_today / total) * 100 if total else 0

            self.performance_label.setText(
                "<p><b>Progress Overview</b></p>"
                f"<p>Learned: <span style='color:#66E39A; font-weight:900;'>{learned_percent:.1f}%</span> ({learned}/{total})</p>"
                f"<p>Due now: <span style='color:#FFD700; font-weight:900;'>{due_percent:.1f}%</span> ({total_due})</p>"
                f"<p>Reviewed (24h): <span style='color:#6B9FFF; font-weight:900;'>{reviewed_percent:.1f}%</span> ({reviewed_today})</p>"
                f"<p>Mastery: <span style='color:#FFFFFF; font-weight:900;'>{mastery}%</span></p>"
            )
            return

        if is_grammar:
            total = self._deck_grammar_count(deck_id)
            if total == 0:
                self._set_empty("This deck is empty.")
                return

            total_due = self._grammar_due_count(deck_id)
            reviewed_today = self._grammar_reviewed_last_24h(deck_id)
            unseen = self._grammar_unseen_count(deck_id)
            total_reviews = self._get_total_grammar_reviews(deck_id)
            mastery = self._calculate_grammar_mastery(deck_id, total)

            self.due_card.set_value(total_due, "items waiting")
            self.reviewed_today_card.set_value(reviewed_today, "reviews in 24h")
            self.reviewed_total_card.set_value(total_reviews, "all-time reviews")
            self.unseen_card.set_value(unseen, "new to learn")
            self.total_card.set_value(total, "cards in deck")
            self.mastery_card.set_value(f"{mastery}%", "mastery level")

            learned = total - unseen
            learned_percent = (learned / total) * 100 if total else 0
            due_percent = (total_due / total) * 100 if total else 0
            reviewed_percent = (reviewed_today / total) * 100 if total else 0

            self.performance_label.setText(
                "<p><b>Progress Overview</b></p>"
                f"<p>Learned: <span style='color:#66E39A; font-weight:900;'>{learned_percent:.1f}%</span> ({learned}/{total})</p>"
                f"<p>Due now: <span style='color:#FFD700; font-weight:900;'>{due_percent:.1f}%</span> ({total_due})</p>"
                f"<p>Reviewed (24h): <span style='color:#6B9FFF; font-weight:900;'>{reviewed_percent:.1f}%</span> ({reviewed_today})</p>"
                f"<p>Mastery: <span style='color:#FFFFFF; font-weight:900;'>{mastery}%</span></p>"
            )
            return

        total = self._deck_vocab_count(deck_id)
        if total == 0:
            self._set_empty("This deck is empty.")
            return

        total_due = self._due_count(deck_id)
        reviewed_today = self._reviewed_last_24h(deck_id)
        unseen = self._unseen_count(deck_id)
        total_reviews = self._get_total_reviews(deck_id)
        mastery = self._calculate_mastery(deck_id, total)

        self.due_card.set_value(total_due, "items waiting")
        self.reviewed_today_card.set_value(reviewed_today, "reviews in 24h")
        self.reviewed_total_card.set_value(total_reviews, "all-time reviews")
        self.unseen_card.set_value(unseen, "new to learn")
        self.total_card.set_value(total, "cards in deck")
        self.mastery_card.set_value(f"{mastery}%", "mastery level")

        learned = total - unseen
        learned_percent = (learned / total) * 100 if total else 0
        due_percent = (total_due / total) * 100 if total else 0
        reviewed_percent = (reviewed_today / total) * 100 if total else 0

        self.performance_label.setText(
            "<p><b>Progress Overview</b></p>"
            f"<p>Learned: <span style='color:#66E39A; font-weight:900;'>{learned_percent:.1f}%</span> ({learned}/{total})</p>"
            f"<p>Due now: <span style='color:#FFD700; font-weight:900;'>{due_percent:.1f}%</span> ({total_due})</p>"
            f"<p>Reviewed (24h): <span style='color:#6B9FFF; font-weight:900;'>{reviewed_percent:.1f}%</span> ({reviewed_today})</p>"
            f"<p>Mastery: <span style='color:#FFFFFF; font-weight:900;'>{mastery}%</span></p>"
        )
