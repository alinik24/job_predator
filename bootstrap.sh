#!/usr/bin/env bash
set -euo pipefail
command -v python3 >/dev/null || { echo "MISSING: Python 3.10+"; exit 1; }
python3 -m venv .venv
if [[ "${1:-}" != "--skip-install" ]]; then .venv/bin/python -m pip install -r requirements.txt; fi
if [[ "${2:-}" != "--skip-playwright" && "${1:-}" != "--skip-playwright" ]]; then .venv/bin/python -m playwright install chromium; fi
.venv/bin/python scripts/doctor.py
echo "Start: .venv/bin/python main.py --help"
