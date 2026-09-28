"""Exercise external CSV ingestion through publication using synthetic extracts only.

Run: python -m scripts.smoke_csv_source --workdir var/csv-smoke
Review decisions here are automated test decisions, not independent human approval.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio

from src.adapters.csv_source import import_csv
from src.domain.models import Principal, ReviewDecision, ReviewGate, Role, RunStatus, StepName
from src.domain.project_models import ItemDecision
from src.fixtures.category_domains import fixture_category_domains
from src.fixtures.portco_a import build
from src.settings import Settings
from src.workflows.facade import OnboardingService

EXPECTED_METRICS = {
    "active_customers",
    "arr",
    "billings",
    "cogs",
    "ebitda",
    "gross_margin_pct",
    "mrr",
    "opex",
    "revenue_recognized",
}


def code_provenance() -> dict[str, Any]:
    """Pin the actual exercised implementation, including an uncommitted worktree."""
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / "src").rglob("*.py")), Path(__file__).resolve()]
    return {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()),
        "implementation_sha256": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
    }


def extracts(root: Path) -> Path:
    """Write synthetic business extracts; the importer has no fixture dependency."""
    fixture = build()
    root.mkdir(parents=True, exist_ok=True)
    tables = []
    for table in fixture.tables:
        name = f"{table.schema}.{table.name}.csv"
        with (root / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([name for name, _ in table.columns])
            writer.writerows([[r"\N" if v is None else str(v) for v in row] for row in table.rows])
        tables.append(
            {"schema_name": table.schema, "table_name": table.name, "file": name, "columns": dict(table.columns)}
        )
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_id": "synthetic-extract-v1",
                "company_id": "csv_demo",
                "as_of": fixture.as_of.isoformat(),
                "tables": tables,
                "category_domains": fixture_category_domains("portco_a"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


async def exercise(workdir: Path) -> dict[str, Any]:
    provenance = code_provenance()
    manifest = extracts(workdir / "extracts")
    settings = Settings(env="test", var_root=workdir / "runtime", log_level="WARNING")
    receipt = import_csv(manifest, manifest.parent, settings.var_root / "sources")
    return await exercise_registered(
        settings,
        receipt,
        provenance,
        data_provenance="synthetic portco_a rows exported as CSV; no customer-data or live-system claim",
    )


async def exercise_registered(
    settings: Settings,
    receipt: dict[str, Any],
    provenance: dict[str, Any],
    *,
    data_provenance: str,
    identity_prefix: str = "csv-smoke",
) -> dict[str, Any]:
    """Verify the same governed workflow for an already registered source snapshot."""
    service = OnboardingService.build(settings)
    companies = (receipt["company_id"],)
    agent = Principal(principal_id=f"{identity_prefix}:agent", role=Role.AGENT, company_ids=companies)
    reviewer = Principal(principal_id=f"{identity_prefix}:reviewer", role=Role.REVIEWER, company_ids=companies)
    run = await service.start_run(agent, receipt["connection_id"])
    for _ in range(3):
        if run.status != RunStatus.NEEDS_REVIEW:
            break
        if run.gate == "test_failures":
            raise RuntimeError("CSV smoke reconciliation failed; test never waives failures")
        decisions = [
            ItemDecision(
                item_key=item.item_key,
                decision=(
                    ReviewDecision.APPROVE_WITH_OVERRIDE
                    if item.item_key == "mapping:crm.opportunities.rev"
                    else ReviewDecision.APPROVE
                ),
                override={"canonical_field": "amount"} if item.item_key == "mapping:crm.opportunities.rev" else None,
            )
            for item in run.pending_items
        ]
        if run.gate == "certification":
            service.certify(reviewer, run.run_id, run.pending_items[0].subject_hash, decisions)
        else:
            service.submit_review(
                reviewer,
                run.run_id,
                decisions,
                subject_hash=run.pending_items[0].subject_hash,
                gate=ReviewGate(run.gate),
            )
        # Rebuild from persisted registration and workflow state between every gate.
        service.store.engine.dispose()
        service = OnboardingService.build(settings)
        run = await service.resume(agent, run.run_id)
    if run.status != RunStatus.COMPLETE:
        raise RuntimeError(f"CSV smoke did not complete: {run.status}")
    report = service.artifact(agent, run.run_id, StepName.AUTOMATED_TESTS)
    publication = service.artifact(agent, run.run_id, StepName.PUBLISH)
    bundle = service.artifact(agent, run.run_id, StepName.ARTIFACT_GENERATION)
    if not report.passed or report.dbt_exit_code != 0 or report.failing_checks or report.waived_checks:
        raise RuntimeError("CSV smoke requires passed reconciliation without waivers")
    if set(publication.published_metrics) != EXPECTED_METRICS or publication.excluded_metrics:
        raise RuntimeError("CSV smoke must publish all nine expected metrics")
    if not all(check.passed for check in report.reconciliation):
        raise RuntimeError("CSV smoke reconciliation contains an unsuccessful check")
    destination = Path(publication.path).resolve()
    for artifact in bundle.files:
        original = destination / artifact.path
        target = original.resolve()
        if not target.is_relative_to(destination) or original.is_symlink():
            raise RuntimeError("CSV smoke publication file escapes its destination")
        if hashlib.sha256(target.read_bytes()).hexdigest() != artifact.sha256:
            raise RuntimeError("CSV smoke published file does not match the generated bundle")
    published_paths = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
    if published_paths != {artifact.path for artifact in bundle.files} | {"certification.json"}:
        raise RuntimeError("CSV smoke publication file set differs from the certified bundle")
    events, audit_valid = service.audit(agent, run.run_id)
    if not audit_valid or not events:
        raise RuntimeError("CSV smoke audit chain verification failed")
    service.store.engine.dispose()
    result = {
        "data_provenance": data_provenance,
        "review_provenance": "automated separate reviewer test identity",
        "connection_id": receipt["connection_id"],
        "snapshot_sha256": receipt["snapshot_sha256"],
        "input_tables": len(receipt["inputs"]),
        "input_rows": sum(t["rows"] for t in receipt["inputs"]),
        "run_id": str(run.run_id),
        "status": run.status.value,
        "test_report": report.model_dump(mode="json"),
        "publication": publication.model_dump(mode="json"),
    }
    result["shareable_summary"] = {
        "format_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        **provenance,
        **{
            key: result[key]
            for key in (
                "data_provenance",
                "review_provenance",
                "connection_id",
                "snapshot_sha256",
                "input_tables",
                "input_rows",
                "run_id",
                "status",
            )
        },
        "service_rebuilt_at_review_gates": True,
        "test_report_passed": report.passed,
        "dbt_exit_code": report.dbt_exit_code,
        "reconciliation": [
            {
                "name": check.name,
                "passed": check.passed,
                "blocking": check.blocking,
                "expected_group_count": len(check.expected),
                "actual_group_count": len(check.actual),
            }
            for check in report.reconciliation
        ],
        "waived_checks": report.waived_checks,
        "published_metrics": sorted(publication.published_metrics),
        "manifest_hash": bundle.manifest_hash,
        "generated_file_hashes_verified": len(bundle.files),
        "published_file_count": len(published_paths),
        "audit_chain_valid": audit_valid,
        "audit_event_count": len(events),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir", type=Path, required=True, help="New work directory; existing source ids are immutable"
    )
    parser.add_argument("--summary", type=Path, help="Optional shareable summary destination without absolute paths")
    args = parser.parse_args()
    result = anyio.run(exercise, args.workdir.resolve())
    output = args.workdir / "evidence.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary_output = args.summary or args.workdir / "summary.json"
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(result["shareable_summary"], indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(output)}, indent=2))


if __name__ == "__main__":
    main()
