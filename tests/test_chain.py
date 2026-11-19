import time

from gesture_control.navigation import NavigationAttempt, Outcome
from gesture_control.navigation.chain import ChainNavigator
from gesture_control.types import Gesture


class Fake:
    def __init__(self, attempt=None, exc=None):
        self.attempt, self.exc, self.calls, self.closed = attempt, exc, 0, False

    def navigate(self, direction, deadline):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.attempt

    def close(self):
        self.closed = True


ACTED = NavigationAttempt(Outcome.ACTED, "ok", "invoke", "'Next'")
NOTHING = NavigationAttempt(Outcome.NOT_FOUND, "no matching control", visual_fallback_ok=True)
REFUSED = NavigationAttempt(Outcome.NOT_FOUND, "no matching control", visual_fallback_ok=False)
OCR_HIT = NavigationAttempt(Outcome.ACTED, "OCR", "ocr click", "'Next'")
LATER = time.monotonic() + 10


def test_uia_success_skips_ocr():
    ocr = Fake(OCR_HIT)
    assert ChainNavigator(Fake(ACTED), ocr).navigate(Gesture.NEXT, LATER) is ACTED
    assert ocr.calls == 0


def test_ocr_used_when_uia_saw_nothing():
    assert ChainNavigator(Fake(NOTHING), Fake(OCR_HIT)).navigate(Gesture.NEXT, LATER) is OCR_HIT


def test_ocr_not_used_when_uia_refused_deliberately():
    ocr = Fake(OCR_HIT)
    for first in (REFUSED, NavigationAttempt(Outcome.AMBIGUOUS, "x", visual_fallback_ok=True)):
        assert ChainNavigator(Fake(first), ocr).navigate(Gesture.NEXT, LATER) is first
    assert ocr.calls == 0


def test_ocr_miss_combines_details():
    miss = NavigationAttempt(Outcome.NOT_FOUND, "OCR: no matching control")
    res = ChainNavigator(Fake(NOTHING), Fake(miss)).navigate(Gesture.NEXT, LATER)
    assert res.outcome is Outcome.NOT_FOUND and "UIA:" in res.detail and "OCR:" in res.detail


def test_ocr_exception_is_error():
    res = ChainNavigator(Fake(NOTHING), Fake(exc=OSError("boom"))).navigate(Gesture.NEXT, LATER)
    assert res.outcome is Outcome.ERROR and "boom" in res.detail


def test_no_time_left_for_ocr():
    ocr = Fake(OCR_HIT)
    res = ChainNavigator(Fake(NOTHING), ocr).navigate(Gesture.NEXT, time.monotonic() - 1)
    assert res.outcome is Outcome.TIMEOUT and ocr.calls == 0


def test_without_ocr():
    assert ChainNavigator(Fake(NOTHING), None).navigate(Gesture.NEXT, LATER) is NOTHING


def test_close_closes_both():
    a, b = Fake(ACTED), Fake(OCR_HIT)
    ChainNavigator(a, b).close()
    assert a.closed and b.closed
