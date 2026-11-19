import numpy as np

from gesture_control.navigation.candidates import ControlKind, Rect
from gesture_control.navigation.scoring import choose_target
from gesture_control.navigation.text_chunks import OcrWord, candidates_from_ocr, chunk_line
from gesture_control.types import Gesture


def w(text, x, width, y=100, h=12):
    return OcrWord(text, Rect(x, y, x + width, y + h))


def test_chunk_splits_on_wide_gaps():
    # "Previous   1   2   3   Next" with button-like spacing (gaps > 1.2 x 12px)
    line = [w("Previous", 10, 55), w("1", 90, 6), w("2", 120, 6), w("3", 150, 6), w("Next", 185, 30)]
    texts = [t for t, _ in chunk_line(line)]
    assert texts == ["Previous", "1", "2", "3", "Next"]


def test_chunk_keeps_normal_spacing_together():
    line = [w("Next", 10, 30), w("page", 44, 30)]  # 4px gap = a normal space
    assert [t for t, _ in chunk_line(line)] == ["Next page"]


def test_chunk_rect_is_union():
    ((text, rect),) = chunk_line([w("Go", 10, 14), w("to", 27, 12), w("next", 42, 26)])
    assert text == "Go to next" and rect == Rect(10, 100, 68, 112)


def test_chunk_handles_unsorted_and_empty():
    assert chunk_line([]) == []
    assert [t for t, _ in chunk_line([w("page", 44, 30), w("Next", 10, 30)])] == ["Next page"]


def test_candidates_scaled_to_screen_and_filtered():
    lines = [
        [w("Previous", 20, 110, y=40, h=24), w("Next", 300, 60, y=40, h=24)],
        [w("Home", 20, 60, y=200, h=24)],  # irrelevant, dropped
    ]
    cands = candidates_from_ocr(lines, offset=(1000, 500), scale=2.0)
    assert [c.name for c in cands] == ["Previous", "Next"]
    nxt = cands[1]
    assert nxt.kind is ControlKind.TEXT and not nxt.invokable
    assert nxt.rect == Rect(1150, 520, 1180, 532)


def test_prose_line_is_not_a_target():
    line = [w(t, 10 + i * 40, 34) for i, t in enumerate("Read the next chapter of this story".split())]
    cands = candidates_from_ocr([line])
    assert len(cands) == 1  # relevant (contains "next") ...
    sel = choose_target(cands, Gesture.NEXT, Rect(0, 0, 2000, 2000))
    assert sel.target is None  # ... but rejected by the strict label rules


def test_mask_rects():
    import sys

    if sys.platform != "win32":
        return
    from gesture_control.navigation.screen_windows import mask_rects

    img = np.full((100, 200, 4), 255, np.uint8)
    keep = Rect(0, 0, 10, 10)
    n = mask_rects(img, (1000, 1000), [Rect(1050, 1020, 1100, 1040), Rect(0, 0, 10, 10), keep], skip=keep)
    assert n == 1
    assert (img[20:40, 50:100] == 0).all()
    assert (img[0:20] == 255).all()
