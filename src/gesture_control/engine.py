"""The processing pipeline, independent of any UI.

camera -> tracker -> gesture detector -> activation -> actions

``Engine.process`` handles one frame and returns a ``Snapshot`` for display;
it needs no camera, so it can be tested with synthetic observations.
``Engine.run`` drives it from the webcam until stopped. A front end (the
OpenCV debug window, or the Qt overlay) consumes snapshots and UI events.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .actions import ActionDispatcher, SmoothScroller
from .activation import ActivationController, ActivationState
from .config import AppConfig
from .controllers import DesktopController, create_controller
from .gestures import GestureDetector
from .navigation import Outcome
from .types import Gesture, HandObservation, MotionDiagnostics

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    image: np.ndarray | None
    obs: HandObservation | None
    state: ActivationState
    arming_progress: float
    diag: MotionDiagnostics
    last_action: str
    last_action_time: float
    fps: float
    controller_name: str
    timestamp: float


@dataclass(frozen=True)
class UiEvent:
    """Something the overlay may want to show briefly."""

    gesture: Gesture
    text: str
    acted: bool
    # Screen rectangle (physical pixels) of the control that was activated.
    rect: tuple[int, int, int, int] | None = None


class Engine:
    def __init__(
        self,
        cfg: AppConfig,
        controller: DesktopController,
        navigation=None,
    ):
        self.cfg = cfg
        self.controller = controller
        self.detector = GestureDetector(cfg.gestures)
        self.activation = ActivationController(cfg.activation)
        self.scroller = SmoothScroller(controller, cfg.scroll)
        self.navigation = navigation
        self.dispatcher = ActionDispatcher(controller, cfg.scroll, cfg.navigation, self.scroller, navigation)
        self.events: queue.Queue[UiEvent] = queue.Queue()
        self._prev_state: ActivationState | None = None
        self._last_action = ""
        self._last_action_t = 0.0
        self._fps = 0.0
        self._last_t: float | None = None
        # Set by start(): hardware and OS integrations.
        self._camera = None
        self._tracker = None
        self._hotkey = None

    # ------------------------------------------------------------ construction
    @classmethod
    def create(cls, cfg: AppConfig) -> "Engine":
        if sys.platform == "win32":
            # Physical-pixel coordinates for UIA, screenshots and clicks, also in dry-run.
            from .controllers.windows import enable_dpi_awareness

            enable_dpi_awareness()
        controller = create_controller(cfg.dry_run)
        log.info("Desktop controller: %s", controller.name)
        navigation = None
        if cfg.navigation.mode == "uia":
            from .navigation.service import NavigationService, create_backend_factory

            factory = create_backend_factory(cfg.navigation, controller, cfg.dry_run)
            navigation = NavigationService(cfg.navigation, controller, factory)
        return cls(cfg, controller, navigation)

    def start(self, base_dir: Path) -> "Engine":
        """Open the camera, load the model, register the hotkey, start workers."""
        from .camera import Camera
        from .hotkeys import GlobalHotkey
        from .tracker import HandTracker, ensure_model

        model_path = ensure_model(self.cfg.tracker, base_dir)
        self.scroller.start()
        if self.navigation is not None:
            self.navigation.start()
        self._hotkey = GlobalHotkey(self.cfg.activation.pause_hotkey, self.toggle_pause).start()
        self._tracker = HandTracker(self.cfg.tracker, model_path)
        self._camera = Camera(self.cfg.camera)
        self._camera.start()
        return self

    def close(self) -> None:
        for name, fn in (
            ("camera", lambda: self._camera and self._camera.stop()),
            ("tracker", lambda: self._tracker and self._tracker.close()),
            ("hotkey", lambda: self._hotkey and self._hotkey.stop()),
            ("scroller", self.scroller.stop),
            ("navigation", lambda: self.navigation and self.navigation.stop()),
            ("controller", self.controller.close),
        ):
            try:
                fn()
            except Exception:
                log.exception("Error closing %s", name)

    # ------------------------------------------------------------ control
    def toggle_pause(self) -> bool:
        paused = self.activation.toggle_pause()
        if paused:
            self.scroller.cancel()
        log.info("%s", "PAUSED" if paused else "RESUMED")
        return paused

    @property
    def paused(self) -> bool:
        return self.activation.paused

    def _scroll_target_note(self) -> str:
        """' -> app.exe' for the window under the cursor, which is where wheel input goes."""
        from .targets import pointer_target

        try:
            target = pointer_target()
        except Exception:  # never let diagnostics break scrolling
            log.debug("pointer_target failed", exc_info=True)
            return ""
        if target is None:
            return ""
        if target.problem:
            log.warning("Scroll went to %s", target.describe())
        return f" -> {target.describe()}"

    def _set_action(self, text: str) -> None:
        self._last_action, self._last_action_t = text, time.monotonic()

    # ------------------------------------------------------------ per frame
    def process(self, image: np.ndarray | None, obs: HandObservation | None, t: float) -> Snapshot:
        event = self.detector.update(obs)
        state = self.activation.update(obs, self.detector.speed, t)

        if state is not self._prev_state:
            log.info("State: %s", state.value.upper())
            if state is not ActivationState.ACTIVE:
                self.scroller.cancel()
            self._prev_state = state

        if event is not None:
            details = (
                f"dx={event.dx:+.2f} dy={event.dy:+.2f} palms, "
                f"{event.duration * 1000:.0f} ms, speed={event.speed:.1f}/s"
            )
            if state is ActivationState.ACTIVE:
                try:
                    desc = self.dispatcher.handle(event)
                except Exception:
                    log.exception("Action failed for %s", event.gesture.value)
                    desc = f"{event.gesture.value} FAILED"
                if event.gesture.is_vertical:
                    desc += self._scroll_target_note()
                log.info("%-12s -> %s  (%s)", event.gesture.value, desc, details)
                self._set_action(desc)
                self.events.put(UiEvent(event.gesture, desc, acted=True))
            else:
                log.info("%-12s ignored, state=%s  (%s)", event.gesture.value, state.value, details)
                self._set_action(f"({event.gesture.value} ignored: {state.value})")

        if self.navigation is not None:
            for res in self.navigation.poll():
                log.info("%-12s => %s  (%.0f ms)", res.gesture.value, res.describe(), res.elapsed * 1000)
                self._set_action(res.describe())
                acted = res.attempt.outcome is Outcome.ACTED
                self.events.put(UiEvent(res.gesture, res.describe(), acted, res.attempt.rect if acted else None))

        if self._last_t is not None and t > self._last_t:
            inst = 1.0 / (t - self._last_t)
            self._fps = 0.9 * self._fps + 0.1 * inst if self._fps else inst
        self._last_t = t

        return Snapshot(
            image=image,
            obs=obs,
            state=state,
            arming_progress=self.activation.arming_progress,
            diag=self.detector.diagnostics,
            last_action=self._last_action,
            last_action_time=self._last_action_t,
            fps=self._fps,
            controller_name=self.controller.name,
            timestamp=t,
        )

    def drain_events(self) -> list[UiEvent]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def run(self, stop: threading.Event, on_snapshot: Callable[[Snapshot], bool | None]) -> None:
        """Process webcam frames until ``stop`` is set or ``on_snapshot`` returns False."""
        assert self._camera is not None and self._tracker is not None, "call start() first"
        frame_id = 0
        while not stop.is_set():
            got = self._camera.read(frame_id, timeout=1.0)
            if got is None:
                log.warning("No camera frame for 1 s")
                continue
            frame_id, t, image = got
            obs = self._tracker.process(image, t)
            snap = self.process(image, obs, t)
            if on_snapshot(snap) is False:
                return
