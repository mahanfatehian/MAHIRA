# 🧠 MAHIRA — Intelligent German Learning App

<p align="center">
  <img src="assets/logo.ico" width="180" alt="MAHIRA logo">
</p>

<p align="center">
  <b>A smart, adaptive spaced‑repetition trainer for learning German, built with PySide6.</b><br>
  Learn faster with an FSRS‑based recall engine and machine‑assisted ranking that
  surface the words, grammar, and sentences you're most likely to forget.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Language-German%20(CEFR)-black">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue">
  <img src="https://img.shields.io/badge/GUI-PySide6-green">
  <img src="https://img.shields.io/badge/Database-SQLite-orange">
  <img src="https://img.shields.io/badge/Scheduler-FSRS%204.5-purple">
</p>

---

# 🇩🇪 German, by design

MAHIRA is a **German‑only** learning app — there is no language‑selection layer.
Content is organised the way real coursebooks are:

```
CEFR Level  →  Book  →  Lektion  →  Objective (vocab · grammar · sentences)
```

You pick a level (A1, A2, …), choose a book, then a Lektion, and practise its
vocabulary, grammar gap‑fills, and sentence building.

### Content is fully folder‑driven (no hardcoding)

Which books exist — and at which levels — is determined **entirely by the
folders on disk**, never by code:

```
data/seeds/
├─ starten_wir/
│  ├─ a1/   1_vocab__Super!__Greetings… .csv, 1_grammar.csv, 1_sentences.csv, …
│  └─ a2/   1_vocab__Damals und heute__Past tense… .csv, …
└─ sicher/
   └─ b1/   1_vocab__… .csv, …
```

- A book shows up under a level **only if it has a folder for that level**. Drop
  in `data/seeds/sicher/b1/…` and *Sicher* appears under B1; *Starten Wir* never
  appears under B1 because it has no `b1/` folder.
- The Lektion's **name and topic live in the filename**
  (`<n>_vocab__<Title>__<Topic>.csv`), so the UI shows real Lektion titles
  without hardcoding them in the database or CSV content.
- Add a new book, level, or Lektion by adding files/folders — **no code change
  required**.

An optional `data/seeds/<book>/manifest.json` can set the display `title`,
sorting `order`, and a book-local `cover` path. Missing or invalid display
metadata never replaces the folder/conventional-cover fallbacks.

Before committing content, run the source/CI authoring command:

```powershell
$env:PYTHONPATH = "src"
python -m mahira validate-seeds data/seeds
```

It checks layout, filenames, headers, required cells, duplicates, noun
article/gender pairs, and manifests without creating learner state. The
installed GUI executable has no console, so use this command from a source
checkout. Runtime imports perform the same validation, calculate a read-only
dry-run plan, make one verified backup when anything changed, and apply the
whole pack transactionally while preserving unambiguous card IDs and history.

Currently shipped: **Menschen A1** and **Starten Wir A1/A2**. Both Starten Wir
levels include complete content for Lektionen 1–12; the engine handles
additional books and levels automatically.

---

# ✨ Features

### 📚 Structured German content
- Vocabulary with article, gender, plural, and meaning
- Grammar gap‑fill drills and sentence‑construction exercises
- Built‑in special‑character keyboard (ä, ö, ü, ß)
- Optional pronunciation audio (Piper TTS)

### 🔁 FSRS adaptive recall engine
- Each item is modelled with **stability + difficulty**, and the engine computes
  **retrievability** — the probability you'd recall it right now — to schedule
  reviews exactly when you're about to forget.
- Failed items re‑enter a short relearning step; correct ones are pushed out to
  the optimal interval for long‑term retention.

### 🧠 Machine‑assisted prioritisation
- An always‑on recall priority surfaces your weakest items from review #1.
- A lightweight online scikit‑learn model **augments** that ranking as it learns
  your personal strengths and weaknesses (it never gates selection).
- Sessions never randomly drop a due/weak item, and guarantee a steady trickle
  of new material.

### 📈 Progress overview
- Clear, focused review flow with a global session tracker and milestones.

### Daily study workspace
- **Today** combines due, unseen, and recurring-error pressure across vocabulary,
  grammar, sentences, and listening, then recommends the lesson needing work.
- **Mistake notebook** identifies repeated lapses and lets learners suspend or
  resume troublesome cards without deleting history.
- **Practice Lab** adds German production (meaning → German) and offline audio
  dictation (audio → German), with actionable language-error feedback.

### Learner-owned and offline-safe
- Versioned, backup-first database migrations preserve FSRS state and reviews.
- Verified backup, export, managed restore, and rotating diagnostic logs.
- Persistent study/audio/accessibility preferences and independent learner profiles.
- Resizable keyboard-friendly UI, high contrast, text scaling, and reduced motion.

---

# ⚙️ Installation (from source)

```bash
# 1) Clone
git clone <repo-url>
cd MAHIRA

# 2) Virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# 3) Dependencies
pip install -r requirements.txt
```

Core stack: **PySide6** (GUI), **SQLite** (storage), **numpy / scikit‑learn /
joblib** (ranking model), and **piper / onnxruntime** (optional TTS). See
[`requirements.txt`](requirements.txt) for the full list.

## 🚀 Running

```bash
cd src
python -m mahira
```

Runtime state is kept outside replaceable application bundles: under the project
`.mahira/` folder from source, `%LOCALAPPDATA%/MAHIRA/.mahira` on Windows, and
`~/Library/Application Support/MAHIRA/.mahira` on macOS. Frozen Linux builds use
`$XDG_DATA_HOME/MAHIRA/.mahira` (or `~/.local/share/MAHIRA/.mahira`). Existing
Windows state is copied forward automatically. See [RELEASING.md](RELEASING.md).

---

# 🧪 Tests

```bash
pip install pytest pytest-timeout
pytest
```

Fast and model-backed tests can also be run separately:

```bash
pytest -m "not slow" --timeout=60
pytest -m slow --timeout=60
```

The suite covers the FSRS scheduler, the recall‑priority ordering, session
selection (highest‑priority items are never dropped + new‑material coverage),
and the folder‑driven seed structure.

---

# 📦 Packaging & releases

MAHIRA ships as a self‑contained desktop app for **Windows 10/11** and
**macOS**, built and published by GitHub Actions. See
[RELEASING.md](RELEASING.md) for the full build and release process.
