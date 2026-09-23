from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field

class Confidence(StrEnum):
    LOW="low"
    MEDIUM="medium"
    HIGH="high"

class EvidenceRef(BaseModel):
    source_id: str
    uri: str
    retrieved_at: datetime
    as_of: datetime | None = None
    excerpt_hash: str | None = None

class Finding(BaseModel):
    finding_id: str
    title: str
    statement: str
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
