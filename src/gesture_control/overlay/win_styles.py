"""Win32 helpers for overlay windows: click-through, no focus, hidden from capture."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from ..navigation.candidates import Rect

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
OVERLAY_EX_STYLE = WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32),
        ]


def ex_style(hwnd: int) -> int:
    return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)


def make_overlay_window(hwnd: int) -> bool:
    """Click-through, never activated, not in the taskbar, hidden from screen capture.

    Returns whether capture exclusion succeeded (needs Windows 10 2004+).
    """
    if sys.platform != "win32":
        return False
    from ..navigation.screen_windows import exclude_from_capture

    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex_style(hwnd) | OVERLAY_EX_STYLE)
    ok = exclude_from_capture(hwnd)
    if not ok:
        log.warning("Could not exclude overlay window from capture; it will be masked for OCR instead")
    return ok


def physical_monitors() -> list[tuple[str, Rect]]:
    """(device name, physical rect) for each monitor."""
    out: list[tuple[str, Rect]] = []

    @MonitorEnumProc
    def cb(hmon, _hdc, _rect, _lp):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            out.append((info.szDevice, Rect(r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    return out
