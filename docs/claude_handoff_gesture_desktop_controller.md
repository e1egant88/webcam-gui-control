# Claude Handoff — AI Hand-Gesture Desktop Controller

**Conversation date:** 19 November 2026  
**Purpose:** Continue implementing the project in Claude from this ChatGPT session.  
**Status:** Architecture and candidate libraries discussed; no application codebase has been built in this conversation.

## Original user request (verbatim)

> i want to make a tool to help me scroll up and down, it should be a layer has the full view of my screen, and when I wave my hands up/down, it scroll up/down. If I wave my hands left/right, it should auto detect the last/next button on the screen and press it.
>
> 1. I need the method to detect gesture with my webcam
> 2. I need the tool to capture/monitor the screen
> 3. I hope it can be used in macos and windows (start from windows)
> 4. Which AI library can I use to detect the last/next button on the screen and interactive like press the button.

## Goal and constraints

Build a desktop-wide, webcam-driven controller. An always-on-top, transparent, click-through overlay covers the screen for visual feedback without blocking normal interactions. Webcam hand movement triggers scrolling or screen-aware previous/next navigation. Prioritize Windows as MVP and retain a path to macOS. The tool should work across browsers, PDF readers and ordinary desktop applications where accessibility/input permissions allow.

## Proposed stack

| Concern | Suggested library/tool | Notes |
|---|---|---|
| Webcam frames | OpenCV | Real-time capture |
| Hand recognition | Google MediaPipe Hand Landmarker | 21 hand landmarks; track palm centre over time |
| Gesture classification | Python movement/temporal logic | Directional waves/swipes require tracking, debouncing and smoothing; no custom ML training initially |
| Screen capture | MSS | Cross-platform capture; prefer active-window captures for navigation |
| Transparent overlay | PySide6 / Qt | Always-on-top, click-through; show status and optional target highlights |
| Windows semantic UI | Windows UI Automation via pywinauto or UIA API | First-choice for finding actual Next/Previous buttons |
| Visual UI parsing | Microsoft OmniParser | Screenshot-based identification of UI elements where accessibility metadata is insufficient |
| Ambiguous visual semantics | Optional VLM | Determine which visual element is the appropriate Next/Previous control |
| Desktop actions | PyAutoGUI / OS-specific adapters | Scroll, click, keyboard simulation |
| Browser-only enhancement | Playwright | Useful only if target browser session/page can be connected or instrumented |

Useful reference: https://github.com/microsoft/OmniParser

## Suggested execution flow

```text
Webcam -> OpenCV -> MediaPipe -> palm landmark trajectory
                                |
                                v
                    Gesture classification and cooldown
                                |
                  +-------------+-------------+
                  |                           |
             Vertical wave               Horizontal swipe
                  |                           |
          Scroll foreground app       Resolve navigation target
                                              |
                                    Windows UI Automation first
                                              |
                                  If unsuccessful -> screenshot
                                              |
                                  OmniParser (+ optional VLM)
                                              |
                                  Validate & click target
```

## Proposed gesture mapping

- Open palm moves up: scroll up.
- Open palm moves down: scroll down.
- Open palm moves left: Previous.
- Open palm moves right: Next.
- Fist/no hand: no action.
- Allow user to reverse horizontal mapping.
- Account for mirrored webcam orientation. Prevent repeated accidental activation with temporal smoothing, movement thresholds, activation gesture and cooldown.

### Sketch of classification logic

```python
dx = current_x - previous_x
dy = current_y - previous_y

if abs(dx) > threshold and abs(dx) > abs(dy) * 1.5:
    action = 'NEXT' if dx > 0 else 'PREVIOUS'
elif abs(dy) > threshold and abs(dy) > abs(dx) * 1.5:
    action = 'SCROLL_DOWN' if dy > 0 else 'SCROLL_UP'
```

**Important:** This is a conceptual sketch, not production code; ensure direction is consistent with camera mirroring and coordinate conventions, and use multi-frame displacement rather than frame-to-frame noise.

## UI button identification strategy

1. Inspect the **foreground application** via Windows UI Automation to locate accessible controls labeled `Next`, `Previous`, `Next Page`, etc. Match semantic role, visibility, state, screen bounds, and context. Prefer an accessibility `Invoke` action where supported rather than simulating a coordinate click.
2. If no reliable target exists, capture the appropriate screen/window using MSS, parse with OmniParser, and optionally use a local vision-language model to choose among detected controls.
3. Reject low-confidence or ambiguous matches; optionally highlight the chosen target or request confirmation. Revalidate the target immediately before acting.
4. Do not run OmniParser continuously: only on valid left/right gestures, with cautious caching.
5. Screen-based controls can fail in games, inaccessible apps, custom canvas UIs or security-restricted windows. Avoid bypassing such restrictions.

Example *illustrative*, **not guaranteed native OmniParser output**:

```json
{
  "action": "NEXT",
  "target": "Next button",
  "center": {"x": 1250, "y": 720},
  "confidence": 0.94
}
```

Do not treat that illustrative confidence number as calibrated.

## Initial Python API boundary

```python
class DesktopController:
    def scroll(self, amount: int):
        raise NotImplementedError

    def find_button(self, direction: str):
        raise NotImplementedError

    def click(self, x: int, y: int):
        raise NotImplementedError
```

Implement `WindowsController` first, `MacOSController` later. Gesture engine and UI target resolver should not depend directly on OS specifics.

## Illustrative commands / snippets from session

```bash
pip install mediapipe opencv-python pyautogui numpy
```

```python
import pyautogui
pyautogui.scroll(3)   # scroll up
pyautogui.scroll(-3)  # scroll down
```

The prior answer also included a **conceptual** `pywinauto` example for enumerating buttons. Validate actual API calls and active-window selection when implementing; do not assume the sketch is production-ready.

## Roadmap agreed in discussion

1. **Phase 1:** Windows webcam gestures and robust up/down scrolling, with pause mode, tuning and no accidental repeats.
2. **Phase 2:** Screen-aware previous/next via Windows UI Automation and selection heuristics.
3. **Phase 3:** OmniParser + optional VLM visual fallback for inaccessible or icon-only UI controls.
4. **Phase 4:** PySide6 desktop overlay, settings, packaging, and macOS adapter.

The overlay can be implemented earlier if needed for debugging; these phases describe incremental capabilities, not a rigid dependency order.

## Safety, reliability and platform considerations

- Overlay should be click-through and usually excluded from screen capture.
- Prefer capturing active window, and capture only when UI analysis is needed.
- Require intentional gestures; include emergency pause hotkey.
- Restrict automation around destructive or sensitive actions; do not auto-click ambiguous UI targets.
- Handle multi-monitor coordinates, DPI scaling and changing windows.
- Elevated Windows apps, protected displays and some full-screen apps can restrict capture and input.
- macOS requires Camera, Screen Recording and Accessibility permissions; uses macOS Accessibility API rather than UIA.
- No cloud dependency required for Phase 1; evaluate local models for privacy and latency.

## Suggested next request for Claude

> Act as a senior Python desktop automation engineer. Using this handoff, start implementing **Phase 1** of a production-minded Windows-first application. Provide a runnable project structure and complete files for webcam acquisition, MediaPipe hand landmark tracking, temporal directional gesture detection, smooth scroll control, debug visualization, activation/pause mechanism, configuration, and a README. Keep core logic separate from Windows-specific adapters so macOS can be added later. Explain how to run and test the MVP, especially camera mirroring, threshold tuning, debounce, and avoiding accidental swipes. Do not add OmniParser or a full overlay until basic gestures are reliable.

---

This file is a faithful **technical handoff/summary** of the session, **not a word-for-word ChatGPT transcript**. The initial user request above is quoted verbatim, and code snippets are illustrative excerpts or adaptations from the prior answer.
