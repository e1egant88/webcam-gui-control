"""Overlay widgets: the status HUD and the target highlight.

Both are frameless, always on top, transparent for mouse input, never take
focus, and (on Windows) are hidden from screen capture so OCR never sees them.
"""

from __future__ import annotations

import sys
import time

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..activation import ActivationState
from ..config import OverlayConfig
from ..engine import Snapshot, UiEvent
from ..types import Gesture

STATE_STYLE = {
    ActivationState.PAUSED: ("PAUSED", QColor(220, 90, 90)),
    ActivationState.IDLE: ("IDLE", QColor(160, 160, 170)),
    ActivationState.ARMING: ("ARMING", QColor(255, 190, 40)),
    ActivationState.ACTIVE: ("ACTIVE", QColor(90, 210, 120)),
}
ARROWS = {Gesture.SCROLL_UP: "↑", Gesture.SCROLL_DOWN: "↓", Gesture.PREVIOUS: "←", Gesture.NEXT: "→"}
ACCENT = QColor(80, 170, 255)

THUMB_W, THUMB_H = 240, 180
PAD = 12
FLASH_S = 0.6
ACTION_VISIBLE_S = 4.0


class OverlayWidget(QWidget):
    """Base: the window flags/attributes every overlay window needs."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.capture_excluded = False
        self._styled = False

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self._styled and sys.platform == "win32":
            from .win_styles import make_overlay_window

            self.capture_excluded = make_overlay_window(int(self.winId()))
            self._styled = True

    @property
    def hwnd(self) -> int:
        return int(self.winId())


class HudWindow(OverlayWidget):
    def __init__(self, cfg: OverlayConfig):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("Gesture Control HUD")
        self._snap: Snapshot | None = None
        self._thumb: QImage | None = None
        self._flash: tuple[Gesture, float, bool] | None = None
        self.show_camera = cfg.show_camera
        self._apply_size()

    # ------------------------------------------------------------ layout
    def _apply_size(self) -> None:
        h = PAD + 26 + 8 + 20 + PAD
        if self.show_camera:
            h += THUMB_H + 8
        self.setFixedSize(THUMB_W + 2 * PAD, h)
        self.reposition()

    def set_show_camera(self, on: bool) -> None:
        self.show_camera = on
        self._thumb = None
        self._apply_size()
        self.update()

    def reposition(self) -> None:
        screen = self.screen() or self._primary_screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        m = self.cfg.margin
        x = geo.right() - self.width() - m + 1 if "right" in self.cfg.corner else geo.left() + m
        y = geo.bottom() - self.height() - m + 1 if "bottom" in self.cfg.corner else geo.top() + m
        self.move(x, y)

    @staticmethod
    def _primary_screen():
        from PySide6.QtGui import QGuiApplication

        return QGuiApplication.primaryScreen()

    # ------------------------------------------------------------ data
    def set_snapshot(self, snap: Snapshot) -> None:
        if snap is self._snap:
            return
        self._snap = snap
        if self.show_camera and snap.image is not None and self.isVisible():
            self._thumb = self._make_thumb(snap)
        self.update()

    def flash(self, event: UiEvent) -> None:
        self._flash = (event.gesture, time.monotonic(), event.acted)
        self.update()

    @staticmethod
    def _make_thumb(snap: Snapshot) -> QImage:
        from ..debug_view import draw_hand

        small = cv2.resize(snap.image, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
        if snap.obs is not None:
            draw_hand(small, snap.obs, skeleton=True, thickness=1)
        rgb = np.ascontiguousarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        return QImage(rgb.data, THUMB_W, THUMB_H, 3 * THUMB_W, QImage.Format.Format_RGB888).copy()

    def status_text(self) -> str:
        snap = self._snap
        if snap is None:
            return "Starting..."
        label, _ = STATE_STYLE[snap.state]
        if snap.state is ActivationState.ARMING:
            return f"{label} {int(snap.arming_progress * 100)}%"
        if snap.state is ActivationState.IDLE:
            return f"{label} - hold palm still"
        return label

    # ------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.fillPath(path, QColor(18, 18, 22, int(255 * self.cfg.opacity)))

        snap = self._snap
        now = time.monotonic()
        y = PAD
        if self.show_camera:
            thumb_rect = QRectF(PAD, y, THUMB_W, THUMB_H)
            clip = QPainterPath()
            clip.addRoundedRect(thumb_rect, 8, 8)
            p.save()
            p.setClipPath(clip)
            if self._thumb is not None:
                p.drawImage(thumb_rect, self._thumb)
            else:
                p.fillRect(thumb_rect, QColor(40, 40, 46))
            self._paint_flash(p, thumb_rect, now)
            p.restore()
            y += THUMB_H + 8
        elif self._flash is not None:
            self._paint_flash(p, QRectF(self.width() - 60, PAD, 48, 26), now, small=True)

        # State pill + progress
        state = snap.state if snap else ActivationState.IDLE
        _, color = STATE_STYLE[state]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(PAD, y + 8, 10, 10))
        p.setPen(QColor(235, 235, 240))
        font = QFont(self.font())
        font.setPointSizeF(10.5)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(PAD + 18, y, THUMB_W - 18, 26), Qt.AlignmentFlag.AlignVCenter, self.status_text())
        if snap is not None and snap.controller_name == "dry-run":
            font.setPointSizeF(8)
            p.setFont(font)
            p.setPen(QColor(255, 190, 40))
            p.drawText(QRectF(PAD, y, THUMB_W, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "DRY RUN")
        if state is ActivationState.ARMING and snap is not None:
            p.fillRect(QRectF(PAD, y + 24, THUMB_W, 3), QColor(60, 60, 66))
            p.fillRect(QRectF(PAD, y + 24, THUMB_W * snap.arming_progress, 3), color)
        y += 26 + 8

        # Last action
        if snap is not None and snap.last_action and now - snap.last_action_time < ACTION_VISIBLE_S:
            font.setBold(False)
            font.setPointSizeF(9)
            p.setFont(font)
            p.setPen(QColor(190, 200, 215))
            text = p.fontMetrics().elidedText(snap.last_action, Qt.TextElideMode.ElideRight, THUMB_W)
            p.drawText(QRectF(PAD, y, THUMB_W, 20), Qt.AlignmentFlag.AlignVCenter, text)
        p.end()

    def _paint_flash(self, p: QPainter, area: QRectF, now: float, small: bool = False) -> None:
        if self._flash is None:
            return
        gesture, t0, acted = self._flash
        age = now - t0
        if age > FLASH_S:
            self._flash = None
            return
        alpha = int(255 * (1 - age / FLASH_S))
        color = QColor(ACCENT if acted else QColor(160, 160, 170))
        color.setAlpha(alpha)
        font = QFont(self.font())
        font.setPointSizeF(16 if small else 64)
        font.setBold(True)
        p.setFont(font)
        p.setPen(color)
        p.drawText(area, Qt.AlignmentFlag.AlignCenter, ARROWS[gesture])
        QTimer.singleShot(30, self.update)


class HighlightWindow(OverlayWidget):
    """Briefly outlines the control that was activated."""

    DURATION_S = 0.9
    INFLATE = 6

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Gesture Control highlight")
        self._t0 = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def show_at(self, x: float, y: float, w: float, h: float) -> None:
        i = self.INFLATE
        self.setGeometry(int(x - i), int(y - i), int(w + 2 * i), int(h + 2 * i))
        self._t0 = time.monotonic()
        self.show()
        self.raise_()
        self._timer.start()
        self.update()

    def _tick(self) -> None:
        if time.monotonic() - self._t0 > self.DURATION_S:
            self._timer.stop()
            self.hide()
        else:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        age = time.monotonic() - self._t0
        alpha = max(0.0, 1 - age / self.DURATION_S)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(ACCENT)
        color.setAlphaF(alpha)
        pen = QPen(color, 3)
        p.setPen(pen)
        fill = QColor(ACCENT)
        fill.setAlphaF(0.15 * alpha)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 6, 6)
        p.end()
