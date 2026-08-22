## MAHIRA 0.6.0

MAHIRA 0.6.0 is a speed and pronunciation release. The app spent a second of
every launch drawing its own splash screen, another waiting for the ranking
model before it would paint, and repainted the entire vocabulary table on every
scroll step. Nouns were also spoken without their article, which is half a
German word. All of that is measured and fixed below.

Your cards, review history, FSRS scheduling state, profiles, settings and
backups carry over untouched. There is no database migration.

### German nouns are spoken with their article

The vocabulary table's speaker read the bare noun, so it gave back "Haus" when
the thing worth hearing is "das Haus". Gender is the hardest part of German
vocabulary and the table already shows it in the next column.

Nouns are now read with their article. Words that take two - `der/die Arme`,
`das/der Event` - are spoken as an alternation, "der oder die Arme", which is
how a German speaker reads the slash. Nouns that take no article, such as the
numbers, are unaffected, and so is every verb, adjective and phrase.

While the article column is hidden for self-quizzing the article is not spoken,
because that would read out the exact answer you are trying to recall. Reveal
the cell and it comes back.

### Faster

Everything below was measured on a real install with a full learner database,
before and after.

- **Startup is about 40% quicker**, from roughly 4.0 s to 2.4 s.
  - The startup banner alone blocked for 1.02 s on every launch, entirely
    inside Qt's splash-screen widget. Replaced with a plain frameless window
    that paints the same picture in 0.2 ms.
  - The first page would not paint until scikit-learn, scipy and numpy had
    finished importing, about 1.1 s. Ranking no longer waits for them; it falls
    back to the deterministic recall priority it is designed to fall back to,
    and the model warms up in the background once the window is on screen.
- **The vocabulary table scrolls properly.** Every scroll step repainted the
  whole viewport - 693 kpx and 14.4 ms per step, 1.4 s to scroll 100 rows. Now
  1.1 kpx and 2.2 ms per step. Moving the pointer over a speaker icon also
  repainted the whole table; that is now limited to the two cells that changed.
  The rendered result is pixel-identical.
- **Saving a setting no longer freezes the app.** Every Save rebuilt the
  application stylesheet and rescaled typography across all 1375 widgets, even
  when the setting had nothing to do with appearance: 627 ms. Now 5 ms, unless
  you actually changed the text size or theme.
- **Opening Setup is 37x cheaper.** A guard meant to skip the level/book/
  Lektion/objective rebuild never held, so the full rebuild ran on every single
  visit: 89.7 ms and 28 database connections each time. Now 2.4 ms when nothing
  has changed, and it still rebuilds when the context or the library does.

### Audio

- **A word that is already prepared plays immediately.** Clicks went through a
  single worker slot, so tapping a cached word while another was still being
  rendered left it waiting seconds behind work it had nothing to do with. That
  is what made the speaker look dead.
- **The pronunciation cache keeps what you waited for.** It documented a
  128 MiB budget but also capped itself at 256 files, and clips average 30 KB -
  so it evicted at about 8 MB, 6% of its own budget, and re-rendered words you
  had already heard. The cache now holds roughly 60 MB.
- **Preparing a word no longer holds up the next one.** Cache housekeeping ran
  inside the lock that guards speech synthesis.

### Known limitation

The first word you play in a session still takes a few seconds while the
offline voice loads. That load holds Python's interpreter lock for about two
seconds, so moving it to a background thread does not help - it only moves the
pause somewhere else, and an earlier attempt in this release did exactly that
before being measured and removed. Fixing it properly means running speech
synthesis outside the app process, which is not a change to rush. Every word
after the first is quick, and repeats are instant.

### Upgrading

Install 0.6.0 over the previous version. Nothing needs migrating.

Because nouns are now cached under their article, the words you have already
heard will be prepared once more the first time you play them. After that they
are instant again.

### Downloads

- **Windows 10/11** - run `MAHIRA-Setup-0.6.0-win64.exe`.
- **macOS (Apple Silicon)** - open `MAHIRA-0.6.0-macos-arm64.dmg` and drag
  **MAHIRA** to Applications.

The macOS app is ad-hoc signed rather than notarized. If Gatekeeper blocks the
first launch, right-click **MAHIRA** and choose **Open**, or run:

```bash
xattr -dr com.apple.quarantine /Applications/MAHIRA.app
```

Everything runs locally after installation; no account or internet connection is
required for study.

**Full changes:** [v0.5.0...v0.6.0](https://github.com/mahanfatehian/MAHIRA/compare/v0.5.0...v0.6.0)
