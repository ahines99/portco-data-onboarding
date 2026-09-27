"""Reproduce synthetic portfolio evidence and a populated SQLite recovery rehearsal.

Run as `uv run python -m scripts.release_evidence`. Never touches existing runtime state.
All reviewer decisions here are automated synthetic test decisions, not live human approval.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from alembic import command
from alembic.config import Config

from src.domain.models import Principal, ReviewDecision, Role, RunStatus, StepName
from src.domain.project_models import ItemDecision
from src.fixtures.generate import ensure_fixture
from src.reporting import render_run_report
from src.settings import PROJECT_ROOT, Settings
from src.workflows.facade import OnboardingService, migrate

AGENT = Principal(principal_id="agent:evidence", role=Role.AGENT)
REVIEWER = Principal(principal_id="synthetic-reviewer", role=Role.REVIEWER)
ADMIN = Principal(principal_id="synthetic-test-operator", role=Role.ADMIN)


async def drive(svc: OnboardingService, fixture: str):
    run = await svc.start_run(AGENT, f"fixture:{fixture}")
    for _ in range(3):
        if run.status is not RunStatus.NEEDS_REVIEW or run.gate == "test_failures":
            break
        decisions = [ItemDecision(item_key=i.item_key, decision=ReviewDecision.APPROVE) for i in run.pending_items]
        if run.gate == "certification":
            svc.certify(REVIEWER, run.run_id, run.pending_items[0].subject_hash, decisions)
        else:
            svc.submit_review(REVIEWER, run.run_id, decisions)
        run = await svc.resume(AGENT, run.run_id)
    return run


def verify(svc: OnboardingService, rid) -> dict[str, Any]:
    receipt = svc.artifact(AGENT, rid, StepName.PUBLISH)
    bundle = svc.artifact(AGENT, rid, StepName.ARTIFACT_GENERATION)
    events, valid = svc.audit(AGENT, rid)
    assert valid
    for file in bundle.files:
        path = Path(receipt.path) / file.path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == file.sha256
    assert (Path(receipt.path) / "certification.json").is_file()
    return {"audit_valid": valid, "audit_events": len(events), "verified_files": len(bundle.files)}


def recovery(svc: OnboardingService, rid, workspace: Path) -> dict[str, Any]:
    before = verify(svc, rid)
    root = svc.settings.var_root
    svc.store.engine.dispose()
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", svc.settings.db_url.replace("%", "%%"))
    # Only this freshly generated disposable test store is downgraded to construct old-version data.
    assert root.resolve().is_relative_to(workspace.resolve())
    command.downgrade(cfg, "0002")
    backup = workspace / "backup"
    shutil.copytree(root, backup)
    with sqlite3.connect(root / "portco.db") as source, sqlite3.connect(backup / "portco.db") as dest:
        source.backup(dest)
    migrate(svc.settings.db_url)
    upgraded = OnboardingService.build(svc.settings)
    assert verify(upgraded, rid) == before
    receipt = upgraded.artifact(AGENT, rid, StepName.PUBLISH)
    target = Path(receipt.path) / "certification.json"
    upgraded.store.engine.dispose()
    target.write_text("simulated loss of publication metadata", encoding="utf-8")
    # Restore to the SAME runtime path: receipts intentionally bind absolute publication paths.
    with sqlite3.connect(backup / "portco.db") as source, sqlite3.connect(root / "portco.db") as dest:
        source.backup(dest)
    shutil.copy2(backup / target.relative_to(root), target)
    migrate(svc.settings.db_url)
    restored = OnboardingService.build(svc.settings)
    assert verify(restored, rid) == before
    assert restored.get_run(AGENT, rid).status is RunStatus.COMPLETE
    restored.store.engine.dispose()
    return {"populated_0002_to_0003": "pass", "same_path_backup_restore": "pass", **before}


async def main() -> None:
    initial_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True).strip())
    root = Path(tempfile.mkdtemp(prefix="pe-"))
    print(f"Private evidence workspace: {root}", flush=True)
    out = PROJECT_ROOT / "docs" / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    def save(name: str, data: Any) -> None:
        value = data if isinstance(data, str) else json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
        for prefix in (str(root), root.as_posix(), str(root).replace("\\", "\\\\")):
            value = value.replace(prefix, "<private-workspace>")
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8", newline="\n")
        paths.append(path)

    fixtures = root / "fixtures"
    for name in ("portco_a", "portco_a__malformed"):
        ensure_fixture(name, fixtures)
    timings = []
    services = []
    for n in range(3):
        svc = OnboardingService.build(
            Settings(_env_file=None, var_root=root / f"run{n}", fixtures_root=fixtures, env="test")
        )
        start = time.perf_counter()
        run = await drive(svc, "portco_a")
        cold = time.perf_counter() - start
        assert run.status is RunStatus.COMPLETE
        verification = verify(svc, run.run_id)
        services.append((svc, run))
        start = time.perf_counter()
        replay = await svc.rerun_from(ADMIN, run.run_id, StepName.CONNECTION_VALIDATION)
        assert replay.status is RunStatus.COMPLETE
        assert verify(svc, run.run_id)["verified_files"] == verification["verified_files"]
        timings.append({"cold_seconds": round(cold, 3), "reused_seconds": round(time.perf_counter() - start, 3)})
    svc, run = services[0]
    save("success-report.md", render_run_report(svc, AGENT, run.run_id))
    report = svc.artifact(AGENT, run.run_id, StepName.AUTOMATED_TESTS)
    save("reconciliation.json", report.model_dump(mode="json"))
    receipt = svc.artifact(AGENT, run.run_id, StepName.PUBLISH)
    save("certification.json", (Path(receipt.path) / "certification.json").read_text(encoding="utf-8"))
    save("gross_margin_pct.yml", svc.bundle_file(AGENT, run.run_id, "models/semantic/metrics/gross_margin_pct.yml"))
    bundle = svc.artifact(AGENT, run.run_id, StepName.ARTIFACT_GENERATION)
    example = next(f for f in bundle.files if f.path.startswith("models/staging/") and f.path.endswith(".sql"))
    save("staging-example.sql", svc.bundle_file(AGENT, run.run_id, example.path))
    findings = svc.findings(AGENT, run.run_id)
    selected = next(f for f in findings if f.evidence)
    save(
        "finding-lineage.json",
        {"finding": selected.model_dump(mode="json"), "lineage": svc.lineage(AGENT, selected.finding_id)},
    )
    save("recovery.json", recovery(svc, run.run_id, root))
    bad = OnboardingService.build(
        Settings(_env_file=None, var_root=root / "failure", fixtures_root=fixtures, env="test")
    )
    failed = await drive(bad, "portco_a__malformed")
    assert failed.gate == "test_failures"
    assert not list(bad.settings.published_root.rglob("certification.json"))
    save("failure-report.md", render_run_report(bad, AGENT, failed.run_id))
    save(
        "benchmark.json",
        {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "method": (
                "3 fresh fixture A workflows, each followed by an unchanged-input rerun; "
                "synthetic approvals; no human waiting; not a scale benchmark"
            ),
            "runs": timings,
        },
    )
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip(),
        "dirty": initial_dirty,
        "command": "uv run python -m scripts.release_evidence",
        "reviewer": "AUTOMATED SYNTHETIC TEST DECISIONS; not independent human review",
        "normalization": (
            "Private workspace prefix replaced; raw runtime state retained locally. "
            "Shared metadata is not an unmodified signed audit export."
        ),
        "versions": {p: importlib.metadata.version(p) for p in ("dbt-core", "dbt-duckdb", "duckdb", "sqlparse", "mcp")},
        "lock_sha256": hashlib.sha256((PROJECT_ROOT / "uv.lock").read_bytes()).hexdigest(),
        "fixture_truth_sha256": hashlib.sha256(
            (PROJECT_ROOT / "fixtures/portco_a/ground_truth.yaml").read_bytes()
        ).hexdigest(),
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }
    save("manifest.json", manifest)
    (PROJECT_ROOT / "var").mkdir(exist_ok=True)
    (PROJECT_ROOT / "var" / "release-evidence-workspace.txt").write_text(str(root), encoding="utf-8")
    print(
        "PASS: 3 complete runs, verified reuse, negative scenario, populated upgrade and same-path restore", flush=True
    )


if __name__ == "__main__":
    anyio.run(main)
