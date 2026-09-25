param([switch]$SkipInstall,[switch]$SkipPlaywright)
$ErrorActionPreference = "Stop"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Error "MISSING: Python 3.10+" }
$py = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { python -m venv .venv }
if (-not $SkipInstall) { & $py -m pip install -r requirements.txt }
if (-not $SkipPlaywright) { & $py -m playwright install chromium }
& $py scripts/doctor.py
Write-Host "Start: .\.venv\Scripts\python.exe main.py --help"
