"""System tray icon: state at a glance, pause, overlay toggles, config, quit."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..activation import ActivationState
from .widgets import STATE_STYLE


def state_icon(state: ActivationState, size: int = 64) -> QIcon:
    _, color = STATE_STYLE[state]
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(28, 28, 34))
    p.drawEllipse(QRectF(2, 2, size - 4, size - 4))
    p.setBrush(color)
    p.drawEllipse(QRectF(size * 0.22, size * 0.22, size * 0.56, size * 0.56))
    if state is ActivationState.PAUSED:
        p.setBrush(QColor(28, 28, 34))
        w = size * 0.08
        p.drawRect(QRectF(size * 0.39, size * 0.34, w, size * 0.32))
        p.drawRect(QRectF(size * 0.53, size * 0.34, w, size * 0.32))
    p.end()
    return QIcon(pm)


class Tray:
    def __init__(
        self,
        *,
        hotkey: str,
        on_toggle_pause: Callable[[], None],
        on_toggle_hud: Callable[[bool], None],
        on_toggle_camera: Callable[[bool], None],
        on_open_config: Callable[[], None] | None,
        on_quit: Callable[[], None],
        hud_visible: bool,
        camera_visible: bool,
    ):
        self._icons = {s: state_icon(s) for s in ActivationState}
        self._state: ActivationState | None = None
        self.icon = QSystemTrayIcon(self._icons[ActivationState.IDLE])
        self._hotkey = hotkey
        self._on_toggle_pause = on_toggle_pause

        menu = QMenu()
        self.status_action = QAction("Starting...", menu)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        self.pause_action = QAction(f"Pause\t{hotkey.title()}", menu, checkable=True)
        self.pause_action.triggered.connect(lambda _checked: on_toggle_pause())
        menu.addAction(self.pause_action)

        self.hud_action = QAction("Show overlay", menu, checkable=True, checked=hud_visible)
        self.hud_action.toggled.connect(on_toggle_hud)
        menu.addAction(self.hud_action)

        self.camera_action = QAction("Show camera in overlay", menu, checkable=True, checked=camera_visible)
        self.camera_action.toggled.connect(on_toggle_camera)
        menu.addAction(self.camera_action)
        menu.addSeparator()

        if on_open_config is not None:
            open_cfg = QAction("Open config file (restart to apply)", menu)
            open_cfg.triggered.connect(lambda _checked: on_open_config())
            menu.addAction(open_cfg)
            menu.addSeparator()

        quit_action = QAction("Quit Gesture Control", menu)
        quit_action.triggered.connect(lambda _checked: on_quit())
        menu.addAction(quit_action)

        self._menu = menu  # keep a reference
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        self.set_state(ActivationState.IDLE, "")

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # left click
            self._on_toggle_pause()

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def set_state(self, state: ActivationState, detail: str) -> None:
        if state is not self._state:
            self._state = state
            self.icon.setIcon(self._icons[state])
            self.pause_action.setChecked(state is ActivationState.PAUSED)
        label, _ = STATE_STYLE[state]
        text = f"Gesture Control - {label}"
        if detail:
            text += f"\n{detail}"
        self.status_action.setText(label.title() + (f": {detail}" if detail else ""))
        self.icon.setToolTip(text + "\nLeft-click: pause/resume")

    def notify(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
