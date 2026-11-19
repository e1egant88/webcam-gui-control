# Gesture Control — webcam hand gestures for your desktop

Wave an open hand at your webcam to scroll, swipe left/right for previous/next.
**Phase 1** (this code): Windows, robust gesture detection, smooth scrolling,
arm/pause safety, debug view. Left/right currently sends configurable keys
(default ←/→); Phase 2 will find real *Next/Previous* buttons with UI Automation.

| Gesture (open palm) | Action |
|---|---|
| Move down quickly | Scroll down |
| Move up quickly | Scroll up |
| Swipe right | Next (default: → key) |
| Swipe left | Previous (default: ← key) |
| Hold still ~0.6 s | **Arm** (start accepting gestures) |
| Hold a fist ~0.4 s | **Disarm** |
| `Ctrl+Alt+P` (anywhere) | Pause / resume (emergency stop) |

Moving a fist or any non-open hand never does anything.

## Install and run

Requires Windows 10/11, Python 3.11+, and a webcam.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Run it in dry-run mode first. It detects and logs gestures but sends no input:

```powershell
python -m gesture_control --dry-run
```

When the gestures behave the way you want, run it for real:

```powershell
python -m gesture_control
```

The first run downloads the MediaPipe hand model (~8 MB) to
`models/hand_landmarker.task`.

Options: `--camera N`, `--no-mirror`, `--headless` (no debug window; quit with
Ctrl+C), `--always-active` (skip arming), `-c other.toml`, `-v` (debug logs).
In the debug window: `q`/`Esc` quits, `p` pauses.

### Where the input goes
* **Scrolling** goes to the window **under the mouse cursor** (Windows'
  *Scroll inactive windows when I hover over them* setting, which is on by default).
  Put the cursor over the page you want to scroll.
* **Next/Previous keys** go to the **foreground** window. Click the target app
  once after starting. The debug window stays on top but doesn't take focus.
* Windows does not let a normal process send input to apps running as
  administrator. Run this tool elevated only if you need that.

## Using it well

1. Sit about 40–80 cm from the camera with your hand clearly in frame.
2. Raise an **open palm** with fingers spread and hold it still. The banner shows
   `ARMING nn%` and then `ACTIVE`.
3. Make **quick, deliberate strokes**, roughly one to two palm-lengths in under
   ⅓ s. Slow drifting is ignored on purpose.
4. To keep scrolling, **paddle**: stroke down, return up, stroke down again.
   Each down stroke scrolls. The return strokes are ignored.
5. Drop your hand out of view for 1.5 s, or hold a fist, to disarm.

## Testing and tuning

### Automated tests
```powershell
pytest
```
The tests feed synthetic hand trajectories (with timestamps) through the gesture
engine. They check basic swipes, slow drift, jitter, diagonals, fist movement,
the hand entering the frame, return strokes, one long stroke firing only once,
paddling, cooldowns, distance invariance, arming and disarming, smooth-scroll
totals, and key/config parsing. No camera is needed.

### Manual checklist with the camera (use `--dry-run`)
| Check | Expected |
|---|---|
| Move your hand to **your** right | Trail moves right in the preview, logs `next`. If it logs `previous`, set `camera.mirror` or `gestures.invert_horizontal`. |
| Move hand down | Logs `scroll_down` |
| Swipe right, then bring hand back | Only **one** `next` |
| Paddle down 4 times | 4× `scroll_down`, no `scroll_up` |
| Raise hand into view quickly | Nothing fires (`settling`) |
| Wave a fist around | Nothing fires |
| Wave slowly / hover | Nothing fires |
| Hand out of view 2 s | `State: IDLE` |
| `Ctrl+Alt+P` | `State: PAUSED`, then again → resumes (re-arm needed) |

### Camera mirroring
`camera.mirror = true` (the default) flips the image like a mirror, so the
preview and gesture directions match **your** left and right. If your camera
driver already mirrors the image, directions come out reversed. Set
`mirror = false`, or keep it and set `gestures.invert_horizontal = true`.
`invert_vertical` swaps scroll directions if you prefer "push the page" style.

### Reading the debug window
The bottom bar shows live tuning numbers:
* `pose`: open_palm / fist / other, plus how many fingers count as extended.
  If an open hand flickers to `other`, lower `tracker.open_palm_min_fingers` to 3.
* `dx`, `dy`: the current stroke length in **palm sizes** (wrist to middle
  knuckle). Palm units make the thresholds independent of your distance from the camera.
* `speed`: stroke speed in palm sizes per second.
* The progress bar fills as the stroke approaches the distance threshold.
* The reason text says why a stroke did not fire: `too slow`, `diagonal`,
  `cooldown`, `return stroke`, `settling`, or `waiting to re-arm`.

Every fired gesture is also logged with its numbers, for example
`scroll_down -> scroll -3.0 notches (dx=+0.05 dy=+1.12 palms, 160 ms, speed=7.0/s)`.
Use these numbers to set thresholds from your own movements.

### Tuning knobs (`config.toml`)
| Symptom | Adjust |
|---|---|
| Swipes not detected | lower `min_distance_*` or `min_speed`, or raise `window_s` |
| Accidental triggers | raise `min_speed`, `min_distance_*`, `dominance_ratio` |
| Returning the hand fires the opposite action | raise `return_suppress_s` |
| Double `next` | raise `cooldown_horizontal_s` |
| Paddling feels sluggish | lower `cooldown_vertical_s` |
| Scroll too short or long | `scroll.notches_per_swipe`, `max_speed_multiplier` |
| An app ignores scrolling | `scroll.high_resolution = false` |
| Preview jittery / laggy | `smoothing_alpha` (lower is smoother but adds lag) |
| Arming too easy or hard | `activation.arm_hold_s`, `still_speed` |

### How accidental swipes are prevented
1. **Arming:** nothing executes until you hold an open palm still.
2. **Pose gate:** only an open palm is tracked. Other poses reset the stroke history.
3. **Settle:** movement in the first 0.25 s after the hand appears is ignored.
4. **Distance + speed + dominance:** a stroke must be long, fast, and mostly along one axis.
5. **Cooldown:** a short pause after each event.
6. **Re-arm:** after an event, the hand must slow down or reverse before the
   next one, so one long stroke can't fire twice.
7. **Return suppression:** the opposite direction is blocked for 0.7 s after an event.
8. **Global pause hotkey** and fist-to-disarm.

## Project layout

```
src/gesture_control/
  types.py          data types (no OS / CV dependencies)
  config.py         typed config + TOML loading/validation
  hand_geometry.py  landmarks -> palm centre, palm size, open/fist pose
  gestures.py       temporal swipe detector (pure logic, unit-tested)
  activation.py     PAUSED / IDLE / ARMING / ACTIVE state machine
  actions.py        gesture -> action mapping, smooth scroll animator
  camera.py         threaded OpenCV capture (latest frame only, mirroring)
  tracker.py        MediaPipe Hand Landmarker (Tasks API) wrapper
  hotkeys.py        global pause hotkey (Win32 RegisterHotKey)
  debug_view.py     OpenCV debug window
  app.py            main loop
  controllers/
    base.py         DesktopController interface + key-combo parsing
    windows.py      Windows SendInput adapter (ctypes)
    dryrun.py       logging-only controller
tests/              pytest suite with synthetic trajectories
```

Only the camera, tracker, and debug window import OpenCV or MediaPipe. Only
`controllers/windows.py` and `hotkeys.py` touch Win32. A macOS port needs a
`MacOSController` (Quartz `CGEventCreateScrollWheelEvent` and keyboard events),
a hotkey implementation, and Camera and Accessibility permissions.

## Roadmap
- **Phase 2:** `navigation.mode = "uia"`. Use Windows UI Automation to find
  Next/Previous buttons in the foreground window and invoke them, falling back to keys.
- **Phase 3:** OmniParser or a VLM screenshot fallback for inaccessible UIs.
- **Phase 4:** PySide6 click-through overlay, settings UI, packaging, macOS adapter.
