"""Turn OCR words into clickable-label candidates (pure logic, testable).

OCR returns lines of words. A pagination bar can come back as one line
("Previous 1 2 3 Next"), while a real button label is a few words with normal
spacing. We split each line wherever the gap between words is much wider than
a normal space; each piece ("chunk") is one potential button label.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from .candidates import ControlKind, Rect, UICandidate
from .scoring import NEXT_ARROWS, PREV_ARROWS

KEYWORDS = ("next", "prev")
ARROW_CHARS = set(NEXT_ARROWS + PREV_ARROWS)


@dataclass(frozen=True)
class OcrWord:
    text: str
    rect: Rect


def _union(rects: Sequence[Rect]) -> Rect:
    return Rect(
        min(r.left for r in rects), min(r.top for r in rects),
        max(r.right for r in rects), max(r.bottom for r in rects),
    )


def chunk_line(words: Sequence[OcrWord], gap_factor: float = 1.2) -> list[tuple[str, Rect]]:
    """Split one OCR line at gaps wider than ``gap_factor`` x the text height."""
    if not words:
        return []
    words = sorted(words, key=lambda w: w.rect.left)
    height = median(w.rect.height for w in words) or 1
    chunks: list[list[OcrWord]] = [[words[0]]]
    for prev, word in zip(words, words[1:]):
        if word.rect.left - prev.rect.right > gap_factor * height:
            chunks.append([word])
        else:
            chunks[-1].append(word)
    return [(" ".join(w.text for w in c), _union([w.rect for w in c])) for c in chunks]


def _relevant(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in KEYWORDS) or any(ch in ARROW_CHARS for ch in text)


def candidates_from_ocr(
    lines: Sequence[Sequence[OcrWord]],
    offset: tuple[int, int] = (0, 0),
    scale: float = 1.0,
    gap_factor: float = 1.2,
) -> list[UICandidate]:
    """Build candidates in *screen* coordinates.

    ``scale`` is how much the image was enlarged before OCR; ``offset`` is the
    screen position of the image's top-left corner.
    """
    ox, oy = offset
    out = []
    for line in lines:
        for text, r in chunk_line(line, gap_factor):
            if not _relevant(text):
                continue
            rect = Rect(
                ox + int(r.left / scale), oy + int(r.top / scale),
                ox + int(round(r.right / scale)), oy + int(round(r.bottom / scale)),
            )
            out.append(UICandidate(name=text, kind=ControlKind.TEXT, rect=rect, invokable=False))
    return out
