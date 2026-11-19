import threading
import time

import pytest

from gesture_control.config import NavigationConfig
from gesture_control.controllers import DryRunController
from gesture_control.navigation import NavigationAttempt, Outcome
from gesture_control.navigation import service as service_mod
from gesture_control.navigation.service import NavigationService
from gesture_control.types import Gesture


class FakeBackend:
    def __init__(self, attempt=None, delay=0.0, block: threading.Event | None = None):
        self.attempt = attempt or NavigationAttempt(Outcome.ACTED, "ok", "invoke", "'Next'")
        self.delay = delay
        self.block = block
        self.calls = []
        self.closed = False

    def navigate(self, direction, deadline):
        self.calls.append(direction)
        if self.block is not None:
            self.block.wait(5)
        time.sleep(self.delay)
        return self.attempt

    def close(self):
        self.closed = True


def wait_results(svc, n=1, timeout=3.0):
    out = []
    end = time.monotonic() + timeout
    while len(out) < n and time.monotonic() < end:
        out += svc.poll()
        time.sleep(0.01)
    return out


def make(backend=None, factory=None, **cfg):
    ctrl = DryRunController()
    svc = NavigationService(NavigationConfig(**cfg), ctrl, factory or (lambda: backend)).start()
    return svc, ctrl


def keys(ctrl):
    return [c[1] for c in ctrl.calls if c[0] == "keys"]


def test_acted_no_fallback():
    svc, ctrl = make(FakeBackend())
    assert svc.request(Gesture.NEXT)
    (res,) = wait_results(svc)
    assert res.attempt.outcome is Outcome.ACTED and res.action == "invoke"
    assert keys(ctrl) == []
    svc.stop()


@pytest.mark.parametrize("outcome", [Outcome.NOT_FOUND, Outcome.AMBIGUOUS, Outcome.TIMEOUT, Outcome.ERROR])
def test_fallback_to_keys(outcome):
    svc, ctrl = make(FakeBackend(NavigationAttempt(outcome, "x")), previous_keys=["alt+left"])
    svc.request(Gesture.PREVIOUS)
    (res,) = wait_results(svc)
    assert res.action == "keys"
    assert keys(ctrl) == [("alt", "left")]
    svc.stop()


def test_no_fallback_when_disabled():
    svc, ctrl = make(FakeBackend(NavigationAttempt(Outcome.NOT_FOUND, "x")), fallback_to_keys=False)
    svc.request(Gesture.NEXT)
    (res,) = wait_results(svc)
    assert res.action == "none" and keys(ctrl) == []
    svc.stop()


def test_skipped_does_not_fall_back():
    svc, ctrl = make(FakeBackend(NavigationAttempt(Outcome.SKIPPED, "own window")))
    svc.request(Gesture.NEXT)
    (res,) = wait_results(svc)
    assert res.action == "none" and keys(ctrl) == []
    svc.stop()


def test_backend_exception_becomes_error_with_fallback():
    class Boom(FakeBackend):
        def navigate(self, direction, deadline):
            raise RuntimeError("COM exploded")

    svc, ctrl = make(Boom())
    svc.request(Gesture.NEXT)
    (res,) = wait_results(svc)
    assert res.attempt.outcome is Outcome.ERROR and "COM exploded" in res.attempt.detail
    assert keys(ctrl) == [("right",)]
    svc.stop()


def test_backend_unavailable_uses_keys():
    def factory():
        raise OSError("no UIA")

    svc, ctrl = make(factory=factory)
    svc.request(Gesture.NEXT)
    (res,) = wait_results(svc)
    assert res.attempt.outcome is Outcome.ERROR and res.action == "keys"
    svc.stop()


def test_busy_worker_drops_requests():
    gate = threading.Event()
    backend = FakeBackend(block=gate)
    svc, _ = make(backend)
    assert svc.request(Gesture.NEXT)
    time.sleep(0.05)
    assert not svc.request(Gesture.NEXT)  # still busy
    gate.set()
    assert len(wait_results(svc)) == 1
    assert backend.calls == [Gesture.NEXT]
    svc.stop()


def test_stale_result_skips_fallback():
    # The search returns NOT_FOUND long after the deadline: no late key press.
    svc, ctrl = make(
        FakeBackend(NavigationAttempt(Outcome.NOT_FOUND, "x"), delay=0.3), search_timeout_s=0.05
    )
    svc.request(Gesture.NEXT)
    old = service_mod.FALLBACK_GRACE_S
    service_mod.FALLBACK_GRACE_S = 0.0
    try:
        (res,) = wait_results(svc)
    finally:
        service_mod.FALLBACK_GRACE_S = old
    assert res.action == "none" and keys(ctrl) == []
    svc.stop()


def test_stuck_worker_is_replaced(monkeypatch):
    monkeypatch.setattr(service_mod, "STUCK_AFTER_S", 0.1)
    gate = threading.Event()
    stuck = FakeBackend(block=gate)
    good = FakeBackend()
    backends = iter([stuck, good])
    svc, _ = make(factory=lambda: next(backends))
    svc.request(Gesture.NEXT)
    time.sleep(0.3)
    assert svc.request(Gesture.PREVIOUS)  # replaces the stuck worker
    (res,) = wait_results(svc)
    assert res.gesture is Gesture.PREVIOUS
    gate.set()  # old worker finishes; its result must be discarded
    time.sleep(0.1)
    assert svc.poll() == []
    svc.stop()
