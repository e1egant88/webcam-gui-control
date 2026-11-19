<#
.SYNOPSIS
  Build the Windows app folder dist\GestureControl\ (and optionally a .zip).

.EXAMPLE
  .\packaging\build.ps1            # build + self-test
  .\packaging\build.ps1 -Zip       # also create dist\GestureControl-<version>.zip
  .\packaging\build.ps1 -Clean     # wipe build\ and dist\ first
#>
param(
    [switch]$Clean,
    [switch]$Zip,
    [switch]$SkipSelfTest
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Virtual environment not found. Run: python -m venv .venv; .venv\Scripts\pip install -e "".[dev,build]""" }

Push-Location $root
try {
    if ($Clean) { Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue }

    Write-Host "== Preparing build inputs"
    # 1. comtypes wrappers for UI Automation (bundled instead of generated at runtime)
    & $py -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')"
    if ($LASTEXITCODE) { throw "comtypes wrapper generation failed" }
    # 2. hand model (shipped next to the exe; avoids a download on first run)
    & $py -c "from pathlib import Path; from gesture_control.config import TrackerConfig; from gesture_control.tracker import ensure_model; print(ensure_model(TrackerConfig(), Path('.')))"
    if ($LASTEXITCODE) { throw "model download failed" }
    # 3. icon
    & $py packaging\make_icon.py build\icon.ico
    if ($LASTEXITCODE) { throw "icon generation failed" }

    Write-Host "== Running PyInstaller"
    & $py -m PyInstaller packaging\gesture_control.spec --noconfirm --distpath dist --workpath build\pyinstaller
    if ($LASTEXITCODE) { throw "PyInstaller failed" }

    Write-Host "== Adding user-editable files"
    $app = Join-Path $root "dist\GestureControl"
    Copy-Item config.toml, README.md -Destination $app -Force
    New-Item -ItemType Directory -Force (Join-Path $app "models") | Out-Null
    Copy-Item models\hand_landmarker.task -Destination (Join-Path $app "models") -Force

    $size = (Get-ChildItem $app -Recurse | Measure-Object Length -Sum).Sum / 1MB
    Write-Host ("== Built {0} ({1:N0} MB)" -f $app, $size)

    if (-not $SkipSelfTest) {
        Write-Host "== Self-test of the packaged app"
        & (Join-Path $app "gesture-control-cli.exe") --self-test --no-user-settings
        if ($LASTEXITCODE) { throw "Packaged self-test failed (exit $LASTEXITCODE)" }
    }

    if ($Zip) {
        $version = & $py -c "import gesture_control; print(gesture_control.__version__)"
        $zipPath = Join-Path $root "dist\GestureControl-$version-windows-x64.zip"
        if (Test-Path $zipPath) { Remove-Item $zipPath }
        Compress-Archive -Path $app -DestinationPath $zipPath
        Write-Host "== Zipped $zipPath"
    }
}
finally {
    Pop-Location
}
