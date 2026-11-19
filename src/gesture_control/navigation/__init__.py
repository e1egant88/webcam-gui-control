"""Screen-aware Next/Previous: find and activate real navigation controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Outcome(str, Enum):
    ACTED = "acted"            # a control was invoked / clicked
    NOT_FOUND = "not_found"    # no acceptable control
    AMBIGUOUS = "ambiguous"    # several different plausible controls
    TIMEOUT = "timeout"        # search exceeded its time budget
    SKIPPED = "skipped"        # nothing sensible to do (e.g. our own window focused)
    ERROR = "error"


@dataclass(frozen=True)
class NavigationAttempt:
    outcome: Outcome
    detail: str
    method: str = ""  # "invoke" | "click" when ACTED
    target: str = ""
    # True when the accessibility search saw nothing usable at all, so a
    # screenshot (OCR) search is worth trying. False when it found controls
    # but deliberately refused them (disabled, blocked, ambiguous).
    visual_fallback_ok: bool = False
