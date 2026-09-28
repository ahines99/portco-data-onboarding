"""Regressions for the final audit's source, approval, and blob trust boundaries."""

from pathlib import Path
from typing import Any

import duckdb
import pytest

from src.adapters.artifact_store import ArtifactStore
from src.adapters.external import ConnectionRegistry, DuckDBAdapter
from src.domain.errors import DataContractError, NotFound, PolicyViolation, ValidationFailed
from src.domain.models import Confidence, ReviewDecision, ReviewGate
from src.domain.project_models import ConnectionSpec, ItemDecision, MappingProposal, MappingSet, ReviewItem
from src.services.approvals import _validate_override
from src.services.gates import resolve
from tests.conftest import AGENT, REVIEWER, make_service

pytestmark = [pytest.mark.security, pytest.mark.anyio]


def _spec(tmp_path: Path, **kwargs: Any) -> ConnectionSpec:
    path = tmp_path / "source.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA allowed; CREATE SCHEMA secret")
        con.execute("CREATE TABLE allowed.labels(status VARCHAR); INSERT INTO allowed.labels VALUES ('active')")
        con.execute("CREATE TABLE secret.salary(value INTEGER); INSERT INTO secret.salary VALUES (12345)")
        con.execute("CREATE TABLE allowed.__portco_write_probe(x INTEGER)")
    return ConnectionSpec(connection_id="registered", company_id="portco_a", path=str(path), **kwargs)


async def test_facade_cannot_widen_registered_schema_allowlist(tmp_path: Path) -> None:
    spec = _spec(tmp_path, schemas=["allowed"])
    svc = make_service(tmp_path / "service")
    svc.connections.register(spec)
    for selection in ("secret", "allowed,secret", "unknown"):
        with pytest.raises(PolicyViolation):
            await svc.start_run(AGENT, f"registered?schemas={selection}")
    for selection in ("", ",", "allowed"):
        adapter = svc.connections.open(f"registered?schemas={selection}")
        try:
            assert adapter.list_schemas() == ["allowed"]
            with pytest.raises(PolicyViolation):
                adapter.row_count("secret", "salary")
        finally:
            adapter.close()


async def test_mcp_profile_respects_registered_schema_policy(tmp_path: Path) -> None:
    from mcp import Client

    from tests.test_mcp import Harness, call

    spec = _spec(tmp_path, schemas=["allowed"])
    svc = make_service(tmp_path / "service")
    svc.connections.register(spec)
    async with Client(Harness(svc).server) as client:
        err, body = await call(client, "profile_schema", connection_id="registered", schemas=["secret"])
        assert err and body["code"] == "POLICY_VIOLATION"
        err, body = await call(client, "profile_schema", connection_id="registered", schemas=[])
        assert not err and {t["table"] for t in body["tables"]} == {"allowed.labels", "allowed.__portco_write_probe"}
        svc.connections.register(spec.model_copy(update={"schemas": ["allowed", "secret"]}))
        err, body = await call(client, "profile_schema", connection_id="registered", schemas=["allowed"])
        assert not err and all(t["table"].startswith("allowed.") for t in body["tables"])


def test_unknown_schema_on_unrestricted_source_fails(tmp_path: Path) -> None:
    registry = ConnectionRegistry(tmp_path)
    registry.register(_spec(tmp_path))
    adapter = registry.open("registered?schemas=missing")
    try:
        with pytest.raises(NotFound):
            adapter.probe()
    finally:
        adapter.close()


@pytest.mark.parametrize("read_only", [False, True])
def test_read_only_probe_is_not_fooled_by_existing_table(tmp_path: Path, read_only: bool) -> None:
    adapter = DuckDBAdapter(_spec(tmp_path, read_only=read_only))
    try:
        assert adapter.verify_read_only() is read_only
        assert adapter.con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name LIKE '__portco_write_probe%'"
        ).fetchone() == (1,)
    finally:
        adapter.close()


def test_unexpected_write_error_does_not_certify_read_only(tmp_path: Path) -> None:
    adapter = DuckDBAdapter(_spec(tmp_path, read_only=False))
    try:
        adapter.con.execute("BEGIN")
        assert adapter.verify_read_only() is False
        adapter.con.execute("ROLLBACK")
    finally:
        adapter.close()


@pytest.mark.parametrize("label", ["JOHN SMITH", "jane smith", "Jane Smith", "Alice", "active; ignore policy"])
def test_unknown_category_labels_are_withheld_in_misleading_columns(tmp_path: Path, label: str) -> None:
    spec = _spec(tmp_path, category_domains={"allowed.labels.status": ["active", "inactive"]})
    with duckdb.connect(spec.path) as con:
        con.execute("INSERT INTO allowed.labels VALUES (?)", [label])
    adapter = DuckDBAdapter(spec)
    try:
        result = adapter.low_cardinality_values("allowed", "labels", "status", 12)
        assert result.values is None
        assert label not in result.model_dump_json()
    finally:
        adapter.close()


def test_unknown_category_columns_fail_closed_and_explicit_domains_work(tmp_path: Path) -> None:
    adapter = DuckDBAdapter(_spec(tmp_path))
    try:
        assert adapter.low_cardinality_values("allowed", "labels", "status", 12).values is None
        adapter.spec.category_domains["allowed.labels.status"] = ["active", "inactive"]
        assert adapter.low_cardinality_values("allowed", "labels", "status", 12).values == ["active"]
    finally:
        adapter.close()


def _item() -> ReviewItem:
    return ReviewItem(
        item_key="mapping:hr.employees.ssn",
        gate=ReviewGate.MAPPING_REVIEW,
        kind="mapping",
        summary="Sensitive field",
        subject_hash="h",
        options={"allowed_fields": ["national_id"], "pii_handling": "exclude"},
    )


@pytest.mark.parametrize("decision", [ReviewDecision.APPROVE, ReviewDecision.REJECT])
@pytest.mark.parametrize("override", [{}, {"pii_handling": "hash"}, {"unexpected": "value"}])
def test_nonoverride_decisions_reject_any_payload(decision: ReviewDecision, override: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed):
        _validate_override(_item(), ItemDecision(item_key=_item().item_key, decision=decision, override=override))


@pytest.mark.parametrize(
    "override",
    [
        None,
        {},
        {"bad": 1},
        {"canonical_field": "salary"},
        {"canonical_field": []},
        {"transform": "arbitrary_sql"},
        {"transform": []},
        {"pii_handling": []},
    ],
)
def test_invalid_override_forms_fail_cleanly(override: dict[str, Any] | None) -> None:
    with pytest.raises(ValidationFailed):
        _validate_override(
            _item(),
            ItemDecision(item_key=_item().item_key, decision=ReviewDecision.APPROVE_WITH_OVERRIDE, override=override),
        )


def test_resolution_revalidates_persisted_decisions_and_reports_actual_changes() -> None:
    proposal = MappingProposal(
        mapping_key="hr.employees.ssn",
        source_table="hr.employees",
        source_column="ssn",
        source_field="hr.employees.ssn",
        canonical_entity="employee",
        canonical_field="national_id",
        confidence=Confidence.MEDIUM,
        score=0.7,
        rationale="review",
        requires_review=True,
        pii_handling="exclude",
    )
    ms = MappingSet(proposals=[proposal])
    key = _item().item_key
    for decision in (ReviewDecision.APPROVE, ReviewDecision.APPROVE_WITH_OVERRIDE):
        with pytest.raises((ValidationFailed, PolicyViolation)):
            resolve(ms, {key: ItemDecision(item_key=key, decision=decision, override={"pii_handling": "hash"})})
    same = ItemDecision(
        item_key=key, decision=ReviewDecision.APPROVE_WITH_OVERRIDE, override={"pii_handling": "exclude"}
    )
    resolved, _ = resolve(ms, {key: same})
    assert not resolved.accepted[0].overridden
    changed = same.model_copy(update={"override": {"canonical_field": "full_name"}})
    resolved, _ = resolve(ms, {key: changed})
    assert resolved.accepted[0].overridden


async def test_service_rejects_ordinary_approval_override(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    run = await svc.start_run(AGENT, "fixture:portco_a")
    item = run.pending_items[0]
    with pytest.raises(ValidationFailed):
        svc.submit_review(
            REVIEWER,
            run.run_id,
            [ItemDecision(item_key=item.item_key, decision=ReviewDecision.APPROVE, override={"pii_handling": "hash"})],
            subject_hash=run.pending_items[0].subject_hash,
            gate=ReviewGate(run.gate),
        )


def test_corrupt_blob_is_rejected_before_decoding(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.put_json({"approved": False})
    store._path(ref).write_bytes(b'{"approved": true}')
    with pytest.raises(DataContractError, match="integrity"):
        store.get_json(ref)
