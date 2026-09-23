"""Content-addressed blob store (POD-202). Blobs are immutable and deduplicated by sha256."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from src.domain.errors import NotFound
from src.domain.hashing import canonical_json, sha256_bytes

M = TypeVar("M", bound=BaseModel)


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, ref: str) -> Path:
        if len(ref) != 64 or not all(c in "0123456789abcdef" for c in ref):
            raise NotFound("invalid artifact reference")
        return self.root / ref[:2] / ref

    def put_bytes(self, data: bytes) -> str:
        ref = sha256_bytes(data)
        path = self._path(ref)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        return ref

    def get_bytes(self, ref: str) -> bytes:
        path = self._path(ref)
        if not path.exists():
            raise NotFound(f"artifact {ref[:12]} not found")
        return path.read_bytes()

    def put_json(self, value: Any) -> str:
        return self.put_bytes(canonical_json(value).encode("utf-8"))

    def get_json(self, ref: str) -> Any:
        return json.loads(self.get_bytes(ref))

    def put_model(self, model: BaseModel) -> str:
        return self.put_json(model.model_dump(mode="json"))

    def get_model(self, ref: str, cls: type[M]) -> M:
        return cls.model_validate(self.get_json(ref))

    def exists(self, ref: str) -> bool:
        try:
            return self._path(ref).exists()
        except NotFound:
            return False
