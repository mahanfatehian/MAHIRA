PRAGMA foreign_keys = ON;

-- =========================
-- Books and Lektions
-- German-only app: there is no language dimension.
-- =========================
CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  UNIQUE(slug)
);

-- A book can span multiple CEFR levels and restart Lektion numbering per level
-- (e.g. Starten Wir A1 L1 and A2 L1 are distinct), so identity is (book, level, number).
CREATE TABLE IF NOT EXISTS lektions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id INTEGER NOT NULL,
  level TEXT NOT NULL DEFAULT 'A1',
  number INTEGER NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
  UNIQUE(book_id, level, number)
);

CREATE INDEX IF NOT EXISTS idx_lektions_book ON lektions(book_id);

-- =========================
-- Decks
-- Deck = (level, lektion, objective)
-- lektion_id NULL = legacy flat-file deck (no book structure)
-- =========================
CREATE TABLE IF NOT EXISTS decks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT NOT NULL,
  lektion_id INTEGER,
  objective TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  seed_file TEXT,
  seed_sha1 TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  FOREIGN KEY(lektion_id) REFERENCES lektions(id) ON DELETE CASCADE
);

-- Expression index so NULL lektion_id is treated as 0 in uniqueness check
CREATE UNIQUE INDEX IF NOT EXISTS idx_decks_unique
ON decks(level, COALESCE(lektion_id, 0), objective);

CREATE INDEX IF NOT EXISTS idx_decks_level
ON decks(level);

-- =========================
-- Vocab
-- =========================
CREATE TABLE IF NOT EXISTS vocab (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deck_id INTEGER NOT NULL,
  pos TEXT NOT NULL DEFAULT 'other',
  word TEXT NOT NULL,
  article TEXT,
  gender TEXT,
  gender_tip TEXT,
  plural TEXT,
  meaning TEXT NOT NULL DEFAULT '',
  notes TEXT,
  tags TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  UNIQUE(deck_id, pos, word, meaning),
  FOREIGN KEY(deck_id) REFERENCES decks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_vocab_deck ON vocab(deck_id);

CREATE TABLE IF NOT EXISTS vocab_examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vocab_id INTEGER NOT NULL,
  de_text TEXT NOT NULL,
  en_text TEXT,
  FOREIGN KEY(vocab_id) REFERENCES vocab(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vocab_states (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vocab_id INTEGER NOT NULL,
  ease REAL NOT NULL DEFAULT 2.5,
  interval_days REAL NOT NULL DEFAULT 0.0,
  reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  due_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  last_review_at INTEGER,
  -- FSRS memory model (NULL until first review; lazily migrated from ease/interval).
  stability REAL,
  difficulty REAL,
  UNIQUE(vocab_id),
  FOREIGN KEY(vocab_id) REFERENCES vocab(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_vocab_states_due
ON vocab_states(due_at);

CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vocab_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  typed_meaning TEXT,
  typed_gender  TEXT,
  typed_plural  TEXT,
  meaning_correct INTEGER,
  gender_correct  INTEGER,
  plural_correct  INTEGER,
  tip_used INTEGER NOT NULL DEFAULT 0,
  gender_tip_used INTEGER NOT NULL DEFAULT 0,
  was_checked INTEGER NOT NULL DEFAULT 0,
  was_skipped INTEGER NOT NULL DEFAULT 0,
  rating INTEGER,
  response_ms INTEGER,
  FOREIGN KEY(vocab_id) REFERENCES vocab(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reviews_vocab ON reviews(vocab_id);
CREATE INDEX IF NOT EXISTS idx_reviews_created ON reviews(created_at);

-- =========================
-- Grammar
-- =========================
CREATE TABLE IF NOT EXISTS grammar (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deck_id INTEGER NOT NULL,
  test_text TEXT NOT NULL,
  answer TEXT NOT NULL,
  test_verb TEXT,
  tip TEXT,
  meaning TEXT,
  grammar_tip TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  UNIQUE(deck_id, test_text, answer),
  FOREIGN KEY(deck_id) REFERENCES decks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_grammar_deck ON grammar(deck_id);

CREATE TABLE IF NOT EXISTS grammar_states (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  grammar_id INTEGER NOT NULL,
  ease REAL NOT NULL DEFAULT 2.5,
  interval_days REAL NOT NULL DEFAULT 0.0,
  reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  due_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  last_review_at INTEGER,
  -- FSRS memory model (NULL until first review; lazily migrated from ease/interval).
  stability REAL,
  difficulty REAL,
  UNIQUE(grammar_id),
  FOREIGN KEY(grammar_id) REFERENCES grammar(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_grammar_states_due
ON grammar_states(due_at);

CREATE TABLE IF NOT EXISTS grammar_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  grammar_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  typed_blank TEXT,
  correct INTEGER,
  meaning_tip_used INTEGER NOT NULL DEFAULT 0,
  hint_used INTEGER NOT NULL DEFAULT 0,
  grammar_tip_used INTEGER NOT NULL DEFAULT 0,
  was_checked INTEGER NOT NULL DEFAULT 0,
  was_skipped INTEGER NOT NULL DEFAULT 0,
  rating INTEGER,
  response_ms INTEGER,
  FOREIGN KEY(grammar_id) REFERENCES grammar(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_grammar_reviews_item ON grammar_reviews(grammar_id);
CREATE INDEX IF NOT EXISTS idx_grammar_reviews_created ON grammar_reviews(created_at);

-- =========================
-- Sentences
-- =========================
CREATE TABLE IF NOT EXISTS sentences (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deck_id INTEGER NOT NULL,
  target_text TEXT NOT NULL,
  translation TEXT,
  tip TEXT,
  words_json TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  UNIQUE(deck_id, target_text),
  FOREIGN KEY(deck_id) REFERENCES decks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sentences_deck ON sentences(deck_id);

CREATE TABLE IF NOT EXISTS sentence_states (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sentence_id INTEGER NOT NULL,
  ease REAL NOT NULL DEFAULT 2.5,
  interval_days REAL NOT NULL DEFAULT 0.0,
  reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  due_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  last_review_at INTEGER,
  -- FSRS memory model (NULL until first review; lazily migrated from ease/interval).
  stability REAL,
  difficulty REAL,
  UNIQUE(sentence_id),
  FOREIGN KEY(sentence_id) REFERENCES sentences(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sentence_states_due
ON sentence_states(due_at);

CREATE TABLE IF NOT EXISTS sentence_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sentence_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  typed_text TEXT,
  correct INTEGER,
  tip_used INTEGER NOT NULL DEFAULT 0,
  translation_used INTEGER NOT NULL DEFAULT 0,
  was_checked INTEGER NOT NULL DEFAULT 0,
  was_skipped INTEGER NOT NULL DEFAULT 0,
  rating INTEGER,
  response_ms INTEGER,
  bank_size INTEGER,
  tokens_used INTEGER,
  mismatch_count INTEGER,
  cap_errors INTEGER,
  punct_errors INTEGER,
  FOREIGN KEY(sentence_id) REFERENCES sentences(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sentence_reviews_item ON sentence_reviews(sentence_id);
CREATE INDEX IF NOT EXISTS idx_sentence_reviews_created ON sentence_reviews(created_at);
