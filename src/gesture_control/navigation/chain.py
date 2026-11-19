"""Try accessibility (UIA) first, then the screenshot/OCR fallback."""

from __future__ import annotations

import logging
import time

from ..types import Gesture
from . import NavigationAttempt, Outcome

log = logging.getLogger(__name__)


class ChainNavigator:
    def __init__(self, primary, visual=None):
        self.primary = primary
        self.visual = visual

    def navigate(self, direction: Gesture, deadline: float) -> NavigationAttempt:
        first = self.primary.navigate(direction, deadline)
        if (
            self.visual is None
            or first.outcome not in (Outcome.NOT_FOUND, Outcome.ERROR)
            or not first.visual_fallback_ok
        ):
            return first
        if time.monotonic() > deadline:
            return NavigationAttempt(Outcome.TIMEOUT, f"UIA: {first.detail}; no time left for OCR")
        log.debug("UIA found nothing (%s); trying OCR", first.detail)
        try:
            second = self.visual.navigate(direction, deadline)
        except Exception as exc:
            log.debug("OCR navigate failed", exc_info=True)
            return NavigationAttempt(Outcome.ERROR, f"UIA: {first.detail}; OCR failed: {exc}")
        if second.outcome is Outcome.ACTED:
            return second
        return NavigationAttempt(second.outcome, f"UIA: {first.detail}; {second.detail}")

    def close(self) -> None:
        for nav in (self.primary, self.visual):
            if nav is not None:
                nav.close()
