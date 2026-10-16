"""Isolated financial probes; synthetic data, generated dbt, no production state."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import json
import sys

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT))
import duckdb
from src.adapters.artifact_store import ArtifactStore
from src.domain.hashing import content_hash
from src.domain.models import Confidence, ReviewDecision
from src.domain.ontology import load_ontology
from src.domain.project_models import (
    MappingProposal,
    MappingSet,
    ItemDecision,
    JoinCandidate,
    ColumnProfile,
    TableProfile,
    SchemaProfile,
    SemanticType,
    ArtifactFile,
    ArtifactBundle,
    ConnectionSpec,
)
from src.services.gates import resolve
from src.services.generation import Generator
from src.services.sandbox import build_and_test
from src.settings import Settings

OUT = ROOT / "var" / "audit-2026-10-10"
OUT.mkdir(parents=True, exist_ok=True)
BASE = OUT / ("financial-" + uuid4().hex[:6])
BASE.mkdir(parents=True)


def run_case(name, label, reject_join):
    root = BASE / name
    root.mkdir()
    source = root / "input.duckdb"
    with duckdb.connect(str(source)) as con:
        con.execute("CREATE SCHEMA erp")
        con.execute("CREATE TABLE erp.gl_accounts(account_code VARCHAR, account_type VARCHAR)")
        con.execute("INSERT INTO erp.gl_accounts VALUES (?, ?)", ["4000", label])
        con.execute(
            "CREATE TABLE erp.journal_lines(journal_id VARCHAR, line_number INTEGER, account_code VARCHAR, posting_date DATE, debit_amount DECIMAL(18,2), credit_amount DECIMAL(18,2))"
        )
        con.execute("INSERT INTO erp.journal_lines VALUES ('j1', 1, '4000', '2026-01-10', 0, 100)")
        tables = []
        proposals = []
        entities = {"erp.gl_accounts": "gl_account", "erp.journal_lines": "gl_entry"}
        for table, entity in entities.items():
            cols = []
            for i, (col, dtype, *_rest) in enumerate(con.execute("DESCRIBE " + table).fetchall()):
                is_money = col in {"debit_amount", "credit_amount"}
                sem = (
                    SemanticType.MONEY
                    if is_money
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
                        category_values=[label] if col == "account_type" else None,
                    )
                )
                proposals.append(
                    MappingProposal(
                        mapping_key=table + "." + col,
                        source_table=table,
                        source_column=col,
                        source_field=table + "." + col,
                        canonical_entity=entity,
                        canonical_field=col,
                        confidence=Confidence.HIGH,
                        score=1,
                        rationale="Synthetic reviewed exact-name mapping",
                        requires_review=True,
                    )
                )
            tables.append(TableProfile(schema_name="erp", table_name=table.split(".")[1], row_count=1, columns=cols))
    join = JoinCandidate(
        join_id="erp.journal_lines.account_code->erp.gl_accounts.account_code",
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
    ms = MappingSet(
        proposals=proposals, joins=[join], entity_tables=entities, primary_tables={v: k for k, v in entities.items()}
    )
    decisions = {
        f"mapping:{p.mapping_key}": ItemDecision(item_key=f"mapping:{p.mapping_key}", decision=ReviewDecision.APPROVE)
        for p in proposals
    }
    decisions["join:" + join.join_id] = ItemDecision(
        item_key="join:" + join.join_id, decision=ReviewDecision.REJECT if reject_join else ReviewDecision.APPROVE
    )
    resolved, duplicate = resolve(ms, decisions)
    assert not duplicate
    profile = SchemaProfile(connection_id="probe", company_id="probe", source_fingerprint="synthetic", tables=tables)
    generator = Generator(
        resolved,
        profile,
        load_ontology(),
        "probe",
        date(2026, 1, 31),
        {"erp.gl_accounts": ["account_code"], "erp.journal_lines": ["journal_id", "line_number"]},
    )
    files = generator.build()
    blobs = ArtifactStore(root / "blobs")
    entries = [
        ArtifactFile(path=p, sha256=blobs.put_bytes(t.encode()), kind="probe", size=len(t.encode()))
        for p, t in files.items()
    ]
    bundle = ArtifactBundle(
        mapping_hash=resolved.content_hash(),
        files=entries,
        manifest_hash=content_hash([(f.path, f.sha256) for f in entries]),
        generated_metrics=generator.generated_metrics,
        not_generated=generator.not_generated,
        models=[p.rsplit("/", 1)[-1][:-4] for p in files if p.startswith("models/") and p.endswith(".sql")],
    )
    spec = ConnectionSpec(
        connection_id="probe", company_id="probe", path=str(source.resolve()), as_of=date(2026, 1, 31)
    )
    ctx = SimpleNamespace(
        settings=Settings(_env_file=None, env="test", var_root=root.resolve()),
        run=SimpleNamespace(run_id=uuid4()),
        services={},
        blobs=blobs,
        adapter=lambda: SimpleNamespace(spec=spec),
        close=lambda: None,
    )
    report = build_and_test(ctx, bundle, resolved, "synthetic")
    result = {
        "case": name,
        "account_type": label,
        "rejected_keys": resolved.rejected_keys,
        "accepted_join_count": len(resolved.joins),
        "generated_gl_sql": files["models/marts/fct_gl_entry.sql"],
        "report": report.model_dump(mode="json"),
    }
    (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "case": name,
                "passed": report.passed,
                "dbt_exit": report.dbt_exit_code,
                "accepted_join_count": len(resolved.joins),
                "rejected_keys": resolved.rejected_keys,
                "reconciliation": [(c.name, c.passed, c.actual) for c in report.reconciliation],
            },
            default=str,
        ),
        flush=True,
    )
    return result


results = [run_case("bad_domain", "Revenue", False), run_case("rejected_join", "revenue", True)]
(OUT / "agent-06-probe-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print("Evidence root: " + str(BASE), flush=True)
