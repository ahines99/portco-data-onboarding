"""Structural inference regressions; these examples are not benchmark labels."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import duckdb
import pytest

from src.adapters.repositories import RunRecord
from src.domain.models import Confidence, ReviewGate, RunStatus, StepName
from src.domain.ontology import load_ontology
from src.domain.project_models import (
    ColumnProfile,
    ConnectionSpec,
    EntityInference,
    JoinGraph,
    MappingSet,
    PiiClass,
    SemanticType,
    TableProfile,
)
from src.services.entities import classify_table, primary_key
from src.workflows.contracts import StepContext
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, REVIEWER, decide_all, make_service


def column(name: str, dtype: str, semantic: SemanticType, ordinal: int = 1) -> ColumnProfile:
    return ColumnProfile(
        table="incoming.archive",
        column=name,
        ordinal=ordinal,
        dtype=dtype,
        row_count=8,
        non_null_count=8,
        distinct_count=8,
        null_pct=0,
        inferred_semantic_type=semantic,
    )


def test_unique_sensitive_or_non_identifier_values_are_not_primary_keys() -> None:
    cols = [
        column("event_date", "DATE", SemanticType.DATE),
        column("amount", "DECIMAL(12,2)", SemanticType.MONEY, 2),
        # Profiling may label a coincidentally unique integer as ID; a bare
        # numeric counter still has no identifier-name evidence.
        column("counter", "INTEGER", SemanticType.ID, 3),
        column("email", "VARCHAR", SemanticType.CODE, 4).model_copy(update={"pii_class": PiiClass.EMAIL}),
    ]
    table = TableProfile(schema_name="incoming", table_name="archive", row_count=8, columns=cols)
    ctx = cast(StepContext, SimpleNamespace(ontology=load_ontology(), adapter=lambda: None))
    assert primary_key(ctx, table) == []
    table = table.model_copy(update={"columns": [*cols, column("record_key", "VARCHAR", SemanticType.ID, 5)]})
    assert primary_key(ctx, table) == ["record_key"]


def test_structural_entity_requires_multiple_compatible_discriminating_anchors() -> None:
    cols = [
        column("record_key", "VARCHAR", SemanticType.ID),
        column("invoice_date", "DATE", SemanticType.DATE, 2),
        column("total_amount", "DECIMAL(12,2)", SemanticType.MONEY, 3),
    ]
    table = TableProfile(schema_name="incoming", table_name="archive", row_count=8, columns=cols)
    inferred = classify_table(table, ["record_key"], load_ontology())
    assert inferred.canonical_entity == "invoice"
    assert inferred.confidence is Confidence.LOW
    assert inferred.feature_breakdown["structural_anchors"] == 2
    wrong_type = table.model_copy(
        update={"columns": [cols[0], cols[1], cols[2].model_copy(update={"dtype": "BOOLEAN"})]}
    )
    assert classify_table(wrong_type, ["record_key"], load_ontology()).canonical_entity is None
    unknown = table.model_copy(update={"columns": [cols[0], column("x", "VARCHAR", SemanticType.CODE)]})
    assert classify_table(unknown, ["record_key"], load_ontology()).canonical_entity is None


def test_equal_structural_entity_support_abstains() -> None:
    table = TableProfile(
        schema_name="incoming",
        table_name="archive",
        row_count=8,
        columns=[
            column("record_key", "VARCHAR", SemanticType.ID),
            column("invoice_date", "DATE", SemanticType.DATE, 2),
            column("total_amount", "DECIMAL(12,2)", SemanticType.MONEY, 3),
            column("product_name", "VARCHAR", SemanticType.CATEGORY, 4),
            column("list_price", "DECIMAL(12,2)", SemanticType.MONEY, 5),
        ],
    )
    assert classify_table(table, ["record_key"], load_ontology()).canonical_entity is None


async def run_schema(root: Path, statements: list[str]) -> tuple[OnboardingService, RunRecord]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.duckdb"
    with duckdb.connect(str(source)) as conn:
        conn.execute("CREATE SCHEMA incoming")
        conn.execute("SET schema='incoming'")
        for statement in statements:
            conn.execute(statement)
    service = make_service(root / "state")
    service.connections.register(
        ConnectionSpec(connection_id="structural", company_id="structural", path=str(source), schemas=["incoming"])
    )
    return service, await service.start_run(AGENT, "structural")


BASE = [
    "CREATE TABLE customers AS SELECT 'C' || i AS customer_id, 'Business ' || i AS customer_name FROM range(1, 5) t(i)",
    "CREATE TABLE archive AS SELECT 'R' || i AS record_key, 'C' || (1 + i % 4) AS zz_ref, DATE '2026-01-01' + i::INTEGER AS invoice_date, (10 + i)::DECIMAL(12,2) AS total_amount FROM range(1, 9) t(i)",
]


@pytest.mark.anyio
async def test_unknown_key_aliases_gain_reviewed_mapping_without_auto_approval(tmp_path: Path) -> None:
    service, run = await run_schema(tmp_path, BASE)
    assert run.status is RunStatus.NEEDS_REVIEW
    assert run.gate == "mapping_review"
    entities = cast(EntityInference, service.artifact(AGENT, run.run_id, StepName.ENTITY_INFERENCE))
    assert entities.for_table("incoming.archive").canonical_entity == "invoice"
    mapping = cast(MappingSet, service.artifact(AGENT, run.run_id, StepName.CANONICAL_MAPPING))
    proposals = {p.source_column: p for p in mapping.proposals if p.source_table == "incoming.archive"}
    assert proposals["record_key"].canonical_field == "invoice_id"
    assert proposals["zz_ref"].canonical_field == "customer_id"
    assert "JOIN_INFERRED" in proposals["zz_ref"].reason_codes
    assert all(p.requires_review and p.confidence is Confidence.LOW for p in proposals.values())
    joins = cast(JoinGraph, service.artifact(AGENT, run.run_id, StepName.JOIN_INFERENCE))
    join = next(j for j in joins.joins if j.left_columns == ["zz_ref"])
    assert join.requires_review and "STRUCTURAL_JOIN" in join.reason_codes


@pytest.mark.anyio
async def test_competing_structural_join_targets_abstain(tmp_path: Path) -> None:
    service, run = await run_schema(tmp_path, [*BASE, "CREATE TABLE clients AS SELECT * FROM customers"])
    joins = cast(JoinGraph, service.artifact(AGENT, run.run_id, StepName.JOIN_INFERENCE))
    assert not any(j.left_columns == ["zz_ref"] for j in joins.joins)


@pytest.mark.anyio
async def test_weak_name_join_with_incomplete_containment_abstains(tmp_path: Path) -> None:
    statements = [statement.replace("1 + i % 4", "1 + i % 5") for statement in BASE]
    service, run = await run_schema(tmp_path, statements)
    joins = cast(JoinGraph, service.artifact(AGENT, run.run_id, StepName.JOIN_INFERENCE))
    assert not any(j.left_columns == ["zz_ref"] for j in joins.joins)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("suffix", "transform", "reason"), [("cents", "cents_to_major", "UNIT_MISMATCH"), ("minor", None, "UNIT_UNCERTAIN")]
)
async def test_explicit_unit_names_require_review(
    tmp_path: Path, suffix: str, transform: str | None, reason: str
) -> None:
    service, run = await run_schema(
        tmp_path,
        [
            f"CREATE TABLE invoices AS SELECT 'I' || i AS invoice_id, (1000+i)::BIGINT AS total_amount_{suffix} FROM range(1, 9) t(i)"
        ],
    )
    mapping = cast(MappingSet, service.artifact(AGENT, run.run_id, StepName.CANONICAL_MAPPING))
    proposal = next(p for p in mapping.proposals if p.source_column == f"total_amount_{suffix}")
    assert proposal.canonical_field == "total_amount"
    assert proposal.suggested_transform == transform
    assert proposal.requires_review and reason in proposal.reason_codes


@pytest.mark.anyio
async def test_integer_money_alone_does_not_imply_minor_units(tmp_path: Path) -> None:
    service, run = await run_schema(
        tmp_path,
        [
            "CREATE TABLE invoices AS SELECT 'I' || i AS invoice_id, (1000+i)::BIGINT AS total_amount FROM range(1, 9) t(i)"
        ],
    )
    mapping = cast(MappingSet, service.artifact(AGENT, run.run_id, StepName.CANONICAL_MAPPING))
    proposal = next(p for p in mapping.proposals if p.source_column == "total_amount")
    assert proposal.suggested_transform is None


@pytest.mark.anyio
async def test_competing_money_variants_review_exact_match_and_do_not_invent_alternate_role(tmp_path: Path) -> None:
    service, run = await run_schema(
        tmp_path,
        [
            "CREATE TABLE invoice_lines AS SELECT 'L' || i AS invoice_line_id, 'I' || i AS invoice_id, "
            "(10+i)::DECIMAL(12,2) AS unit_price, (1000+100*i)::BIGINT AS unit_price_cents "
            "FROM range(1, 9) t(i)"
        ],
    )
    mapping = cast(MappingSet, service.artifact(AGENT, run.run_id, StepName.CANONICAL_MAPPING))
    proposals = {p.source_column: p for p in mapping.proposals}
    for name in ("unit_price", "unit_price_cents"):
        proposal = proposals[name]
        assert proposal.canonical_field == "unit_price"
        assert proposal.requires_review and "CONFLICT" in proposal.reason_codes
    assert not any(p.canonical_field == "amount" for p in proposals.values())
    assert proposals["unit_price_cents"].suggested_transform == "cents_to_major"
    service.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(run.pending_items),
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate.MAPPING_REVIEW,
    )
    resumed = await service.resume(AGENT, run.run_id)
    assert resumed.status is RunStatus.NEEDS_REVIEW
    assert resumed.gate == "mapping_review"
    assert {item.item_key for item in resumed.pending_items} == {
        "mapping:incoming.invoice_lines.unit_price",
        "mapping:incoming.invoice_lines.unit_price_cents",
    }
    assert all("DUPLICATE_TARGET_AFTER_REVIEW" in item.reason_codes for item in resumed.pending_items)


@pytest.mark.anyio
async def test_distinct_explicit_financial_roles_do_not_create_artificial_conflict(tmp_path: Path) -> None:
    service, run = await run_schema(
        tmp_path,
        [
            "CREATE TABLE invoice_lines AS SELECT 'L' || i AS invoice_line_id, 'I' || i AS invoice_id, "
            "(10+i)::DECIMAL(12,2) AS unit_price, (20+2*i)::DECIMAL(12,2) AS amount "
            "FROM range(1, 9) t(i)"
        ],
    )
    mapping = cast(MappingSet, service.artifact(AGENT, run.run_id, StepName.CANONICAL_MAPPING))
    proposals = {p.source_column: p for p in mapping.proposals}
    assert proposals["unit_price"].canonical_field == "unit_price"
    assert proposals["amount"].canonical_field == "amount"
    assert all("CONFLICT" not in p.reason_codes for p in proposals.values())
