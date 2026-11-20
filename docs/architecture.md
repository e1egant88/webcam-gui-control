# Architecture

How Gesture Control is put together. The diagram shows components at module
level: what each one does, which data passes between them, and which thread it
runs on. GitHub renders the diagram; locally, use any Mermaid viewer.

```mermaid
flowchart TB
    %% ---------- process / start-up ----------
    subgraph START["Start-up · #95;#95;main#95;#95;.py · runtime.py"]
        direction LR
        CLI["CLI args<br/>--dry-run, --self-test, ..."]
        RT["runtime.py<br/>log file · single instance<br/>error boxes · restart loop"]
        ST["selftest.py<br/>--self-test checks"]
    end

    subgraph CONFIG["Configuration"]
        direction LR
        CFG["config.toml<br/>(project / next to exe)"]
        USR["settings.toml<br/>%APPDATA%, per user"]
        AC["config.py · AppConfig<br/>defaults → toml → user → CLI<br/>validated, shared by reference"]
        CFG --> AC
        USR --> AC
    end

    CLI --> RT
    RT --> AC
    RT -.-> ST
    AC ==> APP

    APP["app.py · App<br/>picks the front end"]

    %% ---------- input & perception ----------
    subgraph INPUT["Input · camera thread"]
        CAM["camera.py · Camera<br/>OpenCV webcam · mirror<br/>latest frame only"]
    end

    subgraph PERCEPTION["Perception · engine thread"]
        TRK["tracker.py · HandTracker<br/>MediaPipe Hand Landmarker<br/>21 landmarks"]
        GEO["hand_geometry.py<br/>palm centre · palm size<br/>open palm / fist / other"]
        OBS[/"HandObservation<br/>x, y, scale, pose, time"/]
        TRK --> GEO --> OBS
    end

    subgraph RECOGNITION["Recognition · engine thread"]
        GD["gestures.py · GestureDetector<br/>smoothing · time window · thresholds<br/>cooldown · re-arm · return-stroke filter"]
        ACT["activation.py<br/>PAUSED · IDLE · ARMING · ACTIVE<br/>dwell to arm · fist to disarm"]
        EV[/"GestureEvent<br/>scroll up/down · next/previous"/]
        GD --> EV
    end

    ENG["engine.py · Engine.process<br/>one frame in → Snapshot + UI events out"]
    TGT["targets.py<br/>app under cursor<br/>desktop / admin warnings"]

    CAM -- frame --> TRK
    OBS --> GD
    OBS --> ACT
    EV --> ENG
    ACT --> ENG
    ENG -.-> TGT

    %% ---------- actions ----------
    subgraph ACTIONS["Actions"]
        DSP["actions.py · ActionDispatcher<br/>gesture → action (fixed mapping)"]
        SCR["SmoothScroller<br/>eased wheel steps · scroller thread"]

        subgraph NAV["Next / Previous · navigation worker thread"]
            SVC["navigation/service.py<br/>deadline · stuck-worker swap<br/>key fallback"]
            CH["chain.py<br/>UIA first, OCR only if UIA saw nothing"]
            UIA["uia_windows.py<br/>UI Automation search (comtypes)<br/>Invoke or hit-tested click"]
            OCR["ocr_navigator.py<br/>screen_windows.py capture (mss)<br/>ocr_windows.py Windows OCR<br/>text_chunks.py labels"]
            SCO["scoring.py<br/>strict labels · blocked words<br/>ambiguity check"]
            SVC --> CH
            CH --> UIA
            CH --> OCR
            UIA --> SCO
            OCR --> SCO
        end

        subgraph CTRL["controllers/"]
            WIN["windows.py · WindowsController<br/>SendInput: wheel · keys · click"]
            DRY["dryrun.py · DryRunController<br/>log only"]
        end

        DSP -- vertical --> SCR
        DSP -- "horizontal (uia mode)" --> SVC
        DSP -- "horizontal (keys mode)" --> WIN
        SCR --> WIN
        SVC -- fallback keys --> WIN
        UIA -- click --> WIN
        OCR -- click --> WIN
    end

    ENG --> DSP

    OS[("Windows<br/>SendInput · UI Automation<br/>Windows OCR · RegisterHotKey")]
    WIN --> OS
    UIA --> OS
    OCR --> OS

    %% ---------- front ends ----------
    subgraph UI["Front ends · main thread"]
        QT["overlay/qt_app.py<br/>Qt event loop"]
        HUD["widgets.py · HUD<br/>camera · state · last action"]
        FRM["widgets.py · TargetFrame<br/>monitor under cursor"]
        HL["widgets.py · Highlight<br/>pressed button"]
        TRAY["tray.py<br/>pause · settings · quit"]
        SET["settings_dialog.py<br/>settings_schema.py · settings_store.py"]
        GEOM["geometry.py · win_styles.py<br/>physical ↔ logical px<br/>click-through · capture-hidden"]
        DBG["debug_view.py<br/>OpenCV debug window (optional)"]
        QT --> HUD
        QT --> FRM
        QT --> HL
        QT --> TRAY
        TRAY --> SET
        FRM --- GEOM
        HL --- GEOM
    end

    APP --> QT
    APP -.-> DBG
    ENG -- "Snapshot + UiEvents" --> QT
    SET -- "live values · restart" --> AC
    SET --> USR

    HK["hotkeys.py<br/>Ctrl+Alt+P · hotkey thread"]
    HK -- pause --> ACT
    TRAY -- pause --> ACT

    %% ---------- packaging ----------
    subgraph PKG["Packaging (build time)"]
        direction LR
        BLD["packaging/build.ps1"] --> SPEC["gesture_control.spec<br/>PyInstaller"] --> EXE["dist/GestureControl<br/>GestureControl.exe · gesture-control-cli.exe"]
    end
```

## Threads

| Thread | Runs | Talks to others through |
|---|---|---|
| Main (Qt) | overlay, tray, settings window | reads the latest `Snapshot`, drains UI events |
| Engine | tracker → detector → activation → dispatcher | `Snapshot` slot, event queue |
| Camera | `Camera` frame grabbing | latest-frame slot with a condition variable |
| Navigation worker | UI Automation / OCR search and pressing | job queue in, result queue out |
| Scroller | smooth wheel animation | animation list under a lock |
| Hotkey | `RegisterHotKey` message loop | calls `toggle_pause` |

## Main data types

| Type | Defined in | Produced by → consumed by |
|---|---|---|
| `HandObservation` | `types.py` | tracker → gesture detector, activation |
| `GestureEvent` | `types.py` | gesture detector → engine → dispatcher |
| `Snapshot`, `UiEvent` | `engine.py` | engine → front ends |
| `UICandidate`, `Rect` | `navigation/candidates.py` | UIA / OCR → scoring |
| `NavigationAttempt` / `NavigationResult` | `navigation/__init__.py`, `service.py` | navigators → service → engine |
| `AppConfig` | `config.py` | config files + CLI + settings window → every stage |
