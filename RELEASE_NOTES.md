## MAHIRA 0.3.0

Offline-first German study — this release adds audio to the verb conjugator, fixes a handful of audio bugs across the app, and streamlines the downloads.

### Highlights

- **New — listen to every conjugated form.** Each form in the Verb Conjugation tab now has its own speaker that reads the pronoun together with the form ("ich liebe", "wir haben geliebt"). Completely offline, like the rest of the app.
- **Fixed — the first click sometimes played the wrong clip.** Tapping a word's example (or switching word ↔ example) could briefly play the previous clip on the first press. Playback now always waits for the clip you asked for, so word, example, sentence and listening audio are reliable everywhere.
- **Fixed — listening speed now always matches what you hear.** Changing slow / normal / fast while a passage was still loading could leave the highlighted speed and the actual audio out of sync. The passage is now re-rendered at the speed you selected.
- **Fewer interruptions.** Pronunciation/playback errors no longer pop a dialog for a request you've already moved past, and closing the app while audio is preparing no longer risks a crash on quit.

### Downloads

- **Windows** — run the installer (`MAHIRA-Setup-0.3.0-win64.exe`).
- **macOS (Apple Silicon)** — open the `.dmg` and drag **MAHIRA** to Applications.
  The app is ad-hoc signed, so on first launch macOS may block it. If you see
  **"damaged"** or **"not appropriate for this version of macOS"**, clear the
  download quarantine once from Terminal:

  ```
  xattr -dr com.apple.quarantine /Applications/MAHIRA.app
  ```

  then open it normally. (Right-click → **Open** also works on most setups.)

Everything runs locally — no account, and no internet required after install.
