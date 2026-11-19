"""Process-level concerns: frozen (packaged) mode, logging, single instance."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def is_frozen() -> bool:
    """True when running from a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder holding the executable (packaged) or the current directory (source)."""
    return Path(sys.executable).resolve().parent if is_frozen() else Path.cwd()


def default_config_path() -> Path:
    # Packaged: config.toml ships next to GestureControl.exe, wherever it is
    # launched from (shortcut, Start menu, autostart). Source: current folder.
    return app_dir() / "config.toml"


def ensure_std_streams() -> None:
    """A windowed (no-console) exe has sys.stdout/stderr = None; give them a sink."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def log_file_path() -> Path:
    from .settings_store import user_config_dir

    return user_config_dir() / "logs" / "gesture-control.log"


def setup_logging(verbose: bool, log_file: Path | None) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s " + LOG_FORMAT.split(" ", 1)[1]))
            root.addHandler(fh)
        except OSError as exc:
            logging.getLogger(__name__).warning("Cannot write log file %s: %s", log_file, exc)


class SingleInstance:
    """Named-mutex guard so two copies don't fight over the camera and hotkey."""

    NAME = "Local\\GestureControl-SingleInstance"

    def __init__(self, name: str = NAME):
        self.name = name
        self._handle = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, self.name)
        already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        if not handle:
            return True  # can't tell; don't block the user
        if already:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None:
            import ctypes

            ctypes.WinDLL("kernel32").CloseHandle(self._handle)
            self._handle = None


def show_error(title: str, message: str) -> None:
    """Visible error even without a console (packaged windowed app)."""
    logging.getLogger("gesture_control").error("%s: %s", title, message)
    if sys.platform == "win32" and is_frozen():
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10 | 0x40000)  # MB_ICONERROR | MB_TOPMOST
