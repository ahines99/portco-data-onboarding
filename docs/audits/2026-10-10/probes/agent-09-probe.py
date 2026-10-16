import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(
    0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()))
)

import anyio
from mcp import Client
from typer.testing import CliRunner

from src.cli import app
from src.domain.models import ReviewGate
from src.settings import Settings
from tests.conftest import AGENT, REVIEWER, decide_all, drive, make_service
from tests.test_mcp import Harness

ROOT = (
    next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
    / "var"
    / "audit-2026-10-10"
)
ROOT.mkdir(parents=True, exist_ok=True)
out = {}


async def main():
    with TemporaryDirectory(prefix="a9-", dir=ROOT, ignore_cleanup_errors=True) as temporary:
        root = Path(temporary)
        zero = make_service(root / "zero", step_max_attempts=0)
        run = await zero.start_run(AGENT, "fixture:portco_a")
        out["zero_attempts"] = {
            "status": run.status.value,
            "error": run.error,
            "lease_owner": run.lease_owner,
            "steps": zero.steps(AGENT, run.run_id),
        }
        out["accepted_bad_settings"] = Settings(
            _env_file=None,
            dbt_timeout_seconds=-100,
            step_timeout_seconds=-20,
            step_max_attempts=0,
            lease_margin_seconds=-200,
            approval_ttl_hours=-1,
            sandbox_keep_attempts=-1,
        ).model_dump(
            include={
                "dbt_timeout_seconds",
                "step_timeout_seconds",
                "step_max_attempts",
                "lease_margin_seconds",
                "approval_ttl_hours",
                "sandbox_keep_attempts",
            }
        )
        zero.store.engine.dispose()

        svc = make_service(root / "publish")
        run = await drive(svc, certify=False)
        out["before_certification"] = {"status": run.status.value, "gate": run.gate}
        h = Harness(svc)
        h.as_(REVIEWER)
        async with Client(h.server) as client:
            invalid = await client.call_tool(
                "certify_run",
                {
                    "run_id": str(run.run_id),
                    "subject_hash": run.pending_items[0].subject_hash,
                    "bundle_decision": "typo",
                },
            )
            out["invalid_decision"] = {"is_error": invalid.is_error, "body": invalid.structured_content}
            approval = svc.certify(
                REVIEWER, run.run_id, run.pending_items[0].subject_hash, decide_all(run.pending_items)
            )
            h.as_(AGENT)
            result = await client.call_tool("run_sandbox_tests", {"run_id": str(run.run_id)})
            with svc.store.tx() as tx:
                pubs = tx.publications.for_run(run.run_id)
            out["test_tool_after_certification"] = {
                "is_error": result.is_error,
                "body": result.structured_content,
                "publications": len(pubs),
                "publication_states": [p["state"] for p in pubs],
                "published_files_exist": [Path(p["receipt"]["path"]).exists() for p in pubs],
            }
        svc.store.engine.dispose()

    return out


anyio.run(main)
with TemporaryDirectory(prefix="a9-cli-", dir=ROOT, ignore_cleanup_errors=True) as temporary:
    from src.adapters.faults import FaultInjector

    svc = make_service(Path(temporary), faults=FaultInjector.parse("adapter.probe:unavailable"), step_max_attempts=1)
    with patch("src.cli._service", return_value=svc):
        result = CliRunner().invoke(app, ["run", "--fixture", "portco_a"])
    out["cli_failed_run"] = {"exit_code": result.exit_code, "output": result.output}
    svc.store.engine.dispose()

(ROOT / "agent-09-probe.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
print(json.dumps(out, indent=2, default=str))
