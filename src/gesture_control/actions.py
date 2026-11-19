"""Map gesture events to desktop actions; animate scrolling smoothly."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import NavigationConfig, ScrollConfig
from .controllers import DesktopController, parse_combo
from .controllers.base import WHEEL_DELTA
from .types import Gesture, GestureEvent

if TYPE_CHECKING:
    from .navigation.service import NavigationService

log = logging.getLogger(__name__)

HIGH_RES_GRANULARITY = 10  # wheel units per emitted chunk in high-res mode
TICK_S = 1 / 120


def ease_out_cubic(p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


@dataclass
class _Animation:
    start: float
    total: int
    done: float = 0.0  # eased amount already accounted for


class SmoothScroller:
    """Spreads each scroll request over ``duration_s`` with an ease-out curve.

    Overlapping requests are summed, so quick repeated swipes accelerate
    naturally instead of queueing up. ``step(now)`` is the testable core; the
    background thread just calls it at ~120 Hz.
    """

    def __init__(self, controller: DesktopController, cfg: ScrollConfig):
        self.controller = controller
        self.cfg = cfg
        self.granularity = HIGH_RES_GRANULARITY if cfg.high_resolution else WHEEL_DELTA
        self._lock = threading.Lock()
        self._anims: list[_Animation] = []
        self._residual = 0.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def submit(self, wheel_delta: int, now: float | None = None) -> None:
        wheel_delta = int(round(wheel_delta / self.granularity)) * self.granularity
        if wheel_delta == 0:
            return
        if not self.cfg.smooth or self.cfg.duration_s <= 0:
            self.controller.scroll(wheel_delta)
            return
        with self._lock:
            self._anims.append(_Animation(time.monotonic() if now is None else now, wheel_delta))
        self._wake.set()

    def cancel(self) -> None:
        with self._lock:
            self._anims.clear()
            self._residual = 0.0

    @property
    def busy(self) -> bool:
        with self._lock:
            return bool(self._anims)

    def step(self, now: float) -> int:
        """Advance all animations to ``now``; send and return the wheel delta."""
        dur = self.cfg.duration_s
        with self._lock:
            pending = self._residual
            still_running = []
            for anim in self._anims:
                target = ease_out_cubic((now - anim.start) / dur)
                pending += (target - anim.done) * anim.total
                anim.done = target
                if target < 1.0:
                    still_running.append(anim)
            self._anims = still_running
            g = self.granularity
            # Truncate towards zero to whole chunks; carry the remainder.
            chunks = int(pending / g)
            out = chunks * g
            self._residual = pending - out
            if not self._anims:
                # Animation finished: flush any rounding leftovers.
                leftover = int(round(self._residual / g)) * g
                out += leftover
                self._residual = 0.0
        if out:
            self.controller.scroll(out)
        return out

    def start(self) -> "SmoothScroller":
        self._thread = threading.Thread(target=self._run, name="scroller", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.busy:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue
            try:
                self.step(time.monotonic())
            except Exception:  # never let the input thread die silently
                log.exception("Scroll step failed")
                self.cancel()
            time.sleep(TICK_S)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


class ActionDispatcher:
    def __init__(
        self,
        controller: DesktopController,
        scroll_cfg: ScrollConfig,
        nav_cfg: NavigationConfig,
        scroller: SmoothScroller,
        navigation: "NavigationService | None" = None,
    ):
        self.controller = controller
        self.scroll_cfg = scroll_cfg
        self.nav_cfg = nav_cfg
        self.scroller = scroller
        self.navigation = navigation
        if nav_cfg.mode == "uia" and navigation is None:
            raise ValueError("navigation.mode = 'uia' needs a NavigationService")
        # Validate key combos at startup, not at the first swipe.
        self._combos = {
            Gesture.NEXT: [parse_combo(c) for c in nav_cfg.next_keys],
            Gesture.PREVIOUS: [parse_combo(c) for c in nav_cfg.previous_keys],
        }

    def scroll_amount(self, event: GestureEvent) -> int:
        mult = min(max(event.strength, 1.0), self.scroll_cfg.max_speed_multiplier)
        amount = int(round(self.scroll_cfg.notches_per_swipe * WHEEL_DELTA * mult))
        # Wheel convention: positive scrolls up.
        return amount if event.gesture is Gesture.SCROLL_UP else -amount

    def handle(self, event: GestureEvent) -> str:
        """Perform the action for ``event``; return a short description."""
        if event.gesture.is_vertical:
            amount = self.scroll_amount(event)
            self.scroller.submit(amount)
            return f"scroll {amount / WHEEL_DELTA:+.1f} notches"

        if self.nav_cfg.mode == "none":
            return f"{event.gesture.value} (navigation disabled)"
        if self.nav_cfg.mode == "uia":
            assert self.navigation is not None
            if self.navigation.request(event.gesture):
                return f"{event.gesture.value}: searching UI..."
            return f"{event.gesture.value}: ignored, previous search still running"
        combos = self._combos[event.gesture]
        for combo in combos:
            self.controller.press_combo(combo)
        return f"{event.gesture.value}: " + ", ".join("+".join(c) for c in combos)
