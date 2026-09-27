"""Pipeline version: a digest of everything that shapes a step's output besides its inputs.

It is part of every step's input hash, so a change to the ontology, the dbt templates or the
step code invalidates reuse of earlier results instead of silently serving stale outputs.
Line endings are normalised so the digest is the same on Windows and Linux checkouts.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.domain.hashing import content_hash
from src.paths import PACKAGE_ROOT
from src.settings import PROJECT_ROOT, Settings

PIPELINE_SOURCES: tuple[str, ...] = ("ontology", "templates", "src", "uv.lock")


def _files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and "_resources" not in p.relative_to(root).parts
        and p.suffix not in {".pyc", ".pyo"}
    )


@lru_cache(maxsize=1)
def pipeline_version(root: Path = PROJECT_ROOT) -> str:
    h = hashlib.sha256()
    for rel in PIPELINE_SOURCES:
        source = PACKAGE_ROOT if rel == "src" and root == PROJECT_ROOT else root / rel
        for path in _files(source):
            name = f"{rel}/{path.relative_to(source).as_posix()}" if source.is_dir() else rel
            h.update(name.encode())
            h.update(b"\0")
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
    return h.hexdigest()


def configuration_fingerprint(settings: Settings, judge: Any = None) -> str:
    """Hash effective execution settings without credentials or machine-specific paths."""
    ignored = {
        "anthropic_api_key",
        "http_tokens",
        "var_root",
        "fixtures_root",
        "database_url",
        "log_level",
        "local_principal_id",
        "local_principal_role",
        "http_base_url",
        "otel_console",
    }
    config = settings.model_dump(mode="json", exclude=ignored)
    if judge is not None:
        identity = getattr(judge, "cache_identity", None)
        config["judge"] = {
            "type": f"{type(judge).__module__}.{type(judge).__qualname__}",
            "model": getattr(judge, "model", None),
            "mode": getattr(judge, "mode", None),
            "identity": identity() if callable(identity) else identity,
        }
    if settings.llm_enabled and settings.llm_mode == "replay":
        config["cassettes"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(settings.llm_cassette_dir.glob("*.json"))
        }
    return content_hash(config)
