"""Windows OCR tests: rendered images, and a real window captured from the screen.

Nothing is ever clicked: the navigator runs in dry-run mode.
"""

import sys
import time

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR only")

from gesture_control.config import NavigationConfig  # noqa: E402
from gesture_control.controllers import DryRunController  # noqa: E402
from gesture_control.navigation import Outcome  # noqa: E402
from gesture_control.navigation.candidates import Rect  # noqa: E402
from gesture_control.navigation.scoring import choose_target  # noqa: E402
from gesture_control.navigation.text_chunks import candidates_from_ocr  # noqa: E402
from gesture_control.types import Gesture  # noqa: E402

from win32_window import Win32TestWindow  # noqa: E402


@pytest.fixture(scope="module")
def ocr():
    from gesture_control.navigation.ocr_windows import OcrUnavailable, WindowsOcr

    try:
        return WindowsOcr()
    except OcrUnavailable as exc:
        pytest.skip(str(exc))


def render(items, size=(900, 140), font_size=15):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", font_size)
    for x, y, text in items:
        d.text((x, y), text, fill="black", font=font)
    return np.array(img.convert("RGBA"))[:, :, [2, 1, 0, 3]].copy()  # BGRA


def scan(ocr, img, scale=1.5):
    lines, used = ocr.recognize(img, scale)
    return candidates_from_ocr(lines, scale=used)


def test_pagination_image(ocr):
    img = render([(20, 40, "‹ Previous"), (160, 40, "1    2    3"), (270, 40, "Next ›"),
                  (420, 40, "Read the next chapter of this story")])
    cands = scan(ocr, img)
    win = Rect(0, 0, 900, 140)
    nxt = choose_target(cands, Gesture.NEXT, win)
    prev = choose_target(cands, Gesture.PREVIOUS, win)
    assert nxt.target is not None and nxt.target.candidate.name.lower().startswith("next")
    assert 260 <= nxt.target.candidate.rect.center[0] <= 320
    assert prev.target is not None and "previous" in prev.target.candidate.name.lower()


def test_small_font_needs_upscale(ocr):
    img = render([(20, 40, "Previous"), (200, 40, "Next")], font_size=11)
    cands = scan(ocr, img, scale=2.0)
    assert any(c.name.lower() == "next" for c in cands)


def test_blocked_and_content_text_not_chosen(ocr):
    img = render([(20, 40, "Delete account"), (300, 40, "Next steps for your career")])
    sel = choose_target(scan(ocr, img), Gesture.NEXT, Rect(0, 0, 900, 140))
    assert sel.target is None


def test_ocr_navigator_on_real_window():
    """Capture a real (topmost) Win32 window from the screen and find its Next button."""
    from gesture_control.navigation.ocr_navigator import OcrNavigator

    buttons = [(1, "Previous", True), (2, "Next", True), (3, "Delete", True)]
    with Win32TestWindow(buttons, x=300, y=300, topmost=True) as w:
        time.sleep(0.4)  # let it paint
        nav = OcrNavigator(NavigationConfig(), DryRunController(), dry_run=True)
        res = nav.navigate(Gesture.NEXT, time.monotonic() + 5, hwnd=w.hwnd)
        assert res.outcome is Outcome.ACTED and res.method == "would click", res
        assert "Next" in res.target
        res = nav.navigate(Gesture.PREVIOUS, time.monotonic() + 5, hwnd=w.hwnd)
        assert res.outcome is Outcome.ACTED, res
        assert w.clicked == []  # dry-run: nothing pressed
