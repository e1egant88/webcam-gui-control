"""Map physical screen pixels (UIA, OCR, SendInput) to Qt logical coordinates.

Gesture Control runs per-monitor DPI aware, so UI Automation rectangles and
click points are physical pixels. Qt positions windows in device-independent
(logical) pixels, and with mixed-DPI monitors the conversion differs per
monitor, so we convert relative to the monitor that contains the rectangle.
Pure logic; the monitor list is supplied by the caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..navigation.candidates import Rect


@dataclass(frozen=True)
class Monitor:
    name: str
    physical: Rect
    # Qt logical geometry of the same screen: x, y, width, height.
    logical: tuple[float, float, float, float]
    dpr: float


def _contains(r: Rect, x: int, y: int) -> bool:
    return r.left <= x < r.right and r.top <= y < r.bottom


def _distance2(r: Rect, x: int, y: int) -> int:
    dx = max(r.left - x, 0, x - r.right)
    dy = max(r.top - y, 0, y - r.bottom)
    return dx * dx + dy * dy


def monitor_for(rect: Rect, monitors: Sequence[Monitor]) -> Monitor | None:
    if not monitors:
        return None
    cx, cy = rect.center
    for m in monitors:
        if _contains(m.physical, cx, cy):
            return m
    return min(monitors, key=lambda m: _distance2(m.physical, cx, cy))


def monitor_at(x: int, y: int, monitors: Sequence[Monitor]) -> Monitor | None:
    """Monitor containing physical point (x, y), or the nearest one."""
    return monitor_for(Rect(x, y, x + 1, y + 1), monitors)


def edge_rects(
    geo: tuple[float, float, float, float], thickness: float
) -> list[tuple[float, float, float, float]]:
    """Four (x, y, w, h) strips forming a frame just inside ``geo``: top, bottom, left, right."""
    x, y, w, h = geo
    t = thickness
    return [
        (x, y, w, t),
        (x, y + h - t, w, t),
        (x, y + t, t, h - 2 * t),
        (x + w - t, y + t, t, h - 2 * t),
    ]


def phys_to_logical(rect: Rect, monitors: Sequence[Monitor]) -> tuple[float, float, float, float] | None:
    """Return (x, y, w, h) in Qt logical coordinates, or None if no monitors."""
    m = monitor_for(rect, monitors)
    if m is None:
        return None
    lx, ly, _, _ = m.logical
    return (
        lx + (rect.left - m.physical.left) / m.dpr,
        ly + (rect.top - m.physical.top) / m.dpr,
        rect.width / m.dpr,
        rect.height / m.dpr,
    )


def match_monitors(
    physical: Sequence[tuple[str, Rect]],
    logical: Sequence[tuple[str, tuple[float, float, float, float], float]],
) -> list[Monitor]:
    """Pair Win32 monitors (device name, physical rect) with Qt screens (name, geometry, dpr).

    Matches by device name (Qt reports e.g. ``\\\\.\\DISPLAY1`` on Windows);
    falls back to left-to-right order when names don't line up.
    """
    by_name = {name: rect for name, rect in physical}
    out = [
        Monitor(name, by_name[name], geo, dpr)
        for name, geo, dpr in logical
        if name in by_name
    ]
    if len(out) == len(logical) and out:
        return out
    if len(physical) != len(logical):
        return out
    phys_sorted = sorted(physical, key=lambda p: (p[1].left, p[1].top))
    log_sorted = sorted(logical, key=lambda q: (q[1][0], q[1][1]))
    return [Monitor(q[0], p[1], q[1], q[2]) for p, q in zip(phys_sorted, log_sorted)]
