"""Screen capture of one window (Windows), with Gesture Control's own windows masked.

Captures what is actually on screen (via MSS / BitBlt), so it also works for
GPU-rendered apps. Our own windows (debug view, future overlay) are painted
black in the capture so OCR can never read our own status text.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

import mss
import numpy as np

from .candidates import Rect

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsIconic.argtypes = (wintypes.HWND,)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
dwmapi.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

GA_ROOT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
WDA_EXCLUDEFROMCAPTURE = 0x11
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


def window_rect(hwnd: int) -> Rect:
    """Visible window bounds (without the invisible resize border)."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return Rect(r.left, r.top, r.right, r.bottom)


def virtual_screen() -> Rect:
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    return Rect(x, y, x + user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), y + user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))


def clip(r: Rect, bounds: Rect) -> Rect:
    return Rect(max(r.left, bounds.left), max(r.top, bounds.top), min(r.right, bounds.right), min(r.bottom, bounds.bottom))


def own_window_rects() -> list[Rect]:
    """Rectangles of this process's visible top-level windows."""
    pid = os.getpid()
    rects: list[Rect] = []

    @EnumWindowsProc
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid:
                rects.append(window_rect(hwnd))
        return True

    user32.EnumWindows(cb, 0)
    return rects


def mask_rects(img: np.ndarray, origin: tuple[int, int], rects: list[Rect], skip: Rect | None = None) -> int:
    """Black out ``rects`` (screen coords) in ``img`` whose top-left is ``origin``."""
    ox, oy = origin
    h, w = img.shape[:2]
    n = 0
    for r in rects:
        if skip is not None and r == skip:
            continue
        x0, y0 = max(r.left - ox, 0), max(r.top - oy, 0)
        x1, y1 = min(r.right - ox, w), min(r.bottom - oy, h)
        if x0 < x1 and y0 < y1:
            img[y0:y1, x0:x1] = 0
            n += 1
    return n


def capture(region: Rect, exclude_own: bool = True, keep: Rect | None = None) -> np.ndarray:
    """Grab ``region`` of the screen as a BGRA uint8 array."""
    factory = getattr(mss, "MSS", None) or mss.mss  # mss >= 10 renamed the class
    with factory() as sct:
        shot = sct.grab({"left": region.left, "top": region.top, "width": region.width, "height": region.height})
        img = np.array(shot)  # BGRA
    if exclude_own:
        mask_rects(img, (region.left, region.top), own_window_rects(), skip=keep)
    return img


def root_window_at(x: int, y: int) -> int:
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return 0
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def exclude_from_capture(hwnd: int) -> bool:
    """Hide one of our windows from screenshots/screen sharing (Windows 10 2004+)."""
    return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
