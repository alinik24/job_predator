import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

print(f"python={sys.version.split()[0]}")
if sys.version_info < (3, 10):
    print("MISSING: Python 3.10+")
    raise SystemExit(1)

required = ["typer", "rich", "pydantic", "yaml"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    for name in missing:
        print(f"MISSING: Python dependency {name}; run bootstrap.ps1")
    raise SystemExit(1)

if not (ROOT / ".env").exists():
    print("CONFIG: no repository .env; use %USERPROFILE%\\.config\\job_predator\\.env or environment variables")
else:
    print("CONFIG: repository .env present (values not displayed)")

for name in ["LLM_API_KEY", "DATABASE_URL"]:
    if os.getenv(name):
        print(f"CONFIG: {name}=available")
    else:
        print(f"MISSING: {name} (environment or %USERPROFILE%\\.config\\job_predator\\.env)")

print("source=present")
print("doctor=PASS")
