"""Pipeline version: a digest of everything that shapes a step's output besides its inputs.

It is part of every step's input hash, so a change to the ontology, the dbt templates or the
step code invalidates reuse of earlier results instead of silently serving stale outputs.
Line endings are normalised so the digest is the same on Windows and Linux checkouts.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from src.settings import PROJECT_ROOT

PIPELINE_SOURCES: tuple[str, ...] = ("ontology", "templates", "src/domain", "src/services", "src/workflows")


def _files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
    )


@lru_cache(maxsize=1)
def pipeline_version(root: Path = PROJECT_ROOT) -> str:
    h = hashlib.sha256()
    for rel in PIPELINE_SOURCES:
        for path in _files(root / rel):
            h.update(path.relative_to(root).as_posix().encode())
            h.update(b"\0")
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
    return h.hexdigest()
