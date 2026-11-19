"""Decide which on-screen control (if any) is the Next / Previous button.

Pure logic, no OS calls. The rules are deliberately strict: when in doubt we
return *no target* rather than clicking something that might be wrong.

Name matching
-------------
Accepted (examples for NEXT; PREVIOUS is symmetric):
    "Next"                      100
    "Next page", "Next slide »" 90   (a known noun after the keyword)
    "Go to next page"           85   (a known prefix)
    "›", "»", "→"               70   (arrow-only label)
    "Forward" / "Back"          65   (only if include_back_forward)
    unnamed, id="nextBtn"       60   (only when the control has no name)
Rejected:
    "Next steps for your career", "Previous orders" - keyword followed by an
    unknown word usually means it's a link to content, not navigation.
    Anything containing a blocked word ("delete", "pay", "submit", ...).
    Disabled, off-screen, or zero-size controls.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..types import Gesture
from .candidates import ControlKind, Rect, UICandidate

NEXT_ARROWS = "›»>→❯⟩▸⇒➔➜➡"
PREV_ARROWS = "‹«<←❮⟨◂⇐⬅"
_ARROWS = {Gesture.NEXT: NEXT_ARROWS, Gesture.PREVIOUS: PREV_ARROWS}
_WORDS = {Gesture.NEXT: ("next",), Gesture.PREVIOUS: ("previous", "prev")}
_BACK_FORWARD = {
    Gesture.NEXT: ("forward", "go forward"),
    Gesture.PREVIOUS: ("back", "go back"),
}
NOUNS = (
    "page", "pages", "slide", "chapter", "article", "post", "posts", "image", "photo",
    "picture", "item", "result", "results", "section", "lesson", "episode", "video",
    "story", "entry", "card", "question", "month", "week", "day", "year", "track",
    "song", "comment", "comments", "message", "unit", "part", "screen", "step",
)
PREFIXES = ("go to", "go", "show", "view", "load", "see", "open")

DEFAULT_BLOCKED_WORDS = (
    "delete", "remove", "pay", "buy", "purchase", "order", "checkout", "submit",
    "send", "sign out", "signout", "log out", "logout", "uninstall", "erase",
    "format", "discard", "unsubscribe", "transfer", "confirm", "accept", "agree",
    "install", "reset", "close account",
)

KIND_BONUS = {
    ControlKind.BUTTON: 5,
    ControlKind.SPLIT_BUTTON: 0,
    ControlKind.LINK: 0,
    ControlKind.MENU_ITEM: -10,
    ControlKind.TEXT: -5,
    ControlKind.OTHER: -10,
}
PAIR_BONUS = 8

_STRICT = {
    g: re.compile(
        r"^(?:(?P<prefix>{p})\s+)?(?:the\s+)?(?P<kw>{k})(?:\s+(?P<noun>{n}))?(?:\s+page)?$".format(
            p="|".join(map(re.escape, PREFIXES)),
            k="|".join(_WORDS[g]),
            n="|".join(NOUNS),
        )
    )
    for g in (Gesture.NEXT, Gesture.PREVIOUS)
}
_ID_SPLIT = re.compile(r"[^a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    # Drop decorative punctuation but keep the arrow characters.
    return text.strip(" .:;,!\"'()[]{}|-_")


@dataclass(frozen=True)
class NameMatch:
    score: int
    # Grouping key: two matches with compatible keys point at "the same thing"
    # (e.g. top and bottom pagination both labelled "Next").
    noun: str | None = None
    via: str = "name"


def match_name(
    name: str,
    direction: Gesture,
    include_back_forward: bool = False,
    extra_names: Iterable[str] = (),
) -> NameMatch | None:
    text = normalize(name)
    if not text:
        return None
    if text in {normalize(n) for n in extra_names}:
        return NameMatch(95)

    own, other = _ARROWS[direction], _ARROWS[direction.opposite]
    core = text.strip(own + " ")
    had_arrow = core != text
    if any(ch in other for ch in core):
        return None  # e.g. "< Back" for NEXT, or a combined "‹ Prev | Next ›"
    if not core:
        return NameMatch(70, via="arrow") if had_arrow else None

    m = _STRICT[direction].match(core)
    if m:
        if m.group("prefix"):
            return NameMatch(85, noun=m.group("noun"))
        if m.group("noun"):
            return NameMatch(90, noun=m.group("noun"))
        return NameMatch(100)

    if include_back_forward and core in _BACK_FORWARD[direction]:
        return NameMatch(65, via="back/forward")
    return None


def _id_tokens(text: str) -> set[str]:
    return set(_ID_SPLIT.split(_CAMEL.sub(" ", text or "").lower())) - {""}


# Run-together id tokens such as "pnnext", "nextbtn", "prevarrow" - but not
# "preview" or "context".
_ID_WORD = re.compile(r"^[a-z]{0,3}(next|previous|prev)(btn|button|link|arrow|page|slide|icon)?$")


def _id_directions(tokens: set[str]) -> set[str]:
    found = set()
    for t in tokens:
        m = _ID_WORD.match(t)
        if m:
            found.add("next" if m.group(1) == "next" else "prev")
    return found


def match_identifier(automation_id: str, class_name: str, direction: Gesture) -> NameMatch | None:
    found = _id_directions(_id_tokens(automation_id) | _id_tokens(class_name))
    want = "next" if direction is Gesture.NEXT else "prev"
    if found == {want}:
        return NameMatch(60, via="automation id")
    return None


def is_blocked(name: str, blocked_words: Sequence[str]) -> bool:
    text = normalize(name)
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in blocked_words)


@dataclass(frozen=True)
class Scored:
    candidate: UICandidate
    score: int
    match: NameMatch
    reasons: tuple[str, ...] = ()


@dataclass
class Selection:
    target: Scored | None
    reason: str
    ranked: list[Scored] = field(default_factory=list)
    rejected: list[tuple[UICandidate, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ScoringOptions:
    min_score: int = 60
    ambiguity_margin: int = 15
    include_back_forward: bool = False
    extra_next_names: tuple[str, ...] = ()
    extra_previous_names: tuple[str, ...] = ()
    blocked_words: tuple[str, ...] = DEFAULT_BLOCKED_WORDS


def _match(c: UICandidate, direction: Gesture, opts: ScoringOptions) -> NameMatch | None:
    extra = opts.extra_next_names if direction is Gesture.NEXT else opts.extra_previous_names
    if c.name.strip():
        m = match_name(c.name, direction, opts.include_back_forward, extra)
        if m is None and c.help_text:
            h = match_name(c.help_text, direction, opts.include_back_forward, extra)
            # A tooltip only counts when the visible name is just a symbol.
            if h is not None and not any(ch.isalnum() for ch in c.name):
                m = NameMatch(h.score - 10, h.noun, via="tooltip")
        return m
    if c.help_text:
        h = match_name(c.help_text, direction, opts.include_back_forward, extra)
        if h is not None:
            return NameMatch(h.score - 10, h.noun, via="tooltip")
    return match_identifier(c.automation_id, c.class_name, direction)


def _same_row(a: Rect, b: Rect) -> bool:
    return abs(a.center[1] - b.center[1]) <= max(a.height, b.height) * 1.5


def _compatible(a: NameMatch, b: NameMatch) -> bool:
    return a.noun is None or b.noun is None or a.noun == b.noun


def choose_target(
    candidates: Sequence[UICandidate],
    direction: Gesture,
    window: Rect | None,
    opts: ScoringOptions = ScoringOptions(),
    cursor: tuple[int, int] | None = None,
) -> Selection:
    rejected: list[tuple[UICandidate, str]] = []
    usable: list[UICandidate] = []
    for c in candidates:
        if c.rect.empty:
            rejected.append((c, "zero size"))
        elif c.offscreen:
            rejected.append((c, "off-screen"))
        elif window is not None and not c.rect.intersects(window):
            rejected.append((c, "outside window"))
        elif not c.enabled:
            rejected.append((c, "disabled"))
        elif is_blocked(c.name, opts.blocked_words) or is_blocked(c.help_text, opts.blocked_words):
            rejected.append((c, "blocked word"))
        else:
            usable.append(c)

    opposite = [
        c for c in usable
        if (m := _match(c, direction.opposite, opts)) is not None and m.score >= opts.min_score
    ]

    scored: list[Scored] = []
    for c in usable:
        m = _match(c, direction, opts)
        if m is None:
            continue
        score = m.score + KIND_BONUS[c.kind]
        reasons = [f"{m.via} match {m.score}"]
        if KIND_BONUS[c.kind]:
            reasons.append(f"{c.kind.value} {KIND_BONUS[c.kind]:+d}")
        if any(o is not c and _same_row(o.rect, c.rect) for o in opposite):
            score += PAIR_BONUS
            reasons.append(f"paired with opposite {PAIR_BONUS:+d}")
        scored.append(Scored(c, score, m, tuple(reasons)))

    def dist(s: Scored) -> float:
        if cursor is None:
            return 0.0
        cx, cy = s.candidate.rect.center
        return math.hypot(cx - cursor[0], cy - cursor[1])

    scored.sort(key=lambda s: (-s.score, dist(s)))
    if not scored:
        return Selection(None, "no matching control", [], rejected)

    best = scored[0]
    if best.score < opts.min_score:
        return Selection(None, f"best match {best.candidate.describe()} scored {best.score} < {opts.min_score}", scored, rejected)

    for other in scored[1:]:
        if other.score < best.score - opts.ambiguity_margin:
            break
        if not _compatible(best.match, other.match):
            return Selection(
                None,
                f"ambiguous: {best.candidate.describe()} vs {other.candidate.describe()}",
                scored,
                rejected,
            )

    return Selection(best, "ok", scored, rejected)
