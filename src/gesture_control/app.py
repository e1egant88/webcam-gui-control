"""Choose a front end and run the engine.

* Qt overlay (default): click-through HUD, target highlight and tray icon.
  The engine runs on a background thread; Qt owns the main thread.
* OpenCV debug window: used with --debug-window, or when the overlay is off
  or PySide6 is not installed.
* Headless: no UI at all (Ctrl+C to quit).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config import AppConfig
from .engine import Engine, Snapshot

log = logging.getLogger(__name__)


def qt_available() -> bool:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        return False
    return True


class App:
    def __init__(
        self,
        cfg: AppConfig,
        base_dir: Path,
        config_path: Path | None = None,
        settings_path: Path | None = None,
    ):
        self.cfg = cfg
        self.base_dir = base_dir
        self.config_path = config_path
        self.settings_path = settings_path

    def run(self, headless: bool = False) -> int:
        cfg = self.cfg
        use_qt = cfg.overlay.enabled and not headless and qt_available()
        if cfg.overlay.enabled and not headless and not use_qt:
            log.warning("PySide6 not installed - using the OpenCV debug window instead of the overlay")
            cfg.debug.show_window = True

        engine = Engine.create(cfg)
        try:
            engine.start(self.base_dir)
            if use_qt:
                from .overlay.qt_app import run_overlay

                return run_overlay(engine, cfg, self.config_path, self.settings_path)
            return self._run_opencv(engine, show_window=cfg.debug.show_window and not headless)
        except KeyboardInterrupt:
            log.info("Interrupted")
            return 0
        finally:
            engine.close()

    def _run_opencv(self, engine: Engine, show_window: bool) -> int:
        stop = threading.Event()
        if not show_window:
            log.info("Running headless. Press Ctrl+C to quit.")
            engine.run(stop, lambda snap: None)
            return 0

        from .debug_view import DebugView

        view = DebugView(self.cfg)
        try:
            engine.run(stop, lambda snap: self._render(view, engine, snap))
        finally:
            view.close()
        return 0

    @staticmethod
    def _render(view, engine: Engine, snap: Snapshot) -> bool:
        key = view.render_snapshot(snap)
        if key in (ord("q"), 27) or view.window_closed():
            return False
        if key == ord("p"):
            engine.toggle_pause()
        return True
