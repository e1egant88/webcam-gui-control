"""Screenshot + OCR fallback for windows that UI Automation cannot read.

Only used when UIA saw *nothing* usable (see ``NavigationAttempt.visual_fallback_ok``).
Steps: capture the foreground window from the screen (our own windows masked),
OCR it, split lines into label chunks, score them with the same strict rules
as UIA, then before clicking:
  * re-capture and re-OCR a small area around the target - the label must
    still be there and still mean the same direction;
  * hit-test: the window under the click point must be the target window;
  * the foreground window must not have changed.
OCR cannot see whether a control is enabled, so a greyed-out "Next" may be
clicked; that is harmless in practice.
"""

from __future__ import annotations

import logging
import os
import time

from ..config import NavigationConfig
from ..controllers.base import DesktopController
from ..types import Gesture
from . import NavigationAttempt, Outcome
from .candidates import Rect, UICandidate
from .scoring import ScoringOptions, choose_target, match_name
from .text_chunks import candidates_from_ocr

log = logging.getLogger(__name__)

# Re-validation crop: this many label heights of padding around the target.
REVALIDATE_PAD = 3
# The re-found label centre must be within this many pixels of the original.
REVALIDATE_TOLERANCE = 12


class OcrNavigator:
    def __init__(self, cfg: NavigationConfig, controller: DesktopController, dry_run: bool = False):
        from .ocr_windows import WindowsOcr

        self.cfg = cfg
        self.controller = controller
        self.dry_run = dry_run
        self.ocr = WindowsOcr(cfg.ocr_language)
        self.opts = ScoringOptions(
            min_score=cfg.min_score,
            ambiguity_margin=cfg.ambiguity_margin,
            include_back_forward=cfg.include_back_forward,
            extra_next_names=tuple(cfg.extra_next_names),
            extra_previous_names=tuple(cfg.extra_previous_names),
            blocked_words=tuple(cfg.blocked_words),
        )
        log.info("OCR fallback ready (language %s)", self.ocr.language)

    def _scan(self, region: Rect, keep: Rect | None) -> list[UICandidate]:
        from .screen_windows import capture

        img = capture(region, exclude_own=True, keep=keep)
        lines, scale = self.ocr.recognize(img, self.cfg.ocr_scale)
        return candidates_from_ocr(lines, offset=(region.left, region.top), scale=scale)

    def navigate(self, direction: Gesture, deadline: float, hwnd: int | None = None) -> NavigationAttempt:
        from ..controllers.windows import get_cursor_pos
        from .screen_windows import clip, root_window_at, virtual_screen, window_rect
        from .uia_windows import foreground_window, window_pid

        explicit = hwnd is not None
        hwnd = hwnd if explicit else foreground_window()
        if not hwnd:
            return NavigationAttempt(Outcome.SKIPPED, "no foreground window")
        if not explicit and window_pid(hwnd) == os.getpid():
            return NavigationAttempt(Outcome.SKIPPED, "Gesture Control's own window has focus")

        win = window_rect(hwnd)
        region = clip(win, virtual_screen())
        if region.empty:
            return NavigationAttempt(Outcome.SKIPPED, "window is not on screen")
        # When testing against one of our own windows, don't mask it out.
        keep = win if explicit and window_pid(hwnd) == os.getpid() else None

        t0 = time.monotonic()
        candidates = self._scan(region, keep)
        log.debug("OCR scan: %d candidates in %.0f ms", len(candidates), (time.monotonic() - t0) * 1000)
        if time.monotonic() > deadline:
            return NavigationAttempt(Outcome.TIMEOUT, f"OCR took {(time.monotonic() - t0) * 1000:.0f} ms")

        sel = choose_target(candidates, direction, region, self.opts, cursor=get_cursor_pos())
        for s in sel.ranked[:5]:
            log.debug("  ocr %3d %s [%s]", s.score, s.candidate.describe(), ", ".join(s.reasons))
        if sel.target is None:
            outcome = Outcome.AMBIGUOUS if sel.reason.startswith("ambiguous") else Outcome.NOT_FOUND
            return NavigationAttempt(outcome, f"OCR: {sel.reason}")

        target = sel.target.candidate
        label = f"OCR text {target.describe()} score {sel.target.score}"
        problem = self._revalidate(target, direction, hwnd, explicit, keep)
        if problem:
            return NavigationAttempt(Outcome.NOT_FOUND, f"{label}: {problem}")
        if time.monotonic() > deadline:
            return NavigationAttempt(Outcome.TIMEOUT, "deadline passed before acting")

        x, y = target.rect.center
        if root_window_at(x, y) != hwnd:
            return NavigationAttempt(Outcome.NOT_FOUND, f"{label} is covered by another window")
        if self.dry_run:
            return NavigationAttempt(Outcome.ACTED, label, "would click", target.describe())
        self.controller.click(x, y, restore_cursor=self.cfg.restore_cursor)
        return NavigationAttempt(Outcome.ACTED, label, "ocr click", target.describe())

    def _revalidate(self, c: UICandidate, direction: Gesture, hwnd: int, explicit: bool, keep) -> str:
        from .screen_windows import clip, virtual_screen
        from .uia_windows import foreground_window

        if not explicit and foreground_window() != hwnd:
            return "foreground window changed"
        pad = max(c.rect.height, 8) * REVALIDATE_PAD
        region = clip(
            Rect(c.rect.left - pad, c.rect.top - pad, c.rect.right + pad, c.rect.bottom + pad),
            virtual_screen(),
        )
        cx, cy = c.rect.center
        for again in self._scan(region, keep):
            m = match_name(again.name, direction, self.cfg.include_back_forward)
            ax, ay = again.rect.center
            if m is not None and abs(ax - cx) <= REVALIDATE_TOLERANCE and abs(ay - cy) <= REVALIDATE_TOLERANCE:
                return ""
        return "label not found again when re-checking"

    def close(self) -> None:
        pass
