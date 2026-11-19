"""Runs navigation requests on a background worker so the camera loop never blocks.

UI Automation calls are cross-process and can be slow (big web pages) or even
hang (an app that is busy, or a Win32 button whose Invoke opens a modal
dialog). The worker owns the UIA COM objects; the main loop only enqueues
requests and polls results. A worker stuck for longer than ``STUCK_AFTER_S``
is abandoned and replaced, and an abandoned worker never acts late because
every action is checked against the request's deadline.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..config import NavigationConfig
from ..controllers import DesktopController, parse_combo
from ..types import Gesture
from . import NavigationAttempt, Outcome

log = logging.getLogger(__name__)

STUCK_AFTER_S = 4.0
# Fallback keys may still be sent this long after the search deadline.
FALLBACK_GRACE_S = 0.5
FALLBACK_OUTCOMES = {Outcome.NOT_FOUND, Outcome.AMBIGUOUS, Outcome.TIMEOUT, Outcome.ERROR}


class NavigationBackend(Protocol):
    def navigate(self, direction: Gesture, deadline: float) -> NavigationAttempt: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class NavigationResult:
    gesture: Gesture
    attempt: NavigationAttempt
    # What actually happened: "invoke", "click", "would invoke", "keys", "none".
    action: str
    elapsed: float

    def describe(self) -> str:
        a = self.attempt
        if a.outcome is Outcome.ACTED:
            return f"{self.gesture.value}: {a.method} {a.target}"
        if self.action == "keys":
            return f"{self.gesture.value}: keys ({a.outcome.value}: {a.detail})"
        return f"{self.gesture.value}: nothing ({a.outcome.value}: {a.detail})"


@dataclass(frozen=True)
class _Job:
    gesture: Gesture
    requested: float
    deadline: float


class _Worker:
    def __init__(self, service: "NavigationService", generation: int):
        self.service = service
        self.generation = generation
        self.jobs: queue.Queue[_Job | None] = queue.Queue()
        self.busy_since: float | None = None
        self.thread = threading.Thread(target=self._run, name=f"navigation-{generation}", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        svc = self.service
        backend: NavigationBackend | None = None
        try:
            backend = svc.backend_factory()
        except Exception:
            log.exception("Navigation backend unavailable; using key fallback only")
        try:
            while True:
                job = self.jobs.get()
                if job is None:
                    return
                self.busy_since = time.monotonic()
                try:
                    result = svc._process(backend, job)
                finally:
                    self.busy_since = None
                if self.generation == svc._generation:
                    svc.results.put(result)
                else:
                    log.warning("Abandoned navigation worker finished: %s", result.describe())
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    log.debug("backend close failed", exc_info=True)


class NavigationService:
    def __init__(
        self,
        cfg: NavigationConfig,
        controller: DesktopController,
        backend_factory: Callable[[], NavigationBackend],
    ):
        self.cfg = cfg
        self.controller = controller
        self.backend_factory = backend_factory
        self.results: queue.Queue[NavigationResult] = queue.Queue()
        self._combos = {
            Gesture.NEXT: [parse_combo(c) for c in cfg.next_keys],
            Gesture.PREVIOUS: [parse_combo(c) for c in cfg.previous_keys],
        }
        self._generation = 0
        self._worker: _Worker | None = None

    def start(self) -> "NavigationService":
        self._worker = _Worker(self, self._generation)
        return self

    def request(self, gesture: Gesture, now: float | None = None) -> bool:
        """Queue a navigation. Returns False if the worker is busy (request dropped)."""
        now = time.monotonic() if now is None else now
        w = self._worker
        if w is None:
            raise RuntimeError("NavigationService not started")
        if w.busy_since is not None or not w.jobs.empty():
            if w.busy_since is not None and now - w.busy_since > STUCK_AFTER_S:
                log.warning("Navigation worker stuck for %.1f s; replacing it", now - w.busy_since)
                w.jobs.put(None)
                self._generation += 1
                self._worker = w = _Worker(self, self._generation)
            else:
                return False
        w.jobs.put(_Job(gesture, now, now + self.cfg.search_timeout_s))
        return True

    def poll(self) -> list[NavigationResult]:
        out = []
        while True:
            try:
                out.append(self.results.get_nowait())
            except queue.Empty:
                return out

    def _process(self, backend: NavigationBackend | None, job: _Job) -> NavigationResult:
        if backend is None:
            attempt = NavigationAttempt(Outcome.ERROR, "UI Automation unavailable")
        else:
            try:
                attempt = backend.navigate(job.gesture, job.deadline)
            except Exception as exc:
                log.debug("navigate failed", exc_info=True)
                attempt = NavigationAttempt(Outcome.ERROR, f"{type(exc).__name__}: {exc}")

        action = attempt.method if attempt.outcome is Outcome.ACTED else "none"
        if attempt.outcome in FALLBACK_OUTCOMES and self.cfg.fallback_to_keys:
            if time.monotonic() <= job.deadline + FALLBACK_GRACE_S:
                for combo in self._combos[job.gesture]:
                    self.controller.press_combo(combo)
                action = "keys"
            else:
                log.info("Skipping key fallback: request is stale")
        return NavigationResult(job.gesture, attempt, action, time.monotonic() - job.requested)

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.jobs.put(None)
            self._worker.thread.join(timeout=1.0)
            self._worker = None


def create_backend_factory(
    cfg: NavigationConfig, controller: DesktopController, dry_run: bool
) -> Callable[[], NavigationBackend]:
    def factory() -> NavigationBackend:
        import sys

        if sys.platform != "win32":
            raise NotImplementedError("UI Automation navigation is Windows-only for now")
        from .uia_windows import UIANavigator

        return UIANavigator(cfg, controller, dry_run=dry_run)

    return factory
