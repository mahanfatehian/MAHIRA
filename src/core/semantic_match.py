"""Offline semantic answer matching for English vocab meanings.

Replaces the old fuzzy/edit-distance meaning check (which wrongly accepted
"eight" for "eighty") with a real meaning comparison: both the stored gloss and
the learner's answer are embedded with a sentence-embedding model
(all-mpnet-base-v2, int8 ONNX, ~105 MB) and compared by cosine similarity.

Runs fully offline on the CPU via onnxruntime (already shipped for Piper TTS) +
the HuggingFace `tokenizers` lib — no PyTorch. The model lives in
assets/models/all-mpnet-base-v2/ and is bundled with the app.

Model choice: mpnet is the most *discriminating* sentence model in its class —
it keeps wrong answers far from right ones (numbers "eight"/"eighty" ~0.43,
antonyms "buy"/"sell" ~0.69, near-misses "father"/"mother" ~0.69), which is what
this task needs. The trade-off is that it also rates *loose* synonyms low
("happy"/"glad" ~0.35), so those are rejected by design — precision over recall.

Threshold note: MEANING_THRESHOLD is calibrated on this exact int8 model. At
0.70, wrong answers (numbers, antonyms, father/mother) stay below it while strong
synonyms clear it ("to purchase"/"to buy" ~0.80, "to begin"/"to start" ~0.79,
"automobile"/"car" ~0.72). Raise it to be stricter; lower it to accept looser
synonyms (but below ~0.69 you start accepting antonyms like buy/sell). It is the
single knob for tuning meaning matching — and per-item phrasings can also be
listed in the seed glosses for exact-match acceptance.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

# Cosine-similarity cutoff for "same meaning". See module docstring.
MEANING_THRESHOLD = 0.70

_MODEL_SUBPATH = ("assets", "models", "all-mpnet-base-v2")


def _model_dir() -> Path:
    # Lazy import so this module stays usable without the app config loaded.
    from mahira.config import resource_root
    return resource_root().joinpath(*_MODEL_SUBPATH)


class SemanticMatcher:
    """Lazily-loaded, thread-safe embedding matcher with an embedding cache."""

    def __init__(self, model_dir: Path | None = None):
        self._dir = Path(model_dir) if model_dir is not None else None
        self._lock = threading.Lock()
        self._sess = None
        self._tok = None
        self._input_names: set[str] = set()
        self._loaded = False
        self._failed = False
        self._cache: dict[str, np.ndarray] = {}

    # -- loading -------------------------------------------------------------
    def _ensure(self) -> bool:
        if self._loaded:
            return True
        if self._failed:
            return False
        with self._lock:
            if self._loaded:
                return True
            if self._failed:
                return False
            try:
                import onnxruntime as ort
                from tokenizers import Tokenizer

                d = self._dir if self._dir is not None else _model_dir()
                self._tok = Tokenizer.from_file(str(d / "tokenizer.json"))
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.inter_op_num_threads = 1
                self._sess = ort.InferenceSession(
                    str(d / "model.onnx"),
                    sess_options=opts,
                    providers=["CPUExecutionProvider"],
                )
                self._input_names = {i.name for i in self._sess.get_inputs()}
                self._loaded = True
                return True
            except Exception:
                # Missing/corrupt model, missing tokenizers, etc. — degrade to
                # exact-match only rather than crash the review flow.
                self._failed = True
                return False

    def available(self) -> bool:
        return self._ensure()

    # -- embedding -----------------------------------------------------------
    def _embed(self, text: str) -> np.ndarray | None:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        if not self._ensure():
            return None
        enc = self._tok.encode(text)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.array([enc.type_ids], dtype=np.int64)
        out = self._sess.run(None, feed)[0]          # [1, seq, dim]
        m = mask[0][:, None].astype(np.float32)      # [seq, 1]
        vec = (out[0] * m).sum(0) / np.clip(m.sum(0), 1.0, None)  # mean pool
        norm = float(np.linalg.norm(vec))
        vec = (vec / norm) if norm else vec
        vec = vec.astype(np.float32)
        if len(self._cache) < 8192:
            self._cache[text] = vec
        return vec

    def similarity(self, a: str, b: str) -> float:
        ea = self._embed(a)
        eb = self._embed(b)
        if ea is None or eb is None:
            return 0.0
        return float(np.dot(ea, eb))

    # -- public matching -----------------------------------------------------
    def matches(self, answer: str, accepted: list[str],
                threshold: float = MEANING_THRESHOLD) -> bool:
        """True if `answer` means the same as any of the `accepted` glosses.

        Exact (normalized) matches short-circuit; otherwise the best cosine
        similarity must meet `threshold`. If the model can't load, falls back to
        exact-only so the app keeps working.
        """
        a = (answer or "").strip().lower()
        if not a:
            return False
        acc = [(g or "").strip().lower() for g in accepted]
        acc = [g for g in acc if g]
        if not acc:
            return False
        if a in acc:
            return True
        ea = self._embed(a)
        if ea is None:
            return False  # model unavailable -> exact-only
        best = 0.0
        for g in acc:
            eg = self._embed(g)
            if eg is None:
                continue
            s = float(np.dot(ea, eg))
            if s > best:
                best = s
        return best >= threshold


_INSTANCE: SemanticMatcher | None = None


def get_matcher() -> SemanticMatcher:
    """Process-wide singleton (loads the model once, lazily, on first use)."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SemanticMatcher()
    return _INSTANCE
