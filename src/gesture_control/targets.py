"""Which application will receive a scroll, and can it?

Windows delivers wheel input to the window *under the mouse cursor*. With two
monitors the cursor is easily somewhere unexpected - on the other screen, on
the desktop, or over an app running as administrator (Windows silently blocks
input from a normal process to an elevated one). This module names the target
so the HUD/log can say where a scroll went and why nothing may have happened.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

DESKTOP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


@dataclass(frozen=True)
class WindowTarget:
    app: str  # executable name, e.g. "chrome.exe"
    title: str
    class_name: str
    elevated: bool  # runs as admin while we don't: Windows blocks our input
    desktop: bool  # desktop wallpaper or taskbar: nothing to scroll

    def describe(self) -> str:
        if self.desktop:
            return "desktop/taskbar (nothing to scroll - move the mouse over a window)"
        name = self.app or self.class_name or "unknown window"
        if self.elevated:
            return f"{name} - runs as administrator, Windows blocks gesture input"
        return name

    @property
    def problem(self) -> bool:
        return self.desktop or self.elevated


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    _advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    )

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    TOKEN_ELEVATION = 20
    ERROR_ACCESS_DENIED = 5
    GA_ROOT = 2

    def _token_elevated(process_handle) -> bool | None:
        """True/False, or None when the token can't be opened."""
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            value = wintypes.DWORD()
            size = wintypes.DWORD()
            if not _advapi32.GetTokenInformation(
                token, TOKEN_ELEVATION, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)
            ):
                return None
            return bool(value.value)
        finally:
            _kernel32.CloseHandle(token)

    _SELF_ELEVATED: bool | None = None

    def self_elevated() -> bool:
        global _SELF_ELEVATED
        if _SELF_ELEVATED is None:
            _SELF_ELEVATED = bool(_token_elevated(_kernel32.GetCurrentProcess()))
        return _SELF_ELEVATED

    def window_target(hwnd: int) -> WindowTarget:
        cls = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, cls, 256)
        title = ctypes.create_unicode_buffer(256)
        _user32.GetWindowTextW(hwnd, title, 256)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        app, elevated = "", False
        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if handle:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                n = wintypes.DWORD(1024)
                if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(n)):
                    app = buf.value.rsplit("\\", 1)[-1]
                e = _token_elevated(handle)
                # Access denied to a process's token almost always means it is
                # elevated (or protected) - either way our input is blocked.
                elevated = e if e is not None else (ctypes.get_last_error() == ERROR_ACCESS_DENIED)
            finally:
                _kernel32.CloseHandle(handle)
        else:
            elevated = ctypes.get_last_error() == ERROR_ACCESS_DENIED
        if self_elevated():
            elevated = False  # an elevated Gesture Control can reach everything
        return WindowTarget(app, title.value, cls.value, elevated, cls.value in DESKTOP_CLASSES)

    def pointer_target() -> WindowTarget | None:
        """The top-level window under the mouse cursor (where wheel input goes)."""
        pt = wintypes.POINT()
        if not _user32.GetCursorPos(ctypes.byref(pt)):
            return None
        hwnd = _user32.WindowFromPoint(pt)
        if not hwnd:
            return None
        return window_target(_user32.GetAncestor(hwnd, GA_ROOT) or hwnd)

else:  # pragma: no cover - other platforms: no target information yet

    def pointer_target() -> WindowTarget | None:
        return None
