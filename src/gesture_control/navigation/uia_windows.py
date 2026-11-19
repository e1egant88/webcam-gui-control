"""Find and activate Next/Previous controls with Windows UI Automation.

All COM objects are created and used on the thread that constructs
``UIANavigator`` (the navigation worker thread); never share it across threads.

Search strategy (one cross-process round trip):
* scope: the foreground top-level window only;
* condition: control type is Button / Hyperlink / SplitButton / MenuItem AND
  (name or AutomationId contains a navigation keyword or arrow) - filtering
  happens inside UIA, so huge web pages stay fast;
* all properties needed for scoring are fetched with a cache request.
Then the pure scorer picks a target, which is re-validated (live properties,
same foreground window, hit-test for clicks) immediately before acting.
"""

from __future__ import annotations

import ctypes
import logging
import os
import time
from ctypes import wintypes

import comtypes
import comtypes.client

from ..config import NavigationConfig
from ..controllers.base import DesktopController
from ..types import Gesture
from . import NavigationAttempt, Outcome
from .candidates import ControlKind, Rect, UICandidate
from .scoring import NEXT_ARROWS, PREV_ARROWS, ScoringOptions, choose_target

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
GA_ROOT = 2
RPC_E_CHANGED_MODE = -2147417850

# Substrings searched inside UIA (case-insensitive). Scoring does the real work.
NAME_KEYWORDS = ("next", "prev", *NEXT_ARROWS, *PREV_ARROWS)
BACK_FORWARD_KEYWORDS = ("back", "forward")
ID_KEYWORDS = ("next", "prev")

_UIA = None


def _uia_module():
    global _UIA
    if _UIA is None:
        _UIA = comtypes.client.GetModule("UIAutomationCore.dll")
    return _UIA


def foreground_window() -> int:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _tuple(r: Rect) -> tuple[int, int, int, int]:
    return r.as_tuple()


def _rect(r) -> Rect:
    return Rect(int(r.left), int(r.top), int(r.right), int(r.bottom))


class UIANavigator:
    def __init__(self, cfg: NavigationConfig, controller: DesktopController, dry_run: bool = False):
        # The worker thread is fresh, so MTA (recommended for UIA clients)
        # normally succeeds. If COM is already initialised on this thread in
        # another mode (comtypes does STA on import), just use that.
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            self._owns_com = True
        except OSError as exc:
            if getattr(exc, "winerror", None) != RPC_E_CHANGED_MODE:
                raise
            self._owns_com = False
        self.cfg = cfg
        self.controller = controller
        self.dry_run = dry_run
        UIA = self.UIA = _uia_module()
        cls = getattr(UIA, "CUIAutomation8", UIA.CUIAutomation)
        self.uia = comtypes.client.CreateObject(cls, interface=UIA.IUIAutomation)
        self.opts = ScoringOptions(
            min_score=cfg.min_score,
            ambiguity_margin=cfg.ambiguity_margin,
            include_back_forward=cfg.include_back_forward,
            extra_next_names=tuple(cfg.extra_next_names),
            extra_previous_names=tuple(cfg.extra_previous_names),
            blocked_words=tuple(cfg.blocked_words),
        )
        self._condition = self._build_condition()
        self._cache = self._build_cache_request()
        self._kinds = {
            UIA.UIA_ButtonControlTypeId: ControlKind.BUTTON,
            UIA.UIA_HyperlinkControlTypeId: ControlKind.LINK,
            UIA.UIA_SplitButtonControlTypeId: ControlKind.SPLIT_BUTTON,
            UIA.UIA_MenuItemControlTypeId: ControlKind.MENU_ITEM,
        }

    # ------------------------------------------------------------ setup
    def _any_of(self, conditions):
        cond = conditions[0]
        for c in conditions[1:]:
            cond = self.uia.CreateOrCondition(cond, c)
        return cond

    def _build_condition(self):
        UIA, uia = self.UIA, self.uia
        types = [
            uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, t)
            for t in (
                UIA.UIA_ButtonControlTypeId,
                UIA.UIA_HyperlinkControlTypeId,
                UIA.UIA_SplitButtonControlTypeId,
                UIA.UIA_MenuItemControlTypeId,
            )
        ]
        flags = UIA.PropertyConditionFlags_IgnoreCase | UIA.PropertyConditionFlags_MatchSubstring
        words = list(NAME_KEYWORDS) + list(self.cfg.extra_next_names) + list(self.cfg.extra_previous_names)
        if self.cfg.include_back_forward:
            words += BACK_FORWARD_KEYWORDS
        text = [uia.CreatePropertyConditionEx(UIA.UIA_NamePropertyId, w, flags) for w in words]
        text += [uia.CreatePropertyConditionEx(UIA.UIA_AutomationIdPropertyId, w, flags) for w in ID_KEYWORDS]
        text += [uia.CreatePropertyConditionEx(UIA.UIA_HelpTextPropertyId, w, flags) for w in ID_KEYWORDS]
        return uia.CreateAndCondition(self._any_of(types), self._any_of(text))

    def _build_cache_request(self):
        UIA = self.UIA
        req = self.uia.CreateCacheRequest()
        for prop in (
            UIA.UIA_NamePropertyId,
            UIA.UIA_ControlTypePropertyId,
            UIA.UIA_BoundingRectanglePropertyId,
            UIA.UIA_IsEnabledPropertyId,
            UIA.UIA_IsOffscreenPropertyId,
            UIA.UIA_AutomationIdPropertyId,
            UIA.UIA_ClassNamePropertyId,
            UIA.UIA_HelpTextPropertyId,
            UIA.UIA_IsInvokePatternAvailablePropertyId,
        ):
            req.AddProperty(prop)
        return req

    # ------------------------------------------------------------ search
    def find_candidates(self, hwnd: int) -> tuple[list[UICandidate], Rect]:
        UIA = self.UIA
        root = self.uia.ElementFromHandle(hwnd)
        window = _rect(root.CurrentBoundingRectangle)
        found = root.FindAllBuildCache(UIA.TreeScope_Descendants, self._condition, self._cache)
        out: list[UICandidate] = []
        for i in range(found.Length if found else 0):
            e = found.GetElement(i)
            try:
                out.append(
                    UICandidate(
                        name=e.CachedName or "",
                        kind=self._kinds.get(e.CachedControlType, ControlKind.OTHER),
                        rect=_rect(e.CachedBoundingRectangle),
                        enabled=bool(e.CachedIsEnabled),
                        offscreen=bool(e.CachedIsOffscreen),
                        automation_id=e.CachedAutomationId or "",
                        class_name=e.CachedClassName or "",
                        help_text=e.CachedHelpText or "",
                        invokable=bool(e.GetCachedPropertyValue(UIA.UIA_IsInvokePatternAvailablePropertyId)),
                        handle=e,
                    )
                )
            except comtypes.COMError as exc:  # element vanished mid-read
                log.debug("Skipping element: %s", exc)
        return out, window

    # ------------------------------------------------------------ main entry
    def navigate(self, direction: Gesture, deadline: float, hwnd: int | None = None) -> NavigationAttempt:
        explicit = hwnd is not None
        hwnd = hwnd if explicit else foreground_window()
        if not hwnd:
            return NavigationAttempt(Outcome.SKIPPED, "no foreground window")
        if not explicit and window_pid(hwnd) == os.getpid():
            return NavigationAttempt(
                Outcome.SKIPPED, "Gesture Control's own window has focus - click the app to control"
            )

        t0 = time.monotonic()
        try:
            candidates, window = self.find_candidates(hwnd)
        except comtypes.COMError as exc:
            # The window doesn't expose UI Automation properly; let OCR try.
            return NavigationAttempt(Outcome.ERROR, f"UIA unavailable for window: {exc}", visual_fallback_ok=True)
        elapsed = time.monotonic() - t0
        log.debug("UIA search: %d candidates in %.0f ms", len(candidates), elapsed * 1000)
        if time.monotonic() > deadline:
            return NavigationAttempt(Outcome.TIMEOUT, f"UIA search took {elapsed * 1000:.0f} ms")

        from ..controllers.windows import get_cursor_pos

        sel = choose_target(candidates, direction, window, self.opts, cursor=get_cursor_pos())
        for c, why in sel.rejected:
            log.debug("  rejected %s: %s", c.describe(), why)
        for s in sel.ranked[:5]:
            log.debug("  %3d %s [%s]", s.score, s.candidate.describe(), ", ".join(s.reasons))
        if sel.target is None:
            outcome = Outcome.AMBIGUOUS if sel.reason.startswith("ambiguous") else Outcome.NOT_FOUND
            # Only look at pixels when accessibility saw nothing relevant. If it
            # found a Next that is disabled/blocked, OCR must not override that.
            deliberate = any(why in ("disabled", "blocked word") for _, why in sel.rejected)
            visual_ok = outcome is Outcome.NOT_FOUND and not sel.ranked and not deliberate
            return NavigationAttempt(outcome, sel.reason, visual_fallback_ok=visual_ok)

        target = sel.target.candidate
        problem = self._revalidate(target, hwnd, explicit)
        if problem:
            return NavigationAttempt(Outcome.NOT_FOUND, f"{target.describe()}: {problem}")
        if time.monotonic() > deadline:
            return NavigationAttempt(Outcome.TIMEOUT, "deadline passed before acting")
        return self._activate(target, sel.target.score)

    def _revalidate(self, c: UICandidate, hwnd: int, explicit: bool) -> str:
        if not explicit and foreground_window() != hwnd:
            return "foreground window changed"
        e = c.handle
        try:
            if (e.CurrentName or "") != c.name:
                return "name changed"
            if not e.CurrentIsEnabled:
                return "became disabled"
            if e.CurrentIsOffscreen:
                return "went off-screen"
            if _rect(e.CurrentBoundingRectangle).empty:
                return "no longer visible"
        except comtypes.COMError:
            return "element no longer available"
        return ""

    def _activate(self, c: UICandidate, score: int) -> NavigationAttempt:
        method = self.cfg.activation_method
        use_invoke = method == "invoke" or (method == "auto" and c.invokable)
        label = f"{c.describe()} score {score}"
        if use_invoke:
            if not c.invokable:
                return NavigationAttempt(Outcome.NOT_FOUND, f"{label} does not support Invoke")
            if self.dry_run:
                return NavigationAttempt(Outcome.ACTED, label, "would invoke", c.describe(), rect=_tuple(c.rect))
            pattern = c.handle.GetCurrentPattern(self.UIA.UIA_InvokePatternId)
            pattern.QueryInterface(self.UIA.IUIAutomationInvokePattern).Invoke()
            return NavigationAttempt(Outcome.ACTED, label, "invoke", c.describe(), rect=_tuple(c.rect))

        x, y = _rect(c.handle.CurrentBoundingRectangle).center
        if not self._hit_test(c, x, y):
            return NavigationAttempt(Outcome.NOT_FOUND, f"{label} is covered at ({x},{y})")
        if self.dry_run:
            return NavigationAttempt(Outcome.ACTED, label, "would click", c.describe(), rect=_tuple(c.rect))
        self.controller.click(x, y, restore_cursor=self.cfg.restore_cursor)
        return NavigationAttempt(Outcome.ACTED, label, "click", c.describe(), rect=_tuple(c.rect))

    def _hit_test(self, c: UICandidate, x: int, y: int) -> bool:
        """True if the element at (x, y) is the target or inside it."""
        try:
            hit = self.uia.ElementFromPoint(self.UIA.tagPOINT(x, y))
            walker = self.uia.RawViewWalker
            for _ in range(8):
                if hit is None:
                    return False
                if self.uia.CompareElements(hit, c.handle):
                    return True
                hit = walker.GetParentElement(hit)
        except comtypes.COMError:
            return False
        return False

    def close(self) -> None:
        self.uia = None
        self._condition = self._cache = None
        if self._owns_com:
            comtypes.CoUninitialize()
