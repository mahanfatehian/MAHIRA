"""German verb conjugation: the principal-parts → full-paradigm engine, the
bundled dataset, and the conjugation page rendering.

The engine tests assert exact, hand-verified forms across the tricky cases:
weak, strong (vowel change), separable, modal, the hard-coded core irregular
`sein`, epenthesis (haltet vs wohnt), sibilant pasts and reflexives.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET = REPO_ROOT / "assets" / "data" / "german_verbs.sqlite"


def _conj():
    from core.conjugation import Conjugator
    return Conjugator()


# --------------------------------------------------------------- dataset/asset
def test_asset_present_and_populated():
    assert ASSET.exists(), "bundled conjugation asset is missing"
    import sqlite3
    c = sqlite3.connect(ASSET)
    n = c.execute("SELECT COUNT(*) FROM verb_forms").fetchone()[0]
    c.close()
    assert n > 7000, f"expected ~8000 verbs, found {n}"


def test_normalize_lemma():
    from core.conjugation import normalize_lemma
    assert normalize_lemma("  GEHEN ") == "gehen"
    assert normalize_lemma("sich freuen") == "freuen"
    assert normalize_lemma("Sich  Freuen") == "freuen"
    assert normalize_lemma("") == ""


# ------------------------------------------------------------------- weak verb
def test_weak_verb_machen():
    c = _conj()
    cj = c.conjugate("machen")
    assert cj is not None
    assert cj.praesens == ["mache", "machst", "macht", "machen", "macht", "machen"]
    assert cj.praeteritum == ["machte", "machtest", "machte", "machten", "machtet", "machten"]
    assert cj.perfekt[0] == "habe gemacht"
    assert cj.plusquamperfekt[2] == "hatte gemacht"
    assert cj.futur1[0] == "werde machen"
    assert cj.hilfsverb == "haben"
    assert cj.imperativ == {"du": "mache", "ihr": "macht", "Sie": "machen Sie"}


# ----------------------------------------------------------- strong verb + sein
def test_strong_verb_gehen_uses_sein():
    c = _conj()
    cj = c.conjugate("gehen")
    assert cj.hilfsverb == "sein"
    assert cj.praeteritum == ["ging", "gingst", "ging", "gingen", "gingt", "gingen"]
    assert cj.praesens[4] == "geht"           # ihr — regular
    assert cj.perfekt == [
        "bin gegangen", "bist gegangen", "ist gegangen",
        "sind gegangen", "seid gegangen", "sind gegangen",
    ]
    assert cj.plusquamperfekt[0] == "war gegangen"


def test_vowel_change_only_in_du_er_not_ihr():
    c = _conj()
    cj = c.conjugate("geben")               # e -> i in du/er, NOT in ihr/wir
    assert cj.praesens[1] == "gibst"
    assert cj.praesens[2] == "gibt"
    assert cj.praesens[3] == "geben"        # wir = infinitive
    assert cj.praesens[4] == "gebt"         # ihr = unchanged stem


# -------------------------------------------------------------------- epenthesis
def test_epenthesis_rules():
    c = _conj()
    # stem ends in -t  -> ihr gets -e-
    assert c.conjugate("arbeiten").praesens[4] == "arbeitet"
    assert c.conjugate("arbeiten").praesens[1] == "arbeitest"
    assert c.conjugate("halten").praesens[4] == "haltet"     # strong + epenthesis
    # silent-h verb -> NO epenthesis
    assert c.conjugate("wohnen").praesens[4] == "wohnt"


# ---------------------------------------------------------------- separable verb
def test_separable_verb_aufstehen():
    c = _conj()
    cj = c.conjugate("aufstehen")
    assert cj.separable is True
    assert cj.praesens == ["stehe auf", "stehst auf", "steht auf",
                           "stehen auf", "steht auf", "stehen auf"]
    assert cj.praeteritum[0] == "stand auf"
    assert cj.perfekt[0] == "bin aufgestanden"      # participle stays joined
    assert cj.futur1[0] == "werde aufstehen"        # infinitive joined
    assert cj.imperativ["du"] == "steh auf"
    assert cj.imperativ["Sie"] == "stehen Sie auf"


# ------------------------------------------------------------------- modal verb
def test_modal_has_no_imperative():
    c = _conj()
    cj = c.conjugate("können")
    assert cj.praesens[0] == "kann"
    assert cj.praesens[3] == "können"
    assert cj.imperativ == {}                        # modals have no imperative


# ------------------------------------------------------------ hard-coded core verb
def test_sein_is_complete_even_though_absent_from_dataset():
    c = _conj()
    cj = c.conjugate("sein")
    assert cj is not None, "sein must be served from the hard-coded core verbs"
    assert cj.praesens == ["bin", "bist", "ist", "sind", "seid", "sind"]
    assert cj.praeteritum[0] == "war"
    assert cj.perfekt[0] == "bin gewesen"
    assert cj.konjunktiv2[0] == "wäre"
    assert cj.imperativ["du"] == "sei"


# --------------------------------------------------------------------- reflexive
def test_reflexive_lookup_strips_sich():
    c = _conj()
    cj = c.conjugate("sich freuen")
    assert cj is not None
    assert cj.reflexive is True
    assert cj.infinitive == "freuen"
    assert cj.praesens[0] == "freue"


def test_unknown_verb_returns_none():
    c = _conj()
    assert c.conjugate("zzznotaverb") is None
    assert c.conjugate("") is None


def test_tenses_helper_shape():
    c = _conj()
    cj = c.conjugate("machen")
    rows = cj.tenses()
    assert len(rows) == 6
    for de, en, forms in rows:
        assert isinstance(de, str) and isinstance(en, str)
        assert len(forms) == 6


# ------------------------------------------------------------------------- page
def _qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_page_renders_known_verb_and_handles_unknown():
    _qapp()
    from ui.pages.conjugation import ConjugationPage

    page = ConjugationPage()
    try:
        page.set_verb("gehen", "to go")
        page.on_show()
        # header card + tense grid (+ trailing stretch)
        assert page.host_lay.count() >= 2

        page.set_verb("zzznotaverb", "")
        page.on_show()
        # graceful empty card (+ stretch), no crash
        assert page.host_lay.count() >= 1
    finally:
        page.deleteLater()


def test_page_speakers_read_pronoun_plus_form():
    _qapp()
    from ui.pages.conjugation import ConjugationPage, _Speaker

    page = ConjugationPage()
    try:
        # Capture what each speaker would synthesize, without touching audio.
        spoken = []
        page._play = lambda text, spk: spoken.append(text)

        page.set_verb("lieben", "to love")
        page.on_show()

        speakers = page.findChildren(_Speaker)
        assert len(speakers) >= 36, "a speaker on every conjugated form"
        for spk in speakers:
            spk.click()

        texts = set(spoken)
        # Präsens reads pronoun + form ("er/sie/es" is spoken as "er").
        for expected in ("ich liebe", "du liebst", "er liebt",
                         "wir lieben", "ihr liebt", "sie lieben"):
            assert expected in texts, f"missing spoken form: {expected}"
        # Compound tense keeps the pronoun in front of the whole form.
        assert "ich habe geliebt" in texts
        # Imperativ is spoken as the bare command (no extra pronoun).
        assert "lieben Sie" in texts
    finally:
        page.deleteLater()
