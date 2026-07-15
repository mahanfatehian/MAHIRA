from __future__ import annotations

"""
German verb conjugation — full paradigm from a bundled, Wiktionary-derived
dataset of principal parts.

The shipped asset (assets/data/german_verbs.sqlite, ~8000 verbs) stores the
*principal parts* of each verb: present ich/du/er (which carry every stem
change), Präteritum, Partizip II, Konjunktiv II, the two imperatives and the
auxiliary. Those are exactly the forms you cannot derive by rule. From them the
remaining persons of each tense ARE regular, so we expand the principal parts
into a complete six-person paradigm deterministically — no model, no network,
100% reproducible.

The three deeply irregular core verbs (sein/haben/werden) are hard-coded in
full; they double as the auxiliaries for the compound tenses.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Display order of the six grammatical persons.
PERSONS = ("ich", "du", "er/sie/es", "wir", "ihr", "sie/Sie")

# Tense key -> (German label, English gloss). Order = display order.
TENSE_LABELS = [
    ("praesens", "Präsens", "Present"),
    ("praeteritum", "Präteritum", "Simple past"),
    ("perfekt", "Perfekt", "Present perfect"),
    ("plusquamperfekt", "Plusquamperfekt", "Past perfect"),
    ("futur1", "Futur I", "Future"),
    ("konjunktiv2", "Konjunktiv II", "Subjunctive II"),
]

_VOWELS = "aeiouäöü"

# Full six-person present / Präteritum / Konjunktiv II of the three core verbs.
# These power the compound tenses AND are served directly when one of them is
# the verb being looked up (sein in particular is absent from the dataset).
_AUX = {
    "haben": {
        "praesens": ["habe", "hast", "hat", "haben", "habt", "haben"],
        "praeteritum": ["hatte", "hattest", "hatte", "hatten", "hattet", "hatten"],
        "konjunktiv2": ["hätte", "hättest", "hätte", "hätten", "hättet", "hätten"],
        "partizip2": "gehabt",
        "hilfsverb": "haben",
        "imperativ": {"du": "hab", "ihr": "habt", "Sie": "haben Sie"},
    },
    "sein": {
        "praesens": ["bin", "bist", "ist", "sind", "seid", "sind"],
        "praeteritum": ["war", "warst", "war", "waren", "wart", "waren"],
        "konjunktiv2": ["wäre", "wärest", "wäre", "wären", "wäret", "wären"],
        "partizip2": "gewesen",
        "hilfsverb": "sein",
        "imperativ": {"du": "sei", "ihr": "seid", "Sie": "seien Sie"},
    },
    "werden": {
        "praesens": ["werde", "wirst", "wird", "werden", "werdet", "werden"],
        "praeteritum": ["wurde", "wurdest", "wurde", "wurden", "wurdet", "wurden"],
        "konjunktiv2": ["würde", "würdest", "würde", "würden", "würdet", "würden"],
        "partizip2": "geworden",
        "hilfsverb": "sein",
        "imperativ": {"du": "werde", "ihr": "werdet", "Sie": "werden Sie"},
    },
}


@dataclass(frozen=True)
class PrincipalParts:
    infinitive: str
    praesens_ich: str
    praesens_du: str
    praesens_er: str
    praeteritum_ich: str
    partizip2: str
    konjunktiv2_ich: str
    imperativ_sg: str
    imperativ_pl: str
    hilfsverb: str


@dataclass
class Conjugation:
    infinitive: str
    hilfsverb: str
    partizip2: str
    separable: bool
    reflexive: bool
    praesens: list           # 6 forms
    praeteritum: list        # 6 forms
    perfekt: list            # 6 forms
    plusquamperfekt: list    # 6 forms
    futur1: list             # 6 forms
    konjunktiv2: list        # 6 forms
    imperativ: dict          # {"du":..., "ihr":..., "Sie":...}

    def tenses(self) -> list:
        """[(german_label, english_gloss, [6 person forms]), ...] in display order."""
        m = {
            "praesens": self.praesens,
            "praeteritum": self.praeteritum,
            "perfekt": self.perfekt,
            "plusquamperfekt": self.plusquamperfekt,
            "futur1": self.futur1,
            "konjunktiv2": self.konjunktiv2,
        }
        return [(de, en, m[key]) for key, de, en in TENSE_LABELS]


# --------------------------------------------------------------------- helpers
def normalize_lemma(verb: str) -> str:
    """Lower-case, trim, drop a leading reflexive 'sich ', collapse spaces."""
    v = (verb or "").strip().lower()
    v = " ".join(v.split())
    if v.startswith("sich "):
        v = v[5:].strip()
    return v


def _split_prefix(form: str) -> tuple:
    """A separable present form like 'stehe auf' -> ('stehe', 'auf'); a plain
    form -> ('gehe', '')."""
    form = (form or "").strip()
    if " " in form:
        base, prefix = form.rsplit(" ", 1)
        return base.strip(), prefix.strip()
    return form, ""


def _present_stem(infinitive: str) -> str:
    if infinitive.endswith("en"):
        return infinitive[:-2]
    if infinitive.endswith("n"):
        return infinitive[:-1]
    return infinitive


def _needs_e(stem: str) -> bool:
    """Whether a stem takes an epenthetic -e- before -t/-st (arbeitet, öffnet,
    rechnet) — but not the silent-h verbs (wohnt) or l/r/m/n clusters (lernt)."""
    if stem.endswith(("d", "t")):
        return True
    if stem and stem[-1] in ("m", "n"):
        prev = stem[-2] if len(stem) >= 2 else ""
        if prev in "lrmn" or prev in _VOWELS:
            return False
        if prev == "h":
            # -hn: 'rechnen' (consonant before h) takes -e-, 'wohnen' (vowel) not.
            prev2 = stem[-3] if len(stem) >= 3 else ""
            return prev2 not in _VOWELS
        return True
    return False


def _ihr_present(infinitive_stem: str) -> str:
    return infinitive_stem + ("et" if _needs_e(infinitive_stem) else "t")


def _aux_conjugation(name: str, reflexive: bool = False) -> Conjugation:
    a = _AUX[name]
    pres, prat, k2 = a["praesens"], a["praeteritum"], a["konjunktiv2"]
    p2, aux = a["partizip2"], a["hilfsverb"]
    aux_pres = _AUX[aux]["praesens"]
    aux_prat = _AUX[aux]["praeteritum"]
    werden_pres = _AUX["werden"]["praesens"]
    return Conjugation(
        infinitive=name,
        hilfsverb=aux,
        partizip2=p2,
        separable=False,
        reflexive=reflexive,
        praesens=list(pres),
        praeteritum=list(prat),
        perfekt=[f"{aux_pres[i]} {p2}" for i in range(6)],
        plusquamperfekt=[f"{aux_prat[i]} {p2}" for i in range(6)],
        futur1=[f"{werden_pres[i]} {name}" for i in range(6)],
        konjunktiv2=list(k2),
        imperativ=dict(a["imperativ"]),
    )


def _expand(p: PrincipalParts, reflexive: bool = False) -> Conjugation:
    """Expand principal parts into a full six-person paradigm."""
    inf = p.infinitive

    # Separable prefix is visible as the trailing token of the present forms.
    _, prefix = _split_prefix(p.praesens_ich)
    separable = bool(prefix) and inf.startswith(prefix) and inf != prefix
    base_inf = inf[len(prefix):] if separable else inf
    tail = f" {prefix}" if separable else ""
    stem = _present_stem(base_inf)

    # ---- Präsens: ich/du/er from data (carry stem changes); wir/sie = the
    # infinitive; ihr from the *unchanged* stem (strong verbs don't shift here).
    praesens = [
        p.praesens_ich,
        p.praesens_du,
        p.praesens_er,
        base_inf + tail,
        _ihr_present(stem) + tail,
        base_inf + tail,
    ]

    # ---- Präteritum from the given 1st-person form. (Blank when the dataset
    # has no past stem — a handful of rare/dialectal entries — so we never emit
    # a garbage ending attached to nothing.)
    pbase, _ = _split_prefix(p.praeteritum_ich)
    if not pbase or any(ch in pbase for ch in "<>()[]"):
        # Empty, or a rare/dialectal row whose stem is stored as literal markup
        # (e.g. "<small>(derkam)</small>"): emit blanks rather than gluing person
        # endings onto HTML.
        praeteritum = [""] * 6
    else:
        if pbase.endswith("te"):  # weak
            prat = [pbase, pbase + "st", pbase, pbase + "n", pbase + "t", pbase + "n"]
        else:  # strong
            du = pbase + ("est" if pbase.endswith(("s", "ß", "z", "x", "d", "t")) else "st")
            ihr = pbase + ("et" if pbase.endswith(("d", "t")) else "t")
            prat = [pbase, du, pbase, pbase + "en", ihr, pbase + "en"]
        praeteritum = [f + tail for f in prat]

    # ---- Konjunktiv II from the given 1st-person form (it ends in -e).
    kbase, _ = _split_prefix(p.konjunktiv2_ich)
    if not kbase or any(ch in kbase for ch in "<>()[]"):
        # Same markup guard as Präteritum above.
        konjunktiv2 = [""] * 6
    else:
        if kbase.endswith("e"):
            konj = [kbase, kbase + "st", kbase, kbase + "n", kbase + "t", kbase + "n"]
        else:
            du = kbase + ("est" if kbase.endswith(("s", "ß", "z", "x", "d", "t")) else "st")
            ihr = kbase + ("et" if kbase.endswith(("d", "t")) else "t")
            konj = [kbase, du, kbase, kbase + "en", ihr, kbase + "en"]
        konjunktiv2 = [f + tail for f in konj]

    # ---- Compound tenses: hard-coded auxiliary paradigms + this verb's forms.
    aux = (p.hilfsverb or "haben").strip().lower()
    if aux not in ("haben", "sein"):
        aux = "haben"
    aux_pres = _AUX[aux]["praesens"]
    aux_prat = _AUX[aux]["praeteritum"]
    werden_pres = _AUX["werden"]["praesens"]
    if p.partizip2:
        perfekt = [f"{aux_pres[i]} {p.partizip2}" for i in range(6)]
        plusquamperfekt = [f"{aux_prat[i]} {p.partizip2}" for i in range(6)]
    else:
        perfekt = [""] * 6
        plusquamperfekt = [""] * 6
    futur1 = [f"{werden_pres[i]} {inf}" for i in range(6)]

    # ---- Imperativ: du/ihr from data; the Sie form is the inverted infinitive.
    imp = {}
    if p.imperativ_sg:
        imp["du"] = p.imperativ_sg
    if p.imperativ_pl:
        imp["ihr"] = p.imperativ_pl
    if imp:  # only offer a Sie form where an imperative exists at all
        imp["Sie"] = (f"{base_inf} Sie {prefix}".strip() if separable else f"{inf} Sie")

    return Conjugation(
        infinitive=inf,
        hilfsverb=aux,
        partizip2=p.partizip2,
        separable=separable,
        reflexive=reflexive,
        praesens=praesens,
        praeteritum=praeteritum,
        perfekt=perfekt,
        plusquamperfekt=plusquamperfekt,
        futur1=futur1,
        konjunktiv2=konjunktiv2,
        imperativ=imp,
    )


def _default_db_path() -> Path:
    try:
        from mahira.config import resource_root
        return resource_root() / "assets" / "data" / "german_verbs.sqlite"
    except Exception:
        return Path(__file__).resolve().parents[2] / "assets" / "data" / "german_verbs.sqlite"


class Conjugator:
    """Looks up principal parts in the bundled asset and expands them.

    Cheap to construct; the read-only SQLite connection is opened lazily on the
    first lookup and reused. Always degrades gracefully (returns None) instead
    of raising, so a missing/locked asset never breaks the UI."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._tried = False

    def _connect(self) -> Optional[sqlite3.Connection]:
        if self._conn is not None or self._tried:
            return self._conn
        self._tried = True
        try:
            if not self._db_path.exists():
                return None
            uri = f"file:{self._db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._conn = conn
        except Exception:
            self._conn = None
        return self._conn

    def available(self) -> bool:
        return self._connect() is not None

    def principal_parts(self, lemma: str) -> Optional[PrincipalParts]:
        conn = self._connect()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM verb_forms WHERE infinitive = ?", (lemma,)
            ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        return PrincipalParts(
            infinitive=row["infinitive"],
            praesens_ich=row["praesens_ich"] or "",
            praesens_du=row["praesens_du"] or "",
            praesens_er=row["praesens_er"] or "",
            praeteritum_ich=row["praeteritum_ich"] or "",
            partizip2=row["partizip2"] or "",
            konjunktiv2_ich=row["konjunktiv2_ich"] or "",
            imperativ_sg=row["imperativ_sg"] or "",
            imperativ_pl=row["imperativ_pl"] or "",
            hilfsverb=row["hilfsverb"] or "haben",
        )

    def conjugate(self, verb: str) -> Optional[Conjugation]:
        """Full paradigm for a verb (accepts 'sich …' and any casing), or None
        when the verb isn't in the dataset."""
        raw = (verb or "").strip().lower()
        reflexive = raw.startswith("sich ")
        lemma = normalize_lemma(verb)
        if not lemma:
            return None
        # The three core verbs are fully hard-coded (and sein isn't in the data).
        if lemma in _AUX:
            return _aux_conjugation(lemma, reflexive=reflexive)
        parts = self.principal_parts(lemma)
        if parts is None:
            return None
        return _expand(parts, reflexive=reflexive)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "Conjugator":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def __del__(self) -> None:
        # Python 3.13+ reports an unclosed sqlite3.Connection as a
        # ResourceWarning. Keep this destructor tiny and exception-safe so a
        # short-lived lookup helper and interpreter shutdown both release the
        # read-only bundled database cleanly.
        try:
            self.close()
        except Exception:
            pass
