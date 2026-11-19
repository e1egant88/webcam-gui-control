"""Settings window (opened from the tray).

Shows the *saved* settings (defaults + config.toml + the user's settings
file), not temporary command-line overrides such as --dry-run. On Apply:
  1. the edited values are validated as a whole;
  2. only values that differ from defaults + config.toml are saved to the
     user's settings file (config.toml is never rewritten);
  3. values the user actually changed are copied into the running app.
     "Live" ones take effect at once; the rest need a restart, which the
     window offers.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import settings_store
from ..config import AppConfig, apply_overrides
from ..settings_schema import TABS, Spec, all_specs

log = logging.getLogger(__name__)

RESTART_MARK = " ⟳"


def _get(cfg: AppConfig, spec: Spec) -> Any:
    return getattr(getattr(cfg, spec.section), spec.key) if spec.section else getattr(cfg, spec.key)


def _set(cfg: AppConfig, spec: Spec, value: Any) -> None:
    target = getattr(cfg, spec.section) if spec.section else cfg
    setattr(target, spec.key, value)


class SettingsDialog(QDialog):
    def __init__(
        self,
        live: AppConfig,
        base: AppConfig,
        saved: AppConfig,
        settings_path: Path,
        on_live_applied: Callable[[], None] | None = None,
        on_restart: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Gesture Control - Settings")
        self.live = live
        self.base = base
        self.saved = copy.deepcopy(saved)
        self.settings_path = settings_path
        self.on_live_applied = on_live_applied
        self.on_restart = on_restart
        self.restart_pending = False
        self.editors: dict[tuple[str, str], QWidget] = {}

        tabs = QTabWidget()
        for title, specs in TABS.items():
            page = QWidget()
            form = QFormLayout(page)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            for spec in specs:
                editor = self._make_editor(spec, _get(self.saved, spec))
                self.editors[(spec.section, spec.key)] = editor
                label = QLabel(spec.label + ("" if spec.live else RESTART_MARK))
                if spec.help:
                    label.setToolTip(spec.help)
                    editor.setToolTip(spec.help)
                form.addRow(label, editor)
            tabs.addTab(page, title)

        note = QLabel(f"{RESTART_MARK.strip()} = takes effect after restart.  Saved to: {settings_path}")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b;")
        self.error.setWordWrap(True)
        self.error.hide()

        self.restart_row = QWidget()
        row = QHBoxLayout(self.restart_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Some changes need a restart."))
        restart_btn = QPushButton("Restart now")
        restart_btn.clicked.connect(self._restart)
        row.addStretch()
        row.addWidget(restart_btn)
        self.restart_row.hide()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setToolTip(
            "Reset all fields to config.toml / built-in defaults (click Apply to keep)"
        )

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self.error)
        layout.addWidget(self.restart_row)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.resize(520, 480)

    # ------------------------------------------------------------ editors
    @staticmethod
    def _make_editor(spec: Spec, value: Any) -> QWidget:
        if spec.choices:
            w = QComboBox()
            w.addItems(list(spec.choices))
            w.setCurrentText(str(value))
            return w
        if isinstance(value, bool):
            w = QCheckBox()
            w.setChecked(value)
            return w
        if isinstance(value, int):
            w = QSpinBox()
            w.setRange(int(spec.minimum or 0), int(spec.maximum if spec.maximum is not None else 10**6))
            w.setSingleStep(int(spec.step or 1))
            w.setSuffix(spec.suffix)
            w.setValue(value)
            return w
        if isinstance(value, float):
            w = QDoubleSpinBox()
            w.setDecimals(spec.decimals)
            w.setRange(spec.minimum if spec.minimum is not None else 0.0, spec.maximum if spec.maximum is not None else 1e6)
            w.setSingleStep(spec.step or 0.1)
            w.setSuffix(spec.suffix)
            w.setValue(value)
            return w
        if isinstance(value, list):
            w = QLineEdit(", ".join(value))
            return w
        return QLineEdit(str(value))

    def _read(self, spec: Spec) -> Any:
        w = self.editors[(spec.section, spec.key)]
        current = _get(self.saved, spec)
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QSpinBox):
            return int(w.value())
        if isinstance(w, QDoubleSpinBox):
            value = round(float(w.value()), spec.decimals)
            # The box shows `decimals` places; untouched precise values stay as-is.
            if isinstance(current, float) and round(current, spec.decimals) == value:
                return current
            return value
        text = w.text()
        if isinstance(current, list):
            return [part.strip() for part in text.split(",") if part.strip()]
        return text.strip()

    def _write(self, spec: Spec, value: Any) -> None:
        w = self.editors[(spec.section, spec.key)]
        if isinstance(w, QComboBox):
            w.setCurrentText(str(value))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            w.setValue(value)
        elif isinstance(value, list):
            w.setText(", ".join(value))
        else:
            w.setText(str(value))

    def restore_defaults(self) -> None:
        for spec in all_specs():
            self._write(spec, _get(self.base, spec))

    # ------------------------------------------------------------ apply
    def edited_values(self) -> dict[str, Any]:
        """Nested override dict of every field shown in the window."""
        data: dict[str, Any] = {}
        for spec in all_specs():
            value = self._read(spec)
            if spec.section:
                data.setdefault(spec.section, {})[spec.key] = value
            else:
                data[spec.key] = value
        return data

    def apply(self) -> bool:
        try:
            new = apply_overrides(self.saved, self.edited_values())
        except ValueError as exc:
            self.error.setText(f"Not applied: {exc}")
            self.error.show()
            return False
        self.error.hide()

        changed = [s for s in all_specs() if _get(new, s) != _get(self.saved, s)]
        settings_store.save(new, self.base, self.settings_path)
        restart = False
        for spec in changed:
            if spec.live:
                _set(self.live, spec, copy.deepcopy(_get(new, spec)))
            else:
                restart = True
        log.info(
            "Settings saved (%d changed: %s)%s",
            len(changed),
            ", ".join(f"{s.section + '.' if s.section else ''}{s.key}" for s in changed) or "none",
            "; restart needed" if restart else "",
        )
        self.saved = new
        if restart:
            self.restart_pending = True
        self.restart_row.setVisible(self.restart_pending)
        if changed and self.on_live_applied is not None:
            self.on_live_applied()
        return True

    def _ok(self) -> None:
        if self.apply():
            self.accept()

    def _restart(self) -> None:
        if self.apply() and self.on_restart is not None:
            self.accept()
            self.on_restart()


