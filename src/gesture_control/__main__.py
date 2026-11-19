"""Command-line entry point: ``python -m gesture_control`` / GestureControl.exe."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import load_config
from .runtime import (
    SingleInstance,
    default_config_path,
    ensure_std_streams,
    is_frozen,
    log_file_path,
    setup_logging,
    show_error,
)

# Returned by the overlay when the user clicks "Restart now" in Settings.
RESTART_EXIT_CODE = 75
ALREADY_RUNNING_EXIT_CODE = 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gesture-control",
        description="Control scrolling (and next/previous) with webcam hand gestures.",
    )
    p.add_argument("-c", "--config", default=None,
                   help="TOML config file (default: config.toml next to the app / in the current folder)")
    p.add_argument("--no-user-settings", action="store_true",
                   help="ignore settings saved from the Settings window")
    p.add_argument("--dry-run", action="store_true", help="detect gestures but only log actions")
    p.add_argument("--camera", type=int, help="camera index override")
    p.add_argument("--no-mirror", action="store_true", help="do not mirror the camera image")
    p.add_argument("--headless", action="store_true", help="no overlay, tray or debug window (Ctrl+C quits)")
    p.add_argument("--no-overlay", action="store_true", help="use the OpenCV debug window instead of the overlay")
    p.add_argument("--debug-window", action="store_true", help="also show the OpenCV debug window")
    p.add_argument("--always-active", action="store_true", help="skip the dwell-to-arm step")
    p.add_argument("--self-test", action="store_true",
                   help="check camera, model, UI Automation, OCR and overlay, then exit (sends no input)")
    p.add_argument("--log-file", nargs="?", const="default", default=None,
                   help="also log to a file (default location when no path is given; always on when packaged)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def run_once(args: argparse.Namespace) -> int:
    log = logging.getLogger("gesture_control")
    config_path = Path(args.config) if args.config else default_config_path()
    settings_path = None
    if not args.no_user_settings:
        from .settings_store import user_settings_path

        settings_path = user_settings_path()
    try:
        cfg = load_config(config_path, settings_path)
    except (ValueError, OSError) as exc:
        show_error("Gesture Control - invalid configuration", f"{config_path}:\n{exc}")
        return 2
    # Command-line options override files for this run only (never saved).
    if args.dry_run:
        cfg.dry_run = True
    if args.camera is not None:
        cfg.camera.index = args.camera
    if args.no_mirror:
        cfg.camera.mirror = False
    if args.no_overlay:
        cfg.overlay.enabled = False
        cfg.debug.show_window = True
    if args.debug_window:
        cfg.debug.show_window = True
    if args.headless:
        cfg.overlay.enabled = False
        cfg.debug.show_window = False
    if args.always_active:
        cfg.activation.mode = "always"

    base_dir = config_path.resolve().parent if config_path.exists() else default_config_path().parent

    if args.self_test:
        from .selftest import run as self_test

        return self_test(cfg, base_dir)

    from .app import App  # heavy imports (mediapipe, cv2) only after arg parsing
    from .camera import CameraError

    try:
        resolved = config_path.resolve() if config_path.exists() else None
        return App(cfg, base_dir, resolved, settings_path).run(headless=args.headless)
    except CameraError as exc:
        show_error("Gesture Control - camera problem", str(exc))
        return 1
    except (NotImplementedError, FileNotFoundError, ValueError) as exc:
        show_error("Gesture Control", str(exc))
        return 1


def main(argv: list[str] | None = None) -> int:
    ensure_std_streams()
    args = build_parser().parse_args(argv)
    log_file = None
    if args.log_file not in (None, "default"):
        log_file = Path(args.log_file)
    elif args.log_file == "default" or is_frozen():
        log_file = log_file_path()
    setup_logging(args.verbose, log_file)
    log = logging.getLogger("gesture_control")
    if log_file is not None:
        log.info("Logging to %s", log_file)
    if not args.verbose:
        # Quieten MediaPipe / TFLite native INFO logging.
        os.environ.setdefault("GLOG_minloglevel", "2")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

    instance = None
    if not args.self_test:
        instance = SingleInstance()
        if not instance.acquire():
            show_error("Gesture Control", "Gesture Control is already running (see the tray icon).")
            return ALREADY_RUNNING_EXIT_CODE
    try:
        while True:
            rc = run_once(args)
            if rc != RESTART_EXIT_CODE:
                return rc
            log.info("Restarting with new settings...")
    finally:
        if instance is not None:
            instance.release()


if __name__ == "__main__":
    sys.exit(main())
