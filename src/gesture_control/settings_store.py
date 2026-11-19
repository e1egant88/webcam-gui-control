"""Per-user settings file: where it lives, what goes in it, how it's written.

The settings dialog saves only the values that differ from defaults +
config.toml, into a small TOML file in the user's profile. config.toml (with
its comments) is never rewritten.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig

APP_DIR_NAME = "GestureControl"


def user_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_DIR_NAME


def user_settings_path() -> Path:
    return user_config_dir() / "settings.toml"


# --------------------------------------------------------------------- TOML
def _value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError(f"cannot write non-finite float {v!r}")
        return repr(v)
    if isinstance(v, str):
        # JSON string escapes are valid TOML basic-string escapes.
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value {type(v).__name__}")


def dumps(data: dict[str, Any]) -> str:
    """Write a dict of scalars and one level of tables as TOML."""
    lines = ["# Saved by Gesture Control's settings window. Overrides config.toml.", ""]
    top = {k: v for k, v in data.items() if not isinstance(v, dict)}
    for k, v in top.items():
        lines.append(f"{k} = {_value(v)}")
    if top:
        lines.append("")
    for section, table in data.items():
        if not isinstance(table, dict) or not table:
            continue
        lines.append(f"[{section}]")
        for k, v in table.items():
            lines.append(f"{k} = {_value(v)}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------- diff
def diff(cfg: AppConfig, base: AppConfig) -> dict[str, Any]:
    """Nested dict of every value in ``cfg`` that differs from ``base``."""
    out: dict[str, Any] = {}
    for f in fields(cfg):
        a, b = getattr(cfg, f.name), getattr(base, f.name)
        if is_dataclass(a):
            table = {g.name: getattr(a, g.name) for g in fields(a) if getattr(a, g.name) != getattr(b, g.name)}
            if table:
                out[f.name] = table
        elif a != b:
            out[f.name] = a
    return out


def save(cfg: AppConfig, base: AppConfig, path: Path | None = None) -> Path:
    """Write ``cfg``'s differences from ``base``; remove the file if there are none."""
    path = path or user_settings_path()
    data = diff(cfg, base)
    if not data:
        if path.exists():
            path.unlink()
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(data), encoding="utf-8")
    tmp.replace(path)
    return path


def copy_into(target: AppConfig, source: AppConfig) -> None:
    """Copy every value from ``source`` into ``target`` *in place*.

    The engine, detector, scroller and overlay hold references to the section
    objects of the live config, so mutating them applies changes immediately.
    """
    for f in fields(target):
        src = getattr(source, f.name)
        if is_dataclass(src):
            dst = getattr(target, f.name)
            for g in fields(dst):
                setattr(dst, g.name, getattr(src, g.name))
        else:
            setattr(target, f.name, src)
