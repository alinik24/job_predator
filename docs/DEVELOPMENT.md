# Development

## Setup

- Python 3.10+.
- Windows: `.ootstrap.ps1`.
- POSIX: `./bootstrap.sh`.
- Safe private configuration: `%USERPROFILE%\.config\job_predator\.env` or the POSIX XDG equivalent.
- Optional services: Docker Compose PostgreSQL/pgvector and Neo4j.

## Verification

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py --help
```

The full dependency installation includes Playwright browser assets. Database tests require the configured database service; tests that only exercise parsers/configuration can run without Docker.

## Runtime

- CLI: `main.py`.
- API: `api/main.py` where configured.
- Generated and personal state remains outside Git.
- Never commit `.env`, credentials, private CV documents, downloaded models, or runtime databases.
