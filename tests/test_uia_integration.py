"""End-to-end UI Automation test against a real Win32 window (Windows only).

Invoke is exercised for real (it sends BM_CLICK to *our* test window only).
The mouse-click path runs in dry-run mode, so the hit-test is verified
without moving your mouse.
"""

import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation only")

from gesture_control.config import NavigationConfig  # noqa: E402
from gesture_control.controllers import DryRunController  # noqa: E402
from gesture_control.navigation import Outcome  # noqa: E402
from gesture_control.types import Gesture  # noqa: E402

from win32_window import Win32TestWindow  # noqa: E402

PREV_ID, NEXT_ID, DELETE_ID, NEXT_CH_ID = 101, 102, 103, 104


def navigator(**cfg):
    from gesture_control.navigation.uia_windows import UIANavigator

    return UIANavigator(NavigationConfig(**cfg), DryRunController(), dry_run=cfg.pop("_dry", False))


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def window():
    buttons = [(PREV_ID, "‹ Previous", True), (NEXT_ID, "Next ›", True), (DELETE_ID, "Delete", True)]
    with Win32TestWindow(buttons) as w:
        time.sleep(0.2)  # let UIA see the new window
        yield w


def test_finds_candidates(window):
    nav = navigator()
    cands, rect = nav.find_candidates(window.hwnd)
    names = sorted(c.name for c in cands)
    assert names == ["Next ›", "‹ Previous"]  # "Delete" filtered out inside UIA
    assert all(c.invokable and c.enabled and not c.rect.empty for c in cands)
    assert rect.width > 0
    nav.close()


def test_invoke_next_and_previous(window):
    nav = navigator()
    res = nav.navigate(Gesture.NEXT, time.monotonic() + 3, hwnd=window.hwnd)
    assert res.outcome is Outcome.ACTED and res.method == "invoke", res
    assert wait_for(lambda: window.clicked == [NEXT_ID])
    res = nav.navigate(Gesture.PREVIOUS, time.monotonic() + 3, hwnd=window.hwnd)
    assert res.outcome is Outcome.ACTED, res
    assert wait_for(lambda: window.clicked == [NEXT_ID, PREV_ID])
    nav.close()


def test_dry_run_does_not_invoke(window):
    from gesture_control.navigation.uia_windows import UIANavigator

    nav = UIANavigator(NavigationConfig(), DryRunController(), dry_run=True)
    res = nav.navigate(Gesture.NEXT, time.monotonic() + 3, hwnd=window.hwnd)
    assert res.outcome is Outcome.ACTED and res.method == "would invoke"
    time.sleep(0.2)
    assert window.clicked == []
    nav.close()


def test_expired_deadline_does_not_act(window):
    nav = navigator()
    res = nav.navigate(Gesture.NEXT, time.monotonic() - 1, hwnd=window.hwnd)
    assert res.outcome is Outcome.TIMEOUT
    time.sleep(0.2)
    assert window.clicked == []
    nav.close()


def test_disabled_next_is_not_used():
    buttons = [(PREV_ID, "Previous", True), (NEXT_ID, "Next", False)]
    with Win32TestWindow(buttons, x=260, y=260) as w:
        time.sleep(0.2)
        nav = navigator()
        res = nav.navigate(Gesture.NEXT, time.monotonic() + 3, hwnd=w.hwnd)
        assert res.outcome is Outcome.NOT_FOUND
        time.sleep(0.2)
        assert w.clicked == []
        nav.close()


def test_ambiguous_targets_rejected():
    buttons = [(NEXT_CH_ID, "Next chapter", True), (NEXT_ID, "Next page", True)]
    with Win32TestWindow(buttons, x=320, y=320) as w:
        time.sleep(0.2)
        nav = navigator()
        res = nav.navigate(Gesture.NEXT, time.monotonic() + 3, hwnd=w.hwnd)
        assert res.outcome is Outcome.AMBIGUOUS, res
        assert w.clicked == []
        nav.close()


def test_click_path_hit_test_dry_run(window):
    from gesture_control.navigation.uia_windows import UIANavigator

    nav = UIANavigator(NavigationConfig(activation_method="click"), DryRunController(), dry_run=True)
    res = nav.navigate(Gesture.NEXT, time.monotonic() + 3, hwnd=window.hwnd)
    # Either the button is visible ("would click") or another window covers
    # it - in which case the hit-test must refuse rather than click blindly.
    assert res.method == "would click" or "covered" in res.detail, res
    nav.close()
