# Gesture Control — webcam hand gestures for your desktop

Wave an open hand at your webcam to scroll, swipe left/right for previous/next.

* **Phase 1:** Windows gesture detection, smooth scrolling, arm/pause safety, and a debug view.
* **Phase 2:** left/right swipes find the real *Next*/*Previous* button or link
  in the foreground window with Windows UI Automation and press it. When no
  single clear target exists, they fall back to keys (default ←/→).
* **Phase 3:** for apps that expose no accessibility info, a local
  screenshot + Windows OCR fallback reads the window's visible labels.
* **Phase 4 (overlay):** a small click-through HUD shows state, the camera with
  your hand skeleton, and the last action. The control that was pressed gets a
  brief outline. A tray icon handles pause, settings, and quit.

| Gesture (open palm) | Action |
|---|---|
| Move down quickly | Scroll down |
| Move up quickly | Scroll up |
| Swipe right | Press the window's **Next** control (or → key) |
| Swipe left | Press the window's **Previous** control (or ← key) |
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

By default you get the **overlay**: a HUD in the bottom-right corner and a
**tray icon**. Left-click the tray icon to pause or resume. Right-click it for
the menu: pause, show/hide the overlay or camera, **Settings...**, open
config.toml, quit.

### Self-test
```powershell
python -m gesture_control --self-test
```
Checks the hand model, input, UI Automation, OCR, screen capture, the
overlay, the camera, and the hotkey, without sending any input. It prints
PASS / WARN / FAIL for each and exits non-zero if a required check fails. The
camera and hotkey only warn, because another app may legitimately be using them.

### Packaged Windows app
```powershell
pip install -e ".[dev,build]"
.\packaging\build.ps1 -Zip
```
This produces `dist\GestureControl\` (and a `.zip`) that runs on Windows 10/11
without Python. The build ends by running the packaged app's own self-test.
* **`GestureControl.exe`** starts the tray and overlay with no console window.
  Double-click it, or add a shortcut to `shell:startup` to run it at sign-in.
* **`gesture-control-cli.exe`** is the same app with a console, for
  `--self-test`, `--dry-run`, `-v`, and so on.
* **Files next to the exe:** `config.toml` and `models\hand_landmarker.task`.
  Your Settings-window changes still go to `%APPDATA%\GestureControl\settings.toml`.
* **Logs:** `%APPDATA%\GestureControl\logs\gesture-control.log`. Errors such as
  a missing camera appear in a message box.
* **One copy at a time:** starting it again while it's running shows "already
  running" instead of fighting over the camera and hotkey.

The build bundles MediaPipe's native library, the UI Automation wrappers, the
WinRT OCR bindings, and the Qt plugins. See
[packaging/gesture_control.spec](packaging/gesture_control.spec).

### Settings window
**Settings...** in the tray menu edits the common options in tabs: Gestures,
Activation, Scrolling, Next / Previous, Overlay, and Camera. Hover over a
label for an explanation.

* **Live:** most values apply as soon as you click Apply or OK, which is handy
  for tuning gesture sensitivity while you try it.
* **Restart (⟳):** values marked ⟳ are read at start-up. The window then
  offers **Restart now**, which restarts Gesture Control in place.
* **Where it's saved:** only the values that differ from `config.toml` go into
  your per-user file, `%APPDATA%\GestureControl\settings.toml`.
  `config.toml` and its comments are never rewritten.
* **Load order:** built-in defaults, then `config.toml`, then `settings.toml`,
  then command-line options. Command-line options such as `--dry-run` apply to
  that run only and are never saved.
* **Undo:** **Restore Defaults** followed by Apply removes your overrides.
  Start with `--no-user-settings` to ignore the file once. If the file is
  invalid, it's ignored with a warning and the app still starts.

Options:
* `--debug-window` adds the OpenCV window with live tuning numbers
  (`q`/`Esc` quits, `p` pauses).
* `--no-overlay` uses only that window.
* `--headless` shows no UI at all; quit with Ctrl+C.
* Also: `--camera N`, `--no-mirror`, `--always-active` (skip arming),
  `-c other.toml`, and `-v` (debug logs).

### The overlay
* **Click-through and focus-free:** the HUD and the highlight never take
  focus, and your mouse clicks and scrolls go straight through them to the
  window underneath.
* **Invisible to screenshots:** they are hidden from screen capture,
  including screen sharing and OCR. So OCR reads the app *under* the HUD, and
  your screen shares don't show it.
* **Highlight placement:** the outline maps physical pixels to Qt coordinates
  per monitor, so it lands correctly on mixed-DPI setups.
* **Settings:** the corner, opacity, and camera thumbnail are set in the
  Settings window (live) or under `[overlay]` in [config.toml](config.toml).

### Where the input goes
* **Scrolling** goes to the window **under the mouse cursor** (Windows'
  *Scroll inactive windows when I hover over them* setting, which is on by default).
  Put the cursor over the page you want to scroll. With several monitors, a
  **light blue frame** marks the monitor that will receive gestures. It follows
  the cursor and flashes when an action is sent. Turn it off with
  *Frame the target screen* in Settings (Overlay tab).
* **The HUD names the target app** for every scroll, e.g.
  `scroll -3.0 notches -> chrome.exe`. It warns when the cursor is over the
  desktop or taskbar (nothing to scroll), or over an app running as
  administrator. Windows blocks gesture input to admin apps unless Gesture
  Control also runs as administrator.
* **Next/Previous** acts on the **foreground** window. Click the target app
  once after starting. The overlay and debug window never take focus. After a
  left/right swipe, the frame jumps to that window's monitor for 1.5 s.
* Windows does not let a normal process send input to apps running as
  administrator. Run this tool elevated only if you need that.

## Next / Previous with UI Automation

On a left/right swipe, a background worker reads the **foreground window**
through Windows UI Automation (the accessibility API that screen readers use). It then:

1. **Searches** for buttons, links, split buttons, and menu items whose name or id
   contains `next`/`prev` or an arrow (`› » → ‹ « ←`). The filtering runs inside
   UIA, so even large web pages take well under 100 ms.
2. **Scores** each control with strict rules (see
   [scoring.py](src/gesture_control/navigation/scoring.py)):

   | Label | Score |
   |---|---|
   | `Next`, `Next ›`, `« Previous` | 100 |
   | `Next page`, `Next slide`, `Prev chapter` | 90 |
   | `Go to next page` | 85 |
   | `›`, `»` (arrow only) | 70 |
   | `Back` / `Forward` (only with `include_back_forward`) | 65 |
   | unnamed control with id like `nextBtn` | 60 |

   Labels like "Next steps for your career" or "Previous orders" are **rejected**,
   because a keyword followed by an unknown word is usually a content link.
   Buttons get +5, menu items −10. A control in the same row as its opposite
   (a pagination bar) gets +8.
3. **Refuses** controls that are disabled, off-screen, outside the window, or
   labelled with a blocked word (`delete`, `pay`, `submit`, `sign out`, ...).
   It also refuses when the scan is **ambiguous**: two *different* targets within
   15 points, like "Next chapter" and "Next page". Identical duplicates, such as
   pagination at the top and bottom, are fine. The one nearest the mouse cursor wins.
4. **Re-validates** the target just before acting: same foreground window, same
   name, still enabled and visible. Then it uses UIA **Invoke**, which needs no
   mouse movement. If Invoke isn't supported, it clicks the control's centre,
   but only if a hit-test confirms nothing covers it, and then puts your cursor back.
5. If there's no clear target, the search times out (1.5 s), or UIA fails, it
   presses the fallback keys instead. Each result is logged and shown in the
   debug window, for example
   `next => next: invoke 'Next ›' (link at 1766,397)  (93 ms)`.

`--dry-run` runs the whole search and logs what it *would* invoke or click,
without touching anything. Run with `-v` to see every candidate's score and
why each rejected control was rejected.

**Limits:** Windows blocks a non-admin process from controlling admin windows.
Chromium browsers turn on their accessibility tree when a UIA client first
asks, so on rare occasions the very first swipe on a page falls back to OCR or keys.

### Screenshot + OCR fallback

Some apps expose no usable accessibility info: games, canvas-drawn UIs, some
remote-desktop and video windows. When UI Automation finds **no relevant
control at all**, the worker:

1. Captures the foreground window **from the screen**. Gesture Control's own
   windows are blacked out first, and the debug window is also hidden from
   capture, so OCR never reads its own status text.
2. Runs **Windows' built-in OCR** (`Windows.Media.Ocr`). It's local, needs no
   model download, and takes about 200 ms for a full-HD window. The image is
   enlarged 1.5× first to help with small UI fonts.
3. Splits each text line at wide gaps, so a pagination bar like
   `Previous 1 2 3 Next` becomes separate labels. It then scores them with the
   **same strict rules** as UIA, including the blocked words and the ambiguity check.
4. Before clicking, it **re-checks**: it re-captures and re-reads the area
   around the label, confirms the window under the click point is the target
   window, and confirms the foreground window hasn't changed. Then it clicks
   and puts your cursor back.

OCR is **not** used when UIA found the control but refused it: when Next is
disabled (last page), labelled with a blocked word, or ambiguous. Accessibility
knows things a screenshot can't. OCR also can't tell whether a text label is
greyed out, and it can't read icon-only arrows that have no text.

OCR needs a Windows OCR language pack for your display language (English
normally has one). Set `ocr_language = "en-US"` to choose one explicitly. Set
`ocr_fallback = false` to turn this off.

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

The navigation tests cover the scoring rules with synthetic controls and the
background worker with a fake backend (fallback, timeouts, a stuck worker). A
live **UI Automation** test opens a real Win32 window with "‹ Previous",
"Next ›", and "Delete" buttons. It checks that the search finds only the first
two, that Invoke really presses them, and that disabled, ambiguous, and
expired-deadline cases do nothing. That test only ever presses buttons in its
own window and never moves your mouse.

The OCR tests read rendered pagination images: they check that prose and
blocked labels are never chosen and that small fonts work with upscaling. A
dry-run OCR test captures a real, briefly topmost Win32 window from the screen
and finds its Next and Previous buttons, without clicking anything.

The overlay tests briefly show the real HUD on your desktop. They check that it:
* is click-through, topmost, and never focused;
* is hidden from screen capture: a white window underneath still captures white;
* is not masked out of OCR;
* is seen through by both Win32 and UI Automation hit-tests.

They also check that the highlight lands within a few pixels of a given
physical rectangle. The engine tests run synthetic hands through the whole
pipeline (arming, scroll, keys, pause) without a camera.

The settings tests cover:
* the TOML writer round-trip (quotes, backslashes, non-ASCII);
* the load order of the settings layers;
* bad user files being ignored;
* the schema matching the real config fields;
* the Settings window itself: what applies live, what waits for a restart,
  that invalid key combos are rejected, and that a `--dry-run` from the
  command line is never saved.

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
| Swipe right on a page with a "Next" link | Logs `would invoke 'Next ...'` |
| Swipe right in Notepad | Logs `keys (not_found: no matching control)` |
| Debug window focused, swipe right | Logs `skipped: ... own window has focus` |

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

For a diagram of how these parts connect (data flow, threads, main data
types), see [docs/architecture.md](docs/architecture.md).

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
  engine.py         UI-independent pipeline (one frame -> Snapshot + UI events)
  settings_schema.py  what the Settings window shows (labels, ranges, live/restart)
  settings_store.py   per-user settings file: location, TOML writer, diff
  targets.py        which app is under the cursor (receives scrolls); admin/desktop checks
  runtime.py        packaged-app paths, log file, single instance, error boxes
  selftest.py       --self-test subsystem checks
packaging/
  build.ps1         one-command Windows build (+ self-test, optional zip)
  gesture_control.spec  PyInstaller spec (GUI + CLI executables)
  app.py            picks the front end: overlay, OpenCV window, or headless
  overlay/
    qt_app.py       engine thread + Qt main loop
    widgets.py      HUD and target highlight (click-through, capture-excluded)
    tray.py         tray icon and menu
    settings_dialog.py  Settings window (live apply, save, restart)
    geometry.py     physical -> logical coordinates per monitor (pure)
    win_styles.py   Win32 window styles, monitor list
  controllers/
    base.py         DesktopController interface + key-combo parsing
    windows.py      Windows SendInput adapter (ctypes)
    dryrun.py       logging-only controller
  navigation/
    candidates.py   OS-independent description of a UI control
    scoring.py      pure Next/Previous target selection rules
    uia_windows.py  Windows UI Automation search, re-validation, Invoke/click
    text_chunks.py  OCR words -> label candidates (pure)
    screen_windows.py  window screen capture with own-window masking
    ocr_windows.py  Windows.Media.Ocr wrapper
    ocr_navigator.py   screenshot + OCR fallback with re-check and hit-test
    chain.py        UIA first, OCR only when UIA saw nothing usable
    service.py      background worker, deadlines, key fallback
tests/              pytest suite: synthetic trajectories, scoring rules,
                    and a live UIA test against a real Win32 window
```

Only the camera, tracker, and debug window import OpenCV or MediaPipe. Only
`controllers/windows.py` and `hotkeys.py` touch Win32. A macOS port needs a
`MacOSController` (Quartz `CGEventCreateScrollWheelEvent` and keyboard events),
a hotkey implementation, and Camera and Accessibility permissions.

## Roadmap
- **Phase 2 (done):** UI Automation Next/Previous with key fallback.
- **Phase 3 (done):** local screenshot + Windows OCR fallback. Not chosen yet:
  OmniParser (catches icon-only arrows, but on CPU it takes seconds per swipe
  and needs a large PyTorch download; its detector weights are AGPL), or a
  cloud vision model (screen content leaves the machine).
- **Phase 4:** overlay, HUD, highlight, tray, Settings window, and the
  packaged Windows app are done. Still to do: the macOS adapter.
- **Phase 4:** PySide6 click-through overlay, settings UI, packaging, macOS adapter.
