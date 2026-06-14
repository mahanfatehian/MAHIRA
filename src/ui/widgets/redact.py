"""Reliable, cross-platform hiding for the 'reveal' answer/tip cards.

QGraphicsBlurEffect is NOT reliable on macOS — on layer-backed native views Qt
silently drops the effect, so a "blurred" answer renders in clear text and the
learner sees it without pressing Reveal. Instead of blurring the pixels, we mask
the glyphs themselves (so the text is genuinely unreadable everywhere) and swap
the real text back in on reveal.
"""
from __future__ import annotations

_DOT = "•"  # bullet


def mask_hidden(text: str | None) -> str:
    """Redact text: every visible glyph becomes a bullet, while spaces and
    newlines are preserved so the masked block keeps a similar shape/footprint
    to the real answer (just like the old blur did) without being readable.
    """
    if not text:
        return ""
    return "".join(ch if ch.isspace() else _DOT for ch in text)
