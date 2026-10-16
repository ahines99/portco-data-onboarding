"""Regressions for the 2026-10-10 audit's financial and mapping findings (A01, A02, A03, A15, A19).

Synthetic sources, real resolution/generation and (for the slow cases) actual dbt builds with the
independent reconciliation. The audit's original reproductions live in docs/audits/2026-10-10.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import duckdb
import pytest

from src.adapters.artifact_store import ArtifactStore
from src.adapters.external import DuckDBAdapter
from src.domain.hashing import content_hash
from src.domain.models import Confidence, Principal, ReviewDecision, Role, StepName
from src.domain.ontology import load_ontology
from src.domain.project_models import (
    ArtifactBundle,
    ArtifactFile,
    ColumnProfile,
    ConnectionSpec,
    ItemDecision,
    JoinCandidate,
    JoinGraph,
    MappingProposal,
    MappingSet,
    ResolvedMapping,
    SchemaProfile,
    ScoredTarget,
    SemanticType,
    TableProfile,
)
from src.services.gates import resolve
from src.services.generation import Generator
from src.services.mapping import _apply_judge
from src.services.sandbox import build_and_test
from src.services.value_contracts import contract_issues
from src.settings import Settings
from src.workflows.facade import OnboardingService

pytestmark = pytest.mark.integration
GL_METRICS = {"revenue_recognized", "cogs", "opex", "ebitda", "gross_margin_pct"}
JOIN_ID = "erp.journal_lines.account_code->erp.gl_accounts.account_code"


def _gl_source(path: Path, label: str | None, money: str = "DECIMAL(18,2)", credit: str = "100") -> None:
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA erp")
        con.execute("CREATE TABLE erp.gl_accounts(account_code VARCHAR, account_type VARCHAR)")
        con.execute("INSERT INTO erp.gl_accounts VALUES (?, ?)", ["4000", label])
        con.execute(
            "CREATE TABLE erp.journal_lines(journal_id VARCHAR, line_number INTEGER, account_code VARCHAR, "
            f"posting_date DATE, debit_amount {money}, credit_amount {money})"
        )
        con.execute("INSERT INTO erp.journal_lines VALUES ('j1', 1, '4000', '2026-01-10', 0, ?)", [credit])


def _gl_case(
    tmp_path: Path,
    label: str | None,
    *,
    join: str = "approve",  # approve | reject | absent
    normalize: bool = False,
    money: str = "DECIMAL(18,2)",
    credit: str = "100",
    with_contracts: bool = True,
) -> tuple[Generator, dict[str, str], ResolvedMapping, Path]:
    source = tmp_path / "input.duckdb"
    _gl_source(source, label, money, credit)
    entities = {"erp.gl_accounts": "gl_account", "erp.journal_lines": "gl_entry"}
    tables, proposals = [], []
    with duckdb.connect(str(source), read_only=True) as con:
        for table, entity in entities.items():
            cols = []
            for i, (col, dtype, *_rest) in enumerate(con.execute("DESCRIBE " + table).fetchall()):
                sem = (
                    SemanticType.MONEY
                    if col in {"debit_amount", "credit_amount"}
                    else SemanticType.DATE
                    if dtype == "DATE"
                    else SemanticType.CATEGORY
                    if col == "account_type"
                    else SemanticType.ID
                )
                cols.append(
                    ColumnProfile(
                        table=table,
                        column=col,
                        ordinal=i,
                        dtype=dtype,
                        row_count=1,
                        non_null_count=1,
                        null_pct=0,
                        distinct_count=1,
                        inferred_semantic_type=sem,
                    )
                )
                proposals.append(
                    MappingProposal(
                        mapping_key=f"{table}.{col}",
                        source_table=table,
                        source_column=col,
                        source_field=f"{table}.{col}",
                        canonical_entity=entity,
                        canonical_field=col,
                        confidence=Confidence.HIGH,
                        score=1,
                        rationale="synthetic reviewed exact-name mapping",
                        requires_review=True,
                    )
                )
            tables.append(TableProfile(schema_name="erp", table_name=table.split(".")[1], row_count=1, columns=cols))
    joins = []
    if join != "absent":
        joins.append(
            JoinCandidate(
                join_id=JOIN_ID,
                left_table="erp.journal_lines",
                left_columns=["account_code"],
                right_table="erp.gl_accounts",
                right_columns=["account_code"],
                containment_ratio=1,
                orphan_rate=0,
                cardinality="N:1",
                name_score=1,
                score=1,
                confidence=Confidence.HIGH,
                requires_review=True,
            )
        )
    ms = MappingSet(
        proposals=proposals, joins=joins, entity_tables=entities, primary_tables={v: k for k, v in entities.items()}
    )
    decisions = {
        f"mapping:{p.mapping_key}": ItemDecision(item_key=f"mapping:{p.mapping_key}", decision=ReviewDecision.APPROVE)
        for p in proposals
    }
    if normalize:
        key = "mapping:erp.gl_accounts.account_type"
        decisions[key] = ItemDecision(
            item_key=key,
            decision=ReviewDecision.APPROVE_WITH_OVERRIDE,
            override={"transform": "normalize_category"},
        )
    if joins:
        decisions[f"join:{JOIN_ID}"] = ItemDecision(
            item_key=f"join:{JOIN_ID}",
            decision=ReviewDecision.REJECT if join == "reject" else ReviewDecision.APPROVE,
        )
    resolved, duplicate = resolve(ms, decisions)
    assert not duplicate
    profile = SchemaProfile(connection_id="t", company_id="t", source_fingerprint="synthetic", tables=tables)
    issues: dict[tuple[str, str], dict[str, int]] = {}
    if with_contracts:
        adapter = DuckDBAdapter(ConnectionSpec(connection_id="t", company_id="t", path=str(source), schemas=["erp"]))
        try:
            for m in resolved.accepted:
                dtype = profile.table(m.source_table).column(m.source_column).dtype
                found = contract_issues(
                    adapter,
                    load_ontology(),
                    m.source_table,
                    m.source_column,
                    dtype,
                    m.canonical_entity,
                    m.canonical_field,
                    m.transform,
                )
                if found:
                    issues[(m.canonical_entity, m.canonical_field)] = found
        finally:
            adapter.close()
    gen = Generator(
        resolved,
        profile,
        load_ontology(),
        "probe",
        date(2026, 1, 31),
        {"erp.gl_accounts": ["account_code"], "erp.journal_lines": ["journal_id", "line_number"]},
        issues,
    )
    return gen, gen.build(), resolved, source


def _sandbox(tmp_path: Path, gen: Generator, files: dict[str, str], resolved: ResolvedMapping, source: Path) -> Any:
    blobs = ArtifactStore(tmp_path / "blobs")
    entries = [
        ArtifactFile(path=p, sha256=blobs.put_bytes(t.encode()), kind="test", size=len(t.encode()))
        for p, t in files.items()
    ]
    bundle = ArtifactBundle(
        mapping_hash=resolved.content_hash(),
        files=entries,
        manifest_hash=content_hash([(f.path, f.sha256) for f in entries]),
        generated_metrics=gen.generated_metrics,
        not_generated=gen.not_generated,
        models=[p.rsplit("/", 1)[-1][:-4] for p in files if p.startswith("models/") and p.endswith(".sql")],
    )
    spec = ConnectionSpec(connection_id="t", company_id="t", path=str(source.resolve()), as_of=date(2026, 1, 31))
    ctx = SimpleNamespace(
        settings=Settings(_env_file=None, env="test", var_root=(tmp_path / "var").resolve()),
        run=SimpleNamespace(run_id=uuid4()),
        services={},
        blobs=blobs,
        adapter=lambda: SimpleNamespace(spec=spec),
        close=lambda: None,
    )
    return build_and_test(ctx, bundle, resolved, "synthetic")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- A01 canonical categories


@pytest.mark.parametrize("label", ["Revenue", "REVENUE", "revenue ", "R100", None])
def test_noncanonical_classifications_block_gl_metrics(tmp_path: Path, label: str | None) -> None:
    gen, _, _, _ = _gl_case(tmp_path, label)
    assert not GL_METRICS & set(gen.generated_metrics)
    assert "value contract" in gen.not_generated["revenue_recognized"]


def test_canonical_balance_sheet_label_still_generates_gl_metrics(tmp_path: Path) -> None:
    gen, files, _, _ = _gl_case(tmp_path, "asset")
    assert {"revenue_recognized", "cogs", "opex", "ebitda"} <= set(gen.generated_metrics)
    staging = files["models/staging/erp/_models.yml"]
    assert "- revenue" in staging and "- equity" in staging  # canonical domain, not observed labels


@pytest.mark.slow
def test_reviewed_normalization_makes_a_case_variant_count(tmp_path: Path) -> None:
    gen, files, resolved, source = _gl_case(tmp_path, "Revenue ", normalize=True)
    assert "revenue_recognized" in gen.generated_metrics
    report = _sandbox(tmp_path, gen, files, resolved, source)
    assert report.passed, report.failing_checks
    revenue = next(c for c in report.reconciliation if c.name == "metric:revenue_recognized")
    assert revenue.passed and revenue.actual == {"2026-01": "100.00"}


@pytest.mark.slow
def test_reconciliation_fails_closed_on_noncanonical_labels_independently(tmp_path: Path) -> None:
    # Bypass the generation-time contract: the independent reconciliation must still refuse a passing zero.
    gen, files, resolved, source = _gl_case(tmp_path, "Revenue", with_contracts=False)
    assert "revenue_recognized" in gen.generated_metrics
    report = _sandbox(tmp_path, gen, files, resolved, source)
    assert not report.passed
    assert "domain:gl_account.account_type" in report.failing_checks


# --------------------------------------------------------------------------- A02 rejected relationships


@pytest.mark.parametrize("join", ["reject", "absent"])
def test_unapproved_relationship_never_feeds_generated_sql(tmp_path: Path, join: str) -> None:
    gen, files, resolved, _ = _gl_case(tmp_path, "revenue", join=join)
    assert resolved.joins == []
    assert "int_erp__gl_accounts" not in files["models/marts/fct_gl_entry.sql"]
    assert not GL_METRICS & set(gen.generated_metrics)
    assert "no approved relationship" in gen.not_generated["revenue_recognized"]


def test_approved_relationship_feeds_generation(tmp_path: Path) -> None:
    gen, files, resolved, _ = _gl_case(tmp_path, "revenue")
    assert [j.join_id for j in resolved.joins] == [JOIN_ID]
    assert "int_erp__gl_accounts" in files["models/marts/fct_gl_entry.sql"]
    assert "revenue_recognized" in gen.generated_metrics


# --------------------------------------------------------------------------- A15 precision


def test_subcent_amounts_block_money_metrics(tmp_path: Path) -> None:
    gen, _, _, _ = _gl_case(tmp_path, "revenue", money="DECIMAL(18,3)", credit="100.005")
    assert "revenue_recognized" not in gen.generated_metrics
    assert "decimal places" in gen.not_generated["revenue_recognized"]


def test_extra_scale_without_subcent_digits_is_accepted(tmp_path: Path) -> None:
    gen, _, _, _ = _gl_case(tmp_path, "revenue", money="DECIMAL(18,3)", credit="100.000")
    assert "revenue_recognized" in gen.generated_metrics


def test_minor_unit_scaling_is_exact() -> None:
    gen = Generator.__new__(Generator)
    gen.ont = load_ontology()
    from src.domain.project_models import AcceptedMapping

    m = AcceptedMapping(
        source_table="b.lines",
        source_column="amount",
        canonical_entity="invoice_line",
        canonical_field="amount",
        transform="cents_to_major",
        decided_by="reviewer",
    )
    expr, _ = gen._expr(m)
    got = duckdb.sql(f"SELECT {expr} FROM (SELECT 123456789012345678::BIGINT AS amount)").fetchone()
    assert got is not None and got[0] == Decimal("1234567890123456.78")


# --------------------------------------------------------------------------- A03 generic keys


GENERIC_SQL = """
CREATE SCHEMA raw;
CREATE TABLE raw.customers (id INTEGER, customer_name VARCHAR, currency VARCHAR);
INSERT INTO raw.customers VALUES (1, 'Acme', 'USD'), (2, 'Beta', 'USD'), (3, 'Gamma', 'USD');
CREATE TABLE raw.vendors (id INTEGER, vendor_name VARCHAR, is_deleted BOOLEAN);
INSERT INTO raw.vendors VALUES (1, 'Widgets', true), (2, 'Cogs', false), (3, 'Parts', false);
"""


def _render(sql: str) -> str:
    sql = re.sub(r"\{\{ source\('([^']+)', '([^']+)'\) \}\}", lambda m: f"{m[1]}.{m[2]}", sql)
    return re.sub(r"\{\{ ref\('([^']+)'\) \}\}", lambda m: m[1], sql)


@pytest.mark.anyio
async def test_independent_surrogate_keys_never_join_or_scope_each_other(tmp_path: Path) -> None:
    database = tmp_path / "generic.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute(GENERIC_SQL)
    svc = OnboardingService.build(Settings(_env_file=None, var_root=tmp_path / "state", env="test", log_level="ERROR"))
    try:
        svc.connections.register(
            ConnectionSpec(connection_id="generic", company_id="generic", path=str(database), schemas=["raw"])
        )
        agent = Principal(principal_id="agent:test", role=Role.AGENT)
        run = await svc.start_run(agent, "generic", stop_after=StepName.CANONICAL_MAPPING)
        graph = svc.artifact(agent, run.run_id, StepName.JOIN_INFERENCE)
        assert isinstance(graph, JoinGraph)
        assert not [j for j in graph.joins if {j.left_table, j.right_table} == {"raw.customers", "raw.vendors"}]
        mapping = svc.artifact(agent, run.run_id, StepName.CANONICAL_MAPPING)
        profile = svc.artifact(agent, run.run_id, StepName.SCHEMA_PROFILING)
        entities = svc.artifact(agent, run.run_id, StepName.ENTITY_INFERENCE)
        decisions = {
            key: ItemDecision(item_key=key, decision=ReviewDecision.APPROVE)
            for key in [f"mapping:{p.mapping_key}" for p in mapping.proposals if p.requires_review]
            + [f"filter:{f.filter_key}" for f in mapping.row_filters if f.requires_review]
            + [f"join:{j.join_id}" for j in mapping.joins if j.requires_review]
        }
        resolved, _ = resolve(mapping, decisions)
        gen = Generator(
            resolved,
            profile,
            load_ontology(),
            "generic",
            None,
            {c.table: c.primary_key_columns for c in entities.candidates},
        )
        gen.build_staging()
        gen.build_intermediate()
        gen.build_marts()
        with duckdb.connect(str(database)) as con:
            for name, sql in gen.files.items():
                if name.endswith(".sql"):
                    con.execute(f"CREATE VIEW {Path(name).stem} AS {_render(sql)}")
            if "models/marts/dim_customer.sql" in gen.files:
                customers = {r[0] for r in con.execute("SELECT customer_name FROM dim_customer").fetchall()}
                assert customers == {"Acme", "Beta", "Gamma"}  # vendor 1's deletion never removes customer 1
    finally:
        svc.store.engine.dispose()


def test_joins_between_uncertain_entities_require_review(tmp_path: Path) -> None:
    database = tmp_path / "uncertain.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute(
            "CREATE SCHEMA raw; CREATE TABLE raw.customers (customer_id INTEGER, customer_name VARCHAR);"
            "INSERT INTO raw.customers VALUES (1,'a'),(2,'b'),(3,'c'),(4,'d'),(5,'e');"
            "CREATE TABLE raw.invoices (invoice_id INTEGER, customer_id INTEGER, total DECIMAL(10,2));"
            "INSERT INTO raw.invoices VALUES (1,1,1),(2,2,1),(3,3,1),(4,4,1),(5,5,1),(6,1,1)"
        )
    svc = OnboardingService.build(Settings(_env_file=None, var_root=tmp_path / "state", env="test", log_level="ERROR"))
    try:
        svc.connections.register(
            ConnectionSpec(connection_id="unc", company_id="unc", path=str(database), schemas=["raw"])
        )
        import anyio

        agent = Principal(principal_id="agent:test", role=Role.AGENT)
        run = anyio.run(lambda: svc.start_run(agent, "unc", stop_after=StepName.JOIN_INFERENCE))
        entities = svc.artifact(agent, run.run_id, StepName.ENTITY_INFERENCE)
        graph = svc.artifact(agent, run.run_id, StepName.JOIN_INFERENCE)
        confidence = {c.table: c.confidence for c in entities.candidates if c.canonical_entity}
        uncertain = [
            j
            for j in graph.joins
            if confidence.get(j.left_table) is not Confidence.HIGH
            or confidence.get(j.right_table) is not Confidence.HIGH
        ]
        for j in uncertain:
            assert j.requires_review and "ENTITY_UNCERTAIN" in j.reason_codes
    finally:
        svc.store.engine.dispose()


# --------------------------------------------------------------------------- A19 judge rerank metadata


class _AllowedChoice:
    name = "offline-allowed-choice"

    def __init__(self, choice: str) -> None:
        self.choice = choice

    def judge(self, proposal: Any, column: Any, table: Any, ontology: Any) -> dict[str, Any]:
        return {"choice": self.choice, "rationale": "offline rerank", "cited_evidence_ids": []}


def test_judge_rerank_into_a_pii_target_recomputes_safety_metadata() -> None:
    proposal = MappingProposal(
        mapping_key="raw.customers.contact",
        source_table="raw.customers",
        source_column="contact",
        source_field="raw.customers.contact",
        canonical_entity="customer",
        canonical_field="customer_name",
        confidence=Confidence.LOW,
        score=0.54,
        rationale="name/type/context score .54",
        requires_review=True,
        reason_codes=["LOW_CONFIDENCE"],
        alternatives=[ScoredTarget(entity="customer", field="billing_email", score=0.42)],
    )
    column = ColumnProfile(
        table="raw.customers",
        column="contact",
        ordinal=1,
        dtype="VARCHAR",
        row_count=3,
        non_null_count=3,
        null_pct=0,
        distinct_count=3,
        inferred_semantic_type=SemanticType.CATEGORY,
    )
    table = TableProfile(schema_name="raw", table_name="customers", row_count=3, columns=[column])
    ontology = load_ontology()
    out = _apply_judge(_AllowedChoice("billing_email"), proposal, column, table, ontology)
    assert ontology.field("customer", "billing_email").pii
    assert out.canonical_field == "billing_email" and out.score == 0.42
    assert out.pii_handling == "hash" and "PII_FIELD" in out.reason_codes and out.requires_review


@pytest.mark.anyio
async def test_judge_rerank_in_the_workflow_matches_direct_finalization(tmp_path: Path, fixtures_dir: Path) -> None:
    class FirstAlternative:
        name = "offline-first-alternative"

        def judge(self, proposal: Any, column: Any, table: Any, ontology: Any) -> dict[str, Any]:
            return {"choice": proposal.alternatives[0].field, "rationale": "offline", "cited_evidence_ids": []}

    settings = Settings(_env_file=None, var_root=tmp_path, fixtures_root=fixtures_dir, env="test", log_level="ERROR")
    svc = OnboardingService.build(settings, judge=FirstAlternative())
    agent = Principal(principal_id="agent:test", role=Role.AGENT)
    run = await svc.start_run(agent, "fixture:portco_b", stop_after=StepName.CANONICAL_MAPPING)
    mapping = svc.artifact(agent, run.run_id, StepName.CANONICAL_MAPPING)
    reranked = [p for p in mapping.proposals if "JUDGE_REORDERED" in p.reason_codes]
    assert reranked
    ontology = load_ontology()
    for p in reranked:
        fdef = ontology.field(p.canonical_entity, p.canonical_field)
        if fdef.pii:
            assert p.pii_handling is not None and "PII_FIELD" in p.reason_codes
        if p.suggested_transform == "cents_to_major":
            assert fdef.unit == "currency_major"
        if p.suggested_transform == "parse_mixed_date":
            assert fdef.type == "date"
