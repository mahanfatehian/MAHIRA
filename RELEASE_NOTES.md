## MAHIRA 0.5.0

MAHIRA 0.5.0 is a correctness release for the recall engine. Several parts of
the scheduler were doing something other than what the app described, and one
of the four study lanes was not being scheduled at all. Everything below is
fixed in place: your cards, review history, FSRS scheduling state, profiles and
backups carry over untouched.

Two changes alter what a study day looks like, so they are described in full
before the fix list.

### What changes in your daily plan

**New material keeps flowing when you fall behind.** Each skill's share of the
daily goal used to go to due cards first, and only leftovers reached new ones.
Once your backlog reached the daily goal, new cards dropped to zero and the
course stopped advancing until you cleared it. Each skill now holds back part
of its share for new material. With a heavy backlog and a goal of 30, a plan
that was 30 due and 0 new is now about 22 due and 8 new. Due work still leads,
the goal is still filled exactly, and setting a skill's **New** limit to zero in
**Adjust plan** still pauses new material completely.

**A card you fail comes back before you finish.** FSRS schedules a failed card
ten minutes out precisely so you meet it again in the same sitting. That was
written to the database and never acted on, because the session queue was built
once at the start and only ever shrank. Failed cards now return a few cards
later, capped so a card you keep failing cannot make a session unfinishable.
Sessions with lapses will be slightly longer than before.

### Highlights

- **Listening is scheduled properly.** Listening sessions were selected by a
  random shuffle of the whole deck. The recall priority, the FSRS state the app
  was carefully maintaining, and your daily plan all had no effect on which
  listening cards you saw, and an overdue card could be dropped from a session
  indefinitely. Listening now uses the same ranking as the other three skills,
  in both sessions and the daily plan, and learns from your reviews.
- **Adjust plan can change the daily goal.** The goal is the limit that decides
  how big your plan is, and it lived in Settings while every control in
  **Adjust plan** sat under it. Raising those per-skill limits often changed
  nothing at all. The goal is now in the dialog, with a line telling you which
  of the two limits is currently deciding your plan.
- **Choose your target retention.** How much you aim to remember when a card
  comes back, from 70% to 97%. Raise it before an exam for shorter intervals,
  lower it to trade a little forgetting for fewer reviews.
- **Reviews spread out.** Intervals are nudged within a small window, so a
  lesson learned in one sitting no longer comes due as a single spike months
  later. Existing cards adopt this at their next review. It can be turned off
  under **Review spread**.
- **Set a longest interval.** Cap how far ahead a well-known card can be pushed
  so it stays in rotation instead of disappearing for years. Unlimited by
  default, so nothing moves unless you choose it.
- **New material starts at lesson 1.** Decks are numbered in import order, which
  is alphabetical by filename, so a new learner's first plan opened on Lektion
  10. New cards are now introduced in lesson order.
- **Today stays actionable.** When you hit your goal with work still waiting,
  the page said "more practice remains available" and disabled every button. It
  now tells you how much is left and where to raise the goal. A **Refresh**
  button was also added, which the failure message had been referring to for
  some time.

### Fixes

- The adaptive ranker's weights diverged during training and its output
  collapsed to two values that were slightly worse than random. From your second
  review onward, a quarter of every ranking score was effectively a coin flip.
  Existing model files are retired and retrained from your review history.
- The recall priority saturated: any card past a threshold scored an identical
  maximum, so the most at-risk cards could not be told apart and fell back to
  database order.
- Pressing Space could activate Skip and silently lapse the card you were
  looking at.
- The **Speaking speed** setting only affected Practice Lab. It now applies in
  every lane that plays audio.
- The app failed to start if the offline speech engine was missing or broken,
  even though pronunciation is optional. Study now continues without audio.
- All 2378 listening items ship an authored tip that was never displayed. Tips
  now appear with the transcript when the answer is revealed.
- Settings' **New cards per session** did not affect Today's plan and has been
  renamed **New cards per focused set**, which is what it always controlled.
- Superseded ranker model files were left behind in your data folder on every
  upgrade rather than being cleaned up.
- A build run from source reported a hardcoded version number that went stale,
  so the update check compared against the wrong baseline.

### Upgrading

Install 0.5.0 over the previous version. Cards, review history, FSRS state,
profiles, settings and backups are preserved; there is no database migration in
this release. Your saved daily plan limits are kept as they are.

Two things reset by design: trained ranker models are discarded and rebuild
themselves from your existing review history over the next few sessions, and
interval spreading applies to each card the next time you review it.

### Downloads

- **Windows 10/11** - run `MAHIRA-Setup-0.5.0-win64.exe`.
- **macOS (Apple Silicon)** - open `MAHIRA-0.5.0-macos-arm64.dmg` and drag
  **MAHIRA** to Applications.

The macOS app is ad-hoc signed rather than notarized. If Gatekeeper blocks the
first launch, right-click **MAHIRA** and choose **Open**, or run:

```bash
xattr -dr com.apple.quarantine /Applications/MAHIRA.app
```

Everything runs locally after installation; no account or internet connection is
required for study.

**Full changes:** [v0.4.0...v0.5.0](https://github.com/mahanfatehian/MAHIRA/compare/v0.4.0...v0.5.0)

---

## MAHIRA 0.4.0

MAHIRA 0.4.0 is a major offline-study upgrade. It expands Starten Wir A2 through all 12 lessons, introduces a guided daily workspace, gives learners safer control over their data and review queues, and makes the desktop app faster and easier to read without changing its focused graphite visual style.

### Highlights

- **Starten Wir A2, Lessons 1–12.** Every lesson now includes vocabulary, grammar, sentence-building, and listening material, adding a complete four-lane A2 study path alongside the existing A1 course.
- **A new daily study workspace.** Today combines due cards, unseen material, and recurring mistakes, then recommends the lesson and study lane that need attention. A single **Continue** action starts the suggested work.
- **Mistake Notebook and Practice Lab.** Revisit repeated lapses, suspend or resume troublesome cards without deleting history, practise meaning-to-German production, and use offline audio dictation with actionable language feedback.
- **Profiles, settings, and learner-owned data.** Independent learner profiles, persistent study/audio/accessibility preferences, verified backups, export, managed restore, and rotating diagnostic logs are now available from the app.
- **Safer reviews.** Review submissions are atomic, queue actions preserve learning history, and clearer **New set**, **Check**, and **Skip** controls reduce accidental session restarts.

### Performance and interface improvements

- The scikit-learn ranker now loads only when its persisted model is needed or training begins, keeping the heavy ML stack out of normal startup.
- Vocabulary tables, verb conjugation, and offline audio paths have been optimized for faster interaction.
- Typography scaling now applies consistently across legacy and newer screens, including compact layouts and the 140% accessibility setting.
- Today shows bounded new-card targets instead of overwhelming raw totals.
- The active navigation item has a clearer green current-page indicator and improved accessibility metadata.
- Review actions now have a stronger visual hierarchy while preserving MAHIRA's existing graphite, green, and blue design language.

### Reliability and quality

- Database migrations create and verify backups before changing learner data.
- Existing Windows learner data stored beside older app versions is migrated to the upgrade-safe application data directory.
- Pull requests and changes to `dev` or `main` now run the fast Windows test gate automatically.
- The v0.4.0 codebase passes its automated test suite on every push.

### Upgrading

Install v0.4.0 over the previous version. MAHIRA keeps profiles, settings, FSRS scheduling history, reviews, backups, and ML models outside the replaceable application directory. The first launch may perform a backed-up database migration; do not interrupt it.

### Downloads

- **Windows 10/11** — run `MAHIRA-Setup-0.4.0-win64.exe`.
- **macOS (Apple Silicon)** — open `MAHIRA-0.4.0-macos-arm64.dmg` and drag **MAHIRA** to Applications.

The macOS app is ad-hoc signed rather than notarized. If Gatekeeper blocks the first launch, right-click **MAHIRA** and choose **Open**, or run:

```bash
xattr -dr com.apple.quarantine /Applications/MAHIRA.app
```

Everything runs locally after installation; no account or internet connection is required for study.

**Full changes:** [v0.3.0...v0.4.0](https://github.com/mahanfatehian/MAHIRA/compare/v0.3.0...v0.4.0)
