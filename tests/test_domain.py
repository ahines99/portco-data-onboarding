"""Contracts, ontology, hashing, policies (POD-101, 102, 103, 311)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.domain.hashing import canonical_json, content_hash
from src.domain.models import AuditEvent, Confidence, EvidenceRef, Finding, FindingStatus, Principal, Role
from src.domain.ontology import Ontology, load_ontology
from src.domain.policies import ACTIONS, check_action, render_policies
from src.domain.project_models import ConnectionSpec, MappingProposal
from src.settings import PROJECT_ROOT

pytestmark = pytest.mark.unit


def test_naive_datetimes_and_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(source_id="x", uri="u", retrieved_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        ConnectionSpec(connection_id="c", company_id="x", path="p", password="nope")  # type: ignore[call-arg]


def test_supported_finding_must_cite_evidence() -> None:
    with pytest.raises(ValidationError, match="cites no evidence"):
        Finding(code="X", title="t", statement="s", confidence=Confidence.HIGH)
    ok = Finding(code="X", title="t", statement="s", confidence=Confidence.HIGH, status=FindingStatus.NEEDS_EVIDENCE)
    assert ok.status is FindingStatus.NEEDS_EVIDENCE


def test_invalid_enum_rejected() -> None:
    with pytest.raises(ValidationError):
        AuditEvent(
            run_id=uuid4(),
            step="s",
            event_type="e",
            actor="a",
            created_at="2026-01-01T00:00:00Z",
            payload={},
            schema_version="2",
        )  # type: ignore[arg-type]


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": [1, 2]}) == canonical_json({"a": [1, 2], "b": 1})
    assert content_hash({"x": 1}) == content_hash({"x": 1})


def test_principal_scope() -> None:
    p = Principal(principal_id="p", role=Role.AGENT, company_ids=("portco_a",))
    assert p.can_access("portco_a") and not p.can_access("portco_b")
    assert Principal(principal_id="q", role=Role.ADMIN).can_access("anything")


# --------------------------------------------------------------------------- ontology


def test_ontology_loads_and_metrics_reference_existing_fields() -> None:
    ont = load_ontology()
    assert {"customer", "invoice", "subscription", "gl_entry", "employee"} <= set(ont.entities)
    for metric in ont.metrics.values():
        assert all(ont.has_field(ref) for ref in metric.requires)
    assert ont.metric_dependents("revenue_recognized") == {"gross_margin_pct", "ebitda"}


def test_duplicate_synonym_across_fields_is_rejected() -> None:
    raw = load_ontology().model_dump(mode="json", by_alias=True)
    raw["synonyms"]["customer_id"].append("inv_no")  # already a synonym of invoice_id
    with pytest.raises(ValidationError, match="claimed by both"):
        Ontology.model_validate(raw)


def test_pii_entities_mark_pii_fields() -> None:
    ont = load_ontology()
    for entity in ("contact", "employee"):
        pii = [f for f, d in ont.entities[entity].fields.items() if d.pii]
        assert pii, entity


# --------------------------------------------------------------------------- JSON Schemas (POD-102)


def test_committed_json_schemas_match_models() -> None:
    from scripts.export_schemas import MODELS, schema_for

    contracts = PROJECT_ROOT / "contracts"
    for name, model in MODELS.items():
        committed = json.loads((contracts / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert committed == schema_for(model), f"{name} drifted; run `poe schemas`"


def test_no_contract_field_can_carry_row_values() -> None:
    # Reviewers check this by design; this guards against accidental `sample_rows`-style fields.
    forbidden = {"rows", "sample", "samples", "sample_rows", "values", "raw"}
    for model in (MappingProposal, ConnectionSpec):
        assert not forbidden & set(model.model_fields)


# --------------------------------------------------------------------------- policies (POD-311)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("action", sorted(ACTIONS))
@pytest.mark.parametrize("approved", [True, False])
def test_policy_matrix(action: str, role: Role, approved: bool) -> None:
    decision = check_action(action, role=role, has_approval=approved)
    policy = ACTIONS[action]
    expected = role in policy.roles and (policy.gate is None or approved)
    if policy.risk.value in {"high", "critical"} and policy.gate is None:
        expected = expected and role in {Role.REVIEWER, Role.ADMIN}
    assert decision.allowed is expected


def test_unknown_action_is_denied() -> None:
    d = check_action("drop_warehouse", role=Role.ADMIN, has_approval=True)
    assert not d.allowed and "denied by default" in d.reason


def test_handoff_signature_high_risk_without_approval_denied() -> None:
    assert not check_action("publish", "high", False).allowed
    assert check_action("publish", "high", True).allowed


def test_policy_resource_is_generated_from_registry() -> None:
    text = render_policies()
    for action in ACTIONS:
        assert f"| {action} |" in text


def test_contracts_dir_exists() -> None:
    assert Path(PROJECT_ROOT / "contracts").is_dir()
