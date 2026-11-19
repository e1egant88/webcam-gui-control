# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Gesture Control (Windows, one-folder build).
# Build with packaging\build.ps1 rather than calling this directly: the script
# prepares the icon, the model and the UI Automation wrappers first.
#
# Produces dist\GestureControl\ with two executables sharing one runtime:
#   GestureControl.exe       - windowed: tray + overlay, logs to %APPDATA%
#   gesture-control-cli.exe  - console: same app, plus --self-test etc.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - provided by PyInstaller
ICON = os.path.join(ROOT, "build", "icon.ico")

# MediaPipe loads mediapipe/tasks/c/libmediapipe.dll via importlib.resources,
# so it must keep that package-relative location.
binaries = collect_dynamic_libs("mediapipe")
datas = collect_data_files("mediapipe", excludes=["**/*.pyi", "**/testdata/**"])

hiddenimports = [
    # Pre-generated comtypes wrappers for UIAutomationCore (made by build.ps1),
    # so the packaged app never needs to generate code at runtime.
    *collect_submodules("comtypes.gen"),
    # Imported lazily inside functions:
    "gesture_control.overlay.qt_app",
    "gesture_control.navigation.uia_windows",
    "gesture_control.navigation.ocr_navigator",
    "gesture_control.navigation.ocr_windows",
    "gesture_control.selftest",
    "winrt.windows.media.ocr",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.globalization",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
]

# Note: matplotlib must NOT be excluded - `import mediapipe` imports it.
excludes = ["tkinter", "pytest", "_pytest", "IPython", "PyInstaller"]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

common = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
              icon=ICON if os.path.exists(ICON) else None)

gui = EXE(pyz, a.scripts, [], name="GestureControl", console=False, **common)  # noqa: F821
cli = EXE(pyz, a.scripts, [], name="gesture-control-cli", console=True, **common)  # noqa: F821

coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="GestureControl")  # noqa: F821
