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
- The v0.4.0 codebase passes 162 automated tests.

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
