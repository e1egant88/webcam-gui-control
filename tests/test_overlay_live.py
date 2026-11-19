"""Live overlay checks on the real Windows desktop.

Shows the HUD and highlight briefly (they are click-through and never take
focus) and verifies the properties the rest of the app relies on:
  * window styles: click-through, no activation, topmost, tool window;
  * hidden from screen capture, and not masked out of OCR screenshots;
  * hit-tests (Win32 and UI Automation) see *through* the overlay;
  * physical -> logical mapping puts the highlight where it should be.
"""

import sys
import time

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop only")
pytest.importorskip("PySide6")

from gesture_control.activation import ActivationState  # noqa: E402
from gesture_control.config import OverlayConfig  # noqa: E402
from gesture_control.engine import Snapshot  # noqa: E402
from gesture_control.types import MotionDiagnostics  # noqa: E402

from win32_window import Win32TestWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from gesture_control.controllers.windows import enable_dpi_awareness
    from PySide6.QtWidgets import QApplication

    enable_dpi_awareness()
    app = QApplication.instance() or QApplication([])
    yield app


def pump(app, seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def snapshot(state=ActivationState.ACTIVE):
    img = np.full((480, 640, 3), 90, np.uint8)
    return Snapshot(img, None, state, 0.4, MotionDiagnostics(), "next: invoke 'Next ›'",
                    time.monotonic(), 30.0, "dry-run", time.monotonic())


@pytest.fixture
def hud(qapp):
    from gesture_control.overlay.widgets import HudWindow

    w = HudWindow(OverlayConfig())
    w.show()
    w.set_snapshot(snapshot())
    pump(qapp)
    yield w
    w.close()
    pump(qapp, 0.1)


def hud_center(hud):
    from gesture_control.navigation.screen_windows import window_rect

    return window_rect(hud.hwnd).center


def test_window_styles(hud):
    from gesture_control.overlay.win_styles import (
        WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, ex_style,
    )

    style = ex_style(hud.hwnd)
    for flag in (WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT):
        assert style & flag, hex(flag)


def test_hidden_from_capture_and_not_masked(hud):
    from gesture_control.navigation.screen_windows import is_excluded_from_capture, own_window_rects, window_rect

    assert hud.capture_excluded and is_excluded_from_capture(hud.hwnd)
    assert window_rect(hud.hwnd) not in own_window_rects()


def test_never_takes_focus(hud):
    from gesture_control.navigation.uia_windows import foreground_window

    assert foreground_window() != hud.hwnd


def test_win32_hit_test_sees_through(hud):
    from gesture_control.navigation.screen_windows import root_window_at

    x, y = hud_center(hud)
    assert root_window_at(x, y) != hud.hwnd


def test_uia_hit_test_sees_through(hud):
    import comtypes.client

    UIA = comtypes.client.GetModule("UIAutomationCore.dll")
    uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    x, y = hud_center(hud)
    el = uia.ElementFromPoint(UIA.tagPOINT(x, y))
    assert el is None or el.CurrentNativeWindowHandle != hud.hwnd
    assert (el.CurrentName if el else "") != "Gesture Control HUD"


def test_capture_shows_window_underneath(qapp, hud):
    """A white window under the HUD must appear white in a screenshot."""
    from gesture_control.navigation.candidates import Rect
    from gesture_control.navigation.screen_windows import capture, window_rect

    hr = window_rect(hud.hwnd)
    with Win32TestWindow([], x=hr.left - 40, y=hr.top - 40, topmost=True) as w:
        pump(qapp, 0.3)
        hud.raise_()
        pump(qapp, 0.3)
        wr = window_rect(w.hwnd)
        # Area covered by both windows (the test window's client is white).
        ov = Rect(max(hr.left, wr.left + 20), max(hr.top, wr.top + 40),
                  min(hr.right, wr.right - 20), min(hr.bottom, wr.bottom - 20))
        assert not ov.empty
        # exclude_own=False: the white test window is ours too and would be
        # masked; here we only want to know that the HUD itself is invisible.
        img = capture(ov, exclude_own=False)
        assert img[:, :, :3].mean() > 200, "HUD pixels leaked into the capture"
        # With masking on, the test window is blacked out but the HUD is not
        # masked either - so the result is black from the test window only.
        assert capture(ov)[:, :, :3].mean() < 5


def test_highlight_lands_on_physical_rect(qapp):
    from gesture_control.navigation.candidates import Rect
    from gesture_control.navigation.screen_windows import window_rect
    from gesture_control.overlay.geometry import phys_to_logical
    from gesture_control.overlay.qt_app import qt_monitors
    from gesture_control.overlay.widgets import HighlightWindow

    target = Rect(400, 300, 520, 340)
    geo = phys_to_logical(target, qt_monitors())
    assert geo is not None
    hl = HighlightWindow()
    hl.show_at(*geo)
    pump(qapp, 0.2)
    got = window_rect(hl.hwnd)
    inflate = HighlightWindow.INFLATE
    # Allow a couple of pixels for DPI rounding.
    assert abs(got.left - (target.left - inflate)) <= 3
    assert abs(got.top - (target.top - inflate)) <= 3
    assert abs(got.width - (target.width + 2 * inflate)) <= 4
    hl.close()


def test_hud_renders_states(qapp, hud):
    for state in ActivationState:
        hud.set_snapshot(snapshot(state))
        img = hud.grab().toImage()
        assert not img.isNull() and img.width() == hud.width()
    assert "ACTIVE" in hud.status_text() or "PAUSED" in hud.status_text()


def test_tray_builds(qapp):
    from gesture_control.overlay.tray import Tray

    calls = []
    tray = Tray(
        hotkey="ctrl+alt+p", on_toggle_pause=lambda: calls.append("p"), on_toggle_hud=lambda v: None,
        on_toggle_camera=lambda v: None, on_open_config=None, on_quit=lambda: None,
        hud_visible=True, camera_visible=True,
    )
    tray.set_state(ActivationState.PAUSED, "")
    assert tray.pause_action.isChecked()
    tray.pause_action.trigger()
    assert calls == ["p"]
