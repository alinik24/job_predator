"""Shared environment loader for agent modules."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List


def _parse_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def candidate_env_paths(project_root: Path | None = None) -> List[Path]:
    paths: List[Path] = []
    if project_root:
        paths.append(Path(project_root) / ".env")
    return paths


def load_env_files(project_root: Path | None = None, paths: Iterable[Path] | None = None) -> None:
    load_paths = list(paths) if paths is not None else candidate_env_paths(project_root)
    for p in load_paths:
        try:
            _parse_env_file(p)
        except Exception:
            continue
