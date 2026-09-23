"""Filesystem helpers that behave on Windows, where dbt output can exceed MAX_PATH (260 characters)."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Any

WIN_LONG_PREFIX = "\\\\?\\"  # the literal characters \\?\


def _long(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name == "nt" and not resolved.startswith(WIN_LONG_PREFIX):
        return WIN_LONG_PREFIX + resolved
    return resolved


def long_path(path: Path) -> Path:
    """`path` in a form that file APIs accept beyond MAX_PATH on Windows (unchanged elsewhere)."""
    return Path(_long(path))


def write_bytes(path: Path, data: bytes) -> None:
    target = long_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def remove_tree(path: Path) -> bool:
    """Delete a directory tree, handling long paths and read-only files. Returns True if it is gone."""
    if not path.exists():
        return True

    def _retry(func: Any, target: str, _exc: Any) -> None:
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass  # reported through the return value

    shutil.rmtree(_long(path), onexc=_retry)
    return not path.exists()
