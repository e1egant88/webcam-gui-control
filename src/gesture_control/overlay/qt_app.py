"""Qt front end: engine on a worker thread, overlay + tray on the main thread."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from ..activation import ActivationState
from ..config import AppConfig
from ..engine import Engine, Snapshot
from ..navigation.candidates import Rect
from .geometry import match_monitors, phys_to_logical
from .tray import Tray
from .widgets import HighlightWindow, HudWindow, TargetFrame

log = logging.getLogger(__name__)

UI_INTERVAL_MS = 33
# After a next/previous gesture, keep the frame on that window's monitor this long.
NAV_FRAME_HOLD_S = 1.5


def cursor_position() -> tuple[int, int]:
    """Mouse cursor in physical pixels (where wheel input goes)."""
    if sys.platform == "win32":
        from ..controllers.windows import get_cursor_pos

        return get_cursor_pos()
    from PySide6.QtGui import QCursor

    p = QCursor.pos()
    return p.x(), p.y()


def focused_window_rect() -> Rect | None:
    """Physical rect of the foreground window (where next/previous act)."""
    if sys.platform != "win32":
        return None
    from ..navigation.screen_windows import window_rect
    from ..navigation.uia_windows import foreground_window

    hwnd = foreground_window()
    return window_rect(hwnd) if hwnd else None


def qt_monitors():
    """Current monitors, pairing Win32 physical rects with Qt logical geometry."""
    screens = [
        (s.name(), (s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height()), s.devicePixelRatio())
        for s in QGuiApplication.screens()
    ]
    if sys.platform == "win32":
        from .win_styles import physical_monitors

        return match_monitors(physical_monitors(), screens)
    # Elsewhere assume physical = logical * dpr.
    from .geometry import Monitor

    return [
        Monitor(n, Rect(int(x * d), int(y * d), int((x + w) * d), int((y + h) * d)), (x, y, w, h), d)
        for n, (x, y, w, h), d in screens
    ]


class OverlayController:
    def __init__(
        self, engine: Engine, cfg: AppConfig, config_path: Path | None, settings_path: Path | None = None
    ):
        self.engine = engine
        self.cfg = cfg
        self.config_path = config_path
        self.settings_path = settings_path
        self._lock = threading.Lock()
        self._latest: Snapshot | None = None
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._failed = False
        self.restart_requested = False
        self._dialog = None

        self.hud = HudWindow(cfg.overlay)
        self.highlight = HighlightWindow()
        self.frame = TargetFrame()
        self._monitor_cache = None
        self._nav_monitor = None
        self._nav_until = 0.0
        self.tray = Tray(
            hotkey=cfg.activation.pause_hotkey,
            on_toggle_pause=engine.toggle_pause,
            on_toggle_hud=self.hud.setVisible,
            on_toggle_camera=self._set_camera,
            on_open_config=self._open_config if config_path else None,
            on_quit=QApplication.quit,
            on_settings=self.open_settings if settings_path else None,
            hud_visible=True,
            camera_visible=cfg.overlay.show_camera,
        )
        self.timer = QTimer()
        self.timer.setInterval(UI_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)
        self._thread = threading.Thread(target=self._engine_thread, name="engine", daemon=True)

    # ------------------------------------------------------------ engine side
    def _engine_thread(self) -> None:
        view = None
        try:
            if self.cfg.debug.show_window:
                from ..debug_view import DebugView

                view = DebugView(self.cfg)
            self.engine.run(self._stop, lambda snap: self._on_snapshot(snap, view))
        except Exception:
            log.exception("Engine stopped with an error")
            self._failed = True
        finally:
            if view is not None:
                view.close()
            self._finished.set()

    def _on_snapshot(self, snap: Snapshot, view) -> bool:
        with self._lock:
            self._latest = snap
        if view is not None:
            key = view.render_snapshot(snap)
            if key in (ord("q"), 27):
                return False
            if key == ord("p"):
                self.engine.toggle_pause()
        return True

    # ------------------------------------------------------------ UI side
    def _tick(self) -> None:
        if self._finished.is_set():
            QApplication.quit()
            return
        with self._lock:
            snap = self._latest
        if snap is not None:
            self.hud.set_snapshot(snap)
            self.tray.set_state(snap.state, snap.last_action if snap.state is ActivationState.ACTIVE else "")
        events = self.engine.drain_events()
        for ev in events:
            self.hud.flash(ev)
            if ev.rect is not None and self.cfg.overlay.highlight_targets:
                self._highlight(Rect(*ev.rect))
        self._update_frame(snap.state if snap else None, events)

    # ------------------------------------------------------------ target frame
    def _monitors(self):
        """Monitor list, refreshed every 2 s (cheap, but not needed every frame)."""
        now = time.monotonic()
        if self._monitor_cache is None or now - self._monitor_cache[0] > 2.0:
            self._monitor_cache = (now, qt_monitors())
        return self._monitor_cache[1]

    def _update_frame(self, state: ActivationState | None, events) -> None:
        if not self.cfg.overlay.target_frame or state not in (ActivationState.ACTIVE, ActivationState.ARMING):
            self.frame.hide()
            return
        monitors = self._monitors()
        now = time.monotonic()
        for ev in events:
            if not ev.acted:
                continue
            if not ev.gesture.is_vertical:
                # Next/previous act on the focused window: frame its monitor for a moment.
                rect = Rect(*ev.rect) if ev.rect else focused_window_rect()
                if rect is not None:
                    from .geometry import monitor_for

                    self._nav_monitor = monitor_for(rect, monitors)
                    self._nav_until = now + NAV_FRAME_HOLD_S
            self.frame.flash()
        if now < self._nav_until and self._nav_monitor is not None:
            monitor = self._nav_monitor
        else:
            # Scrolling goes to the window under the mouse cursor.
            from .geometry import monitor_at

            x, y = cursor_position()
            monitor = monitor_at(x, y, monitors)
        if monitor is None:
            self.frame.hide()
            return
        self.frame.set_monitor(monitor.logical)
        self.frame.set_level("normal" if state is ActivationState.ACTIVE else "dim")
        self.frame.show()

    def _highlight(self, rect: Rect) -> None:
        geo = phys_to_logical(rect, self._monitors())
        if geo is not None:
            self.highlight.show_at(*geo)

    def _set_camera(self, on: bool) -> None:
        self.cfg.overlay.show_camera = on
        self.hud.set_show_camera(on)

    def open_settings(self) -> None:
        from ..config import load_base_config, load_config
        from .settings_dialog import SettingsDialog

        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        assert self.settings_path is not None
        try:
            base = load_base_config(self.config_path)
            saved = load_config(self.config_path, self.settings_path)
        except ValueError as exc:
            self.tray.notify("Settings unavailable", f"config.toml is invalid: {exc}")
            return
        self._dialog = SettingsDialog(
            self.cfg, base, saved, self.settings_path,
            on_live_applied=self._settings_applied, on_restart=self.request_restart,
        )
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def _settings_applied(self) -> None:
        # Overlay values are read live, but the HUD caches size and position.
        self.hud.set_show_camera(self.cfg.overlay.show_camera)
        self.tray.camera_action.setChecked(self.cfg.overlay.show_camera)
        self.hud.reposition()
        self.hud.update()

    def request_restart(self) -> None:
        self.restart_requested = True
        QApplication.quit()

    def _open_config(self) -> None:
        assert self.config_path is not None
        if sys.platform == "win32":
            os.startfile(self.config_path)  # noqa: S606 - opens in the user's editor
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_path)))

    def start(self) -> None:
        self._thread.start()
        self.hud.show()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            log.warning("No system tray available; quit with Ctrl+C")
        self.timer.start()
        log.info(
            "Overlay running. Tray icon: left-click pauses, right-click for menu. Pause hotkey: %s",
            self.cfg.activation.pause_hotkey,
        )

    def shutdown(self) -> None:
        self.timer.stop()
        self._stop.set()
        self._thread.join(timeout=3.0)
        if self._dialog is not None:
            self._dialog.close()
        self.tray.hide()
        self.hud.close()
        self.highlight.close()
        self.frame.close()


RESTART_EXIT_CODE = 75


def run_overlay(
    engine: Engine, cfg: AppConfig, config_path: Path | None, settings_path: Path | None = None
) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Gesture Control")
    controller = OverlayController(engine, cfg, config_path, settings_path)
    # Ctrl+C in the console: Qt's loop doesn't run Python signal handlers by
    # itself, but our 33 ms timer gives Python a chance to run this one.
    signal.signal(signal.SIGINT, lambda *_: QApplication.quit())
    controller.start()
    try:
        app.exec()
    finally:
        controller.shutdown()
    if controller.restart_requested:
        return RESTART_EXIT_CODE
    return 1 if controller._failed else 0
