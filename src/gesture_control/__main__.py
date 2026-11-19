"""Command-line entry point: ``python -m gesture_control``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import load_config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gesture-control",
        description="Control scrolling (and next/previous) with webcam hand gestures.",
    )
    p.add_argument("-c", "--config", default="config.toml", help="TOML config file (default: config.toml)")
    p.add_argument("--dry-run", action="store_true", help="detect gestures but only log actions")
    p.add_argument("--camera", type=int, help="camera index override")
    p.add_argument("--no-mirror", action="store_true", help="do not mirror the camera image")
    p.add_argument("--headless", action="store_true", help="no debug window")
    p.add_argument("--always-active", action="store_true", help="skip the dwell-to-arm step")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("gesture_control")
    config_path = Path(args.config)
    try:
        cfg = load_config(config_path)
    except (ValueError, OSError) as exc:
        log.error("Invalid configuration: %s", exc)
        return 2
    if args.dry_run:
        cfg.dry_run = True
    if args.camera is not None:
        cfg.camera.index = args.camera
    if args.no_mirror:
        cfg.camera.mirror = False
    if args.headless:
        cfg.debug.show_window = False
    if args.always_active:
        cfg.activation.mode = "always"

    base_dir = config_path.resolve().parent if config_path.exists() else Path.cwd()

    if not args.verbose:
        # Quieten MediaPipe / TFLite native INFO logging.
        os.environ.setdefault("GLOG_minloglevel", "2")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

    from .app import App  # heavy imports (mediapipe, cv2) only after arg parsing
    from .camera import CameraError

    try:
        return App(cfg, base_dir).run()
    except CameraError as exc:
        log.error("%s", exc)
        return 1
    except (NotImplementedError, FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
