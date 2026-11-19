"""Main loop: camera -> tracker -> gesture detector -> activation -> actions."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .actions import ActionDispatcher, SmoothScroller
from .activation import ActivationController, ActivationState
from .camera import Camera
from .config import AppConfig
from .controllers import create_controller
from .gestures import GestureDetector
from .hotkeys import GlobalHotkey
from .navigation.service import NavigationService, create_backend_factory
from .tracker import HandTracker, ensure_model

log = logging.getLogger(__name__)


class App:
    def __init__(self, cfg: AppConfig, base_dir: Path):
        self.cfg = cfg
        self.base_dir = base_dir

    def run(self) -> int:
        cfg = self.cfg
        model_path = ensure_model(cfg.tracker, self.base_dir)
        controller = create_controller(cfg.dry_run)
        log.info("Desktop controller: %s", controller.name)

        detector = GestureDetector(cfg.gestures)
        activation = ActivationController(cfg.activation)
        scroller = SmoothScroller(controller, cfg.scroll).start()
        navigation = None
        if cfg.navigation.mode == "uia":
            factory = create_backend_factory(cfg.navigation, controller, cfg.dry_run)
            navigation = NavigationService(cfg.navigation, controller, factory).start()
        dispatcher = ActionDispatcher(controller, cfg.scroll, cfg.navigation, scroller, navigation)

        def on_hotkey() -> None:
            paused = activation.toggle_pause()
            if paused:
                scroller.cancel()
            log.info("Hotkey: %s", "PAUSED" if paused else "RESUMED")

        hotkey = GlobalHotkey(cfg.activation.pause_hotkey, on_hotkey).start()
        tracker = HandTracker(cfg.tracker, model_path)
        camera = Camera(cfg.camera)
        view = None
        try:
            camera.start()
            if cfg.debug.show_window:
                from .debug_view import DebugView

                view = DebugView(cfg)
            else:
                log.info("Running headless. Press Ctrl+C to quit.")
            self._loop(camera, tracker, detector, activation, dispatcher, scroller, view)
        except KeyboardInterrupt:
            log.info("Interrupted")
        finally:
            camera.stop()
            tracker.close()
            hotkey.stop()
            scroller.stop()
            if navigation is not None:
                navigation.stop()
            controller.close()
            if view is not None:
                view.close()
        return 0

    def _loop(self, camera, tracker, detector, activation, dispatcher, scroller, view) -> None:
        from .debug_view import Frame  # cheap; only drawing needs the window

        frame_id = 0
        fps = 0.0
        last_t = None
        last_action, last_action_t = "", 0.0
        prev_state: ActivationState | None = None

        while True:
            got = camera.read(frame_id, timeout=2.0)
            if got is None:
                log.warning("No camera frame for 2 s")
                if view is not None and view.window_closed():
                    return
                continue
            frame_id, t, image = got

            obs = tracker.process(image, t)
            event = detector.update(obs)
            state = activation.update(obs, detector.speed, t)

            if state is not prev_state:
                log.info("State: %s", state.value.upper())
                if state is not ActivationState.ACTIVE:
                    scroller.cancel()
                prev_state = state

            if event is not None:
                details = (
                    f"dx={event.dx:+.2f} dy={event.dy:+.2f} palms, "
                    f"{event.duration * 1000:.0f} ms, speed={event.speed:.1f}/s"
                )
                if state is ActivationState.ACTIVE:
                    try:
                        desc = dispatcher.handle(event)
                    except Exception:
                        log.exception("Action failed for %s", event.gesture.value)
                        desc = f"{event.gesture.value} FAILED"
                    log.info("%-12s -> %s  (%s)", event.gesture.value, desc, details)
                    last_action = desc
                else:
                    log.info("%-12s ignored, state=%s  (%s)", event.gesture.value, state.value, details)
                    last_action = f"({event.gesture.value} ignored: {state.value})"
                last_action_t = t

            if dispatcher.navigation is not None:
                for res in dispatcher.navigation.poll():
                    log.info("%-12s => %s  (%.0f ms)", res.gesture.value, res.describe(), res.elapsed * 1000)
                    last_action, last_action_t = res.describe(), time.monotonic()

            if last_t is not None and t > last_t:
                fps = 0.9 * fps + 0.1 * (1.0 / (t - last_t)) if fps else 1.0 / (t - last_t)
            last_t = t

            if view is not None:
                key = view.render(
                    Frame(
                        image=image,
                        obs=obs,
                        state=state,
                        arming_progress=activation.arming_progress,
                        diag=detector.diagnostics,
                        last_action=last_action,
                        last_action_age=time.monotonic() - last_action_t,
                        fps=fps,
                        controller_name=dispatcher.controller.name,
                    )
                )
                if key in (ord("q"), 27) or view.window_closed():
                    return
                if key == ord("p"):
                    paused = activation.toggle_pause()
                    log.info("Key: %s", "PAUSED" if paused else "RESUMED")
