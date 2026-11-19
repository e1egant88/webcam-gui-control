from __future__ import annotations

import sys

from .base import DesktopController, parse_combo
from .dryrun import DryRunController

__all__ = ["DesktopController", "DryRunController", "create_controller", "parse_combo"]


def create_controller(dry_run: bool = False) -> DesktopController:
    if dry_run:
        return DryRunController()
    if sys.platform == "win32":
        from .windows import WindowsController

        return WindowsController()
    if sys.platform == "darwin":
        raise NotImplementedError(
            "macOS controller not implemented yet (planned: Quartz CGEvent + "
            "Accessibility API). Run with --dry-run to test gesture detection."
        )
    raise NotImplementedError(f"No desktop controller for platform '{sys.platform}'")
