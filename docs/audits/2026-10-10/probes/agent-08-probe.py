"""Reproduce audit 08 findings with an isolated, synthetic local source.

Run with this repository's virtualenv Python from any working directory:
    .venv/Scripts/python.exe var/audit-2026-10-10/agent-08-probe.py

Uses real inference, pure Gate A resolution, generation and DuckDB execution.
Approval decisions below are an offline simulation: they are never written to
the approval store, and no publication or external model calls are performed.
Exit 0 means both currently observed defects were reproduced. An assertion
failure can mean a finding has been fixed and needs re-evaluation.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def find_repository() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src/services/joins.py").is_file():
            return candidate
    raise RuntimeError("Place this probe within the audited repository")


ROOT = find_repository()
sys.path.insert(0, str(ROOT))

# This is a standalone subprocess. Avoid inheriting an operator's database,
# credential, live-model or production settings; never read the project .env.
for variable in list(os.environ):
    if variable.startswith("PORTCO_"):
        del os.environ[variable]

import duckdb  # noqa: E402

from src.domain.models import Confidence, Principal, ReviewDecision, Role, StepName  # noqa: E402
from src.domain.ontology import load_ontology  # noqa: E402
from src.domain.project_models import (  # noqa: E402
    ColumnProfile,
    ConnectionSpec,
    ItemDecision,
    MappingProposal,
    ScoredTarget,
    SemanticType,
    TableProfile,
)
from src.services.gates import resolve  # noqa: E402
from src.services.generation import Generator  # noqa: E402
from src.services.mapping import _apply_judge  # noqa: E402
from src.settings import Settings  # noqa: E402
from src.workflows.facade import OnboardingService  # noqa: E402


INPUT_SQL = """
CREATE SCHEMA raw;
CREATE TABLE raw.customers (
    id INTEGER, customer_name VARCHAR, currency VARCHAR
);
INSERT INTO raw.customers VALUES
    (1, 'Acme', 'USD'), (2, 'Beta', 'USD'), (3, 'Gamma', 'USD');
CREATE TABLE raw.vendors (
    id INTEGER, vendor_name VARCHAR, is_deleted BOOLEAN
);
INSERT INTO raw.vendors VALUES
    (1, 'Widgets', true), (2, 'Cogs', false), (3, 'Parts', false);
"""


def render_dbt_references(sql: str) -> str:
    """Resolve only these generated source/ref calls against synthetic views."""
    sql = re.sub(
        r"\{\{ source\('([^']+)', '([^']+)'\) \}\}",
        lambda match: f"{match[1]}.{match[2]}",
        sql,
    )
    return re.sub(r"\{\{ ref\('([^']+)'\) \}\}", lambda match: match[1], sql)


async def generic_key_scope_probe() -> dict:
    with tempfile.TemporaryDirectory(prefix="portco-audit08-probe-") as scratch:
        work = Path(scratch)
        database = work / "synthetic-source.duckdb"
        with duckdb.connect(str(database)) as connection:
            connection.execute(INPUT_SQL)
            original_customers = connection.execute(
                "SELECT id, customer_name FROM raw.customers ORDER BY id"
            ).fetchall()

        settings = Settings(
            _env_file=None,
            var_root=work / "state",
            env="test",
            llm_enabled=False,
            llm_mode="replay",
            log_level="ERROR",
        )
        service = OnboardingService.build(settings)
        try:
            service.connections.register(
                ConnectionSpec(
                    connection_id="audit08",
                    company_id="audit08",
                    path=str(database),
                    schemas=["raw"],
                )
            )
            agent = Principal(principal_id="agent:audit08", role=Role.AGENT)
            run = await service.start_run(agent, "audit08", stop_after=StepName.CANONICAL_MAPPING)
            mapping = service.artifact(agent, run.run_id, StepName.CANONICAL_MAPPING)
            profile = service.artifact(agent, run.run_id, StepName.SCHEMA_PROFILING)
            entities = service.artifact(agent, run.run_id, StepName.ENTITY_INFERENCE)

            # Simulate ordinary approvals for requested mappings and vendor
            # soft deletion. There is deliberately no join decision.
            decision_keys = [
                f"mapping:{proposal.mapping_key}" for proposal in mapping.proposals if proposal.requires_review
            ] + [f"filter:{row_filter.filter_key}" for row_filter in mapping.row_filters if row_filter.requires_review]
            decisions = {key: ItemDecision(item_key=key, decision=ReviewDecision.APPROVE) for key in decision_keys}
            resolved, duplicates = resolve(mapping, decisions)
            generator = Generator(
                resolved,
                profile,
                load_ontology(),
                "audit08",
                None,
                {candidate.table: candidate.primary_key_columns for candidate in entities.candidates},
            )
            generator.build_staging()
            generator.build_intermediate()
            generator.build_marts()
            sql_files = {name: contents for name, contents in generator.files.items() if name.endswith(".sql")}
            with duckdb.connect(str(database)) as connection:
                # Generator insertion order is staging, topologically ordered
                # intermediate models, then marts for this synthetic source.
                for name, contents in sql_files.items():
                    sql = render_dbt_references(contents)
                    connection.execute(f"CREATE VIEW {Path(name).stem} AS {sql}")
                final_customers = connection.execute(
                    "SELECT customer_id, customer_name FROM dim_customer ORDER BY customer_id"
                ).fetchall()

            original_ids = {str(row[0]) for row in original_customers}
            final_ids = {str(row[0]) for row in final_customers}
            automatic_joins = [join for join in resolved.joins if not join.requires_review]
            result = {
                "input_sql": INPUT_SQL,
                "entities": entities.model_dump(mode="json"),
                "decision_keys": decision_keys,
                "resolved_joins": [join.model_dump(mode="json") for join in resolved.joins],
                "duplicates": duplicates,
                "generated_sql": sql_files,
                "original_customers": original_customers,
                "final_customers": final_customers,
                "incorrectly_excluded_customer_ids": sorted(original_ids - final_ids),
                "defect_reproduced": len(automatic_joins) == 2 and original_ids - final_ids == {"1"},
            }
            return result
        finally:
            service.store.engine.dispose()


def judge_metadata_probe() -> dict:
    class AllowedChoiceStub:
        name = "offline-allowed-choice-stub"

        def judge(self, proposal, column, table, ontology):
            return {
                "choice": "billing_email",
                "rationale": "Offline permitted-target rerank for metadata regression",
                "cited_evidence_ids": [str(proposal.evidence_ids[0])],
            }

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
        evidence_ids=["6f1c2a9e-3b7d-4c55-9a51-0d2f7e1b8c44"],
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
        uniqueness_ratio=1,
        inferred_semantic_type=SemanticType.CATEGORY,
    )
    table = TableProfile(schema_name="raw", table_name="customers", row_count=3, columns=[column])
    ontology = load_ontology()
    result = _apply_judge(AllowedChoiceStub(), proposal, column, table, ontology)
    return {
        "before": proposal.model_dump(mode="json"),
        "after": result.model_dump(mode="json"),
        "target_pii_class": ontology.field("customer", "billing_email").pii,
        "defect_reproduced": (
            result.canonical_field == "billing_email" and result.pii_handling is None and result.score == proposal.score
        ),
    }


async def main() -> None:
    results = {
        "generic_key_scope": await generic_key_scope_probe(),
        "judge_metadata": judge_metadata_probe(),
    }
    output = ROOT / "var/audit-2026-10-10/agent-08-probe-results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    summary = {
        "output": str(output),
        "generic_key_scope_reproduced": results["generic_key_scope"]["defect_reproduced"],
        "incorrectly_excluded_customer_ids": results["generic_key_scope"]["incorrectly_excluded_customer_ids"],
        "judge_metadata_reproduced": results["judge_metadata"]["defect_reproduced"],
    }
    print(json.dumps(summary, indent=2))
    assert all(result["defect_reproduced"] for result in results.values()), (
        "A previously observed defect did not reproduce; inspect the report and evaluate whether it was fixed."
    )


if __name__ == "__main__":
    asyncio.run(main())
