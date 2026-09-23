"""Export JSON Schemas for every public contract to contracts/ (POD-102).

A test fails when the committed schemas drift from the models: run `uv run poe schemas`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain import models, project_models

MODELS: dict[str, type[BaseModel]] = {
    "evidence": models.Evidence,
    "evidence_ref": models.EvidenceRef,
    "finding": models.Finding,
    "audit_event": models.AuditEvent,
    "connection_check": project_models.ConnectionCheck,
    "schema_profile": project_models.SchemaProfile,
    "entity_inference": project_models.EntityInference,
    "join_graph": project_models.JoinGraph,
    "mapping_set": project_models.MappingSet,
    "resolved_mapping": project_models.ResolvedMapping,
    "review_item": project_models.ReviewItem,
    "approval": project_models.Approval,
    "artifact_bundle": project_models.ArtifactBundle,
    "test_report": project_models.TestReport,
    "certification_packet": project_models.CertificationPacket,
    "publish_receipt": project_models.PublishReceipt,
}

OUT = Path(__file__).resolve().parents[1] / "contracts"


def schema_for(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, model in MODELS.items():
        (OUT / f"{name}.schema.json").write_text(
            json.dumps(schema_for(model), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"wrote {len(MODELS)} schemas to {OUT}")


if __name__ == "__main__":
    main()
