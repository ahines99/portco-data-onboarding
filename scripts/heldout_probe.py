"""A small unfamiliar-schema probe; reports failures without tuning the mapper."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import anyio
import duckdb

from src.domain.models import Principal, Role, StepName
from src.domain.ontology import load_ontology
from src.domain.project_models import ConnectionSpec
from src.settings import PROJECT_ROOT, Settings
from src.workflows.facade import OnboardingService
from src.workflows.versioning import pipeline_version

# Declared before execution; none of these labels is added to synonyms or scoring rules.
LABELS = {
    "legacy.payer_registry.account_key": "customer.customer_id",
    "legacy.payer_registry.legal_label": "customer.customer_name",
    "legacy.payer_registry.ccy_iso": "customer.currency",
    "legacy.sales_deals.deal_key": "opportunity.opportunity_id",
    "legacy.sales_deals.buyer_key": "opportunity.crm_account_id",
    "legacy.sales_deals.rev": "opportunity.amount",
    "legacy.invoice_register.document_key": "invoice.invoice_id",
    "legacy.invoice_register.buyer_key": "invoice.customer_id",
    "legacy.invoice_register.net_minor": "invoice.total_amount",
    "legacy.invoice_register.issue_date": "invoice.invoice_date",
}


async def main() -> None:
    ontology = load_ontology()
    for target in LABELS.values():
        entity, field = target.split(".")
        assert field in ontology.entities[entity].fields
    root = Path(tempfile.mkdtemp(prefix="ph-"))
    db = root / "heldout.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA legacy")
        conn.execute("CREATE TABLE legacy.payer_registry(account_key VARCHAR, legal_label VARCHAR, ccy_iso VARCHAR)")
        conn.execute("CREATE TABLE legacy.sales_deals(deal_key VARCHAR, buyer_key VARCHAR, rev DECIMAL(12,2))")
        conn.execute(
            "CREATE TABLE legacy.invoice_register("
            "document_key VARCHAR, buyer_key VARCHAR, net_minor BIGINT, issue_date DATE)"
        )
        for i in range(1, 9):
            conn.execute("INSERT INTO legacy.payer_registry VALUES (?, ?, ?)", [f"A{i}", f"Synthetic Buyer {i}", "USD"])
            conn.execute("INSERT INTO legacy.sales_deals VALUES (?, ?, ?)", [f"D{i}", f"A{i}", 100 + i])
            conn.execute(
                "INSERT INTO legacy.invoice_register VALUES (?, ?, ?, ?)",
                [f"I{i}", f"A{i}", 10000 + i * 100, date(2026, 1, i)],
            )
    svc = OnboardingService.build(Settings(_env_file=None, var_root=root / "state", env="test"))
    svc.connections.register(
        ConnectionSpec(
            connection_id="heldout:v1", company_id="heldout", path=str(db), schemas=["legacy"], as_of=date(2026, 1, 31)
        )
    )
    principal = Principal(principal_id="agent:heldout", role=Role.AGENT)
    run = await svc.start_run(principal, "heldout:v1")
    mapping = svc.artifact(principal, run.run_id, StepName.CANONICAL_MAPPING)
    proposals = {p.source_field: p for p in mapping.proposals}
    rows = []
    for source, expected in LABELS.items():
        p = proposals.get(source)
        actual = f"{p.canonical_entity}.{p.canonical_field}" if p else None
        rows.append(
            {
                "source": source,
                "expected": expected,
                "actual": actual,
                "correct": actual == expected,
                "requires_review": p.requires_review if p else None,
                "confidence": p.confidence.value if p else None,
            }
        )
    result = {
        "scope": "10 labeled columns in 3 unfamiliar tables, 8 records/table; no outcome-based mapper changes",
        "limitations": (
            "Small probe created by the implementation assistant, not an external blinded dataset. "
            "net_minor is cents; labels score targets only, not unit conversion correctness."
        ),
        "pipeline_version": pipeline_version(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "labels_sha256": hashlib.sha256(json.dumps(LABELS, sort_keys=True).encode()).hexdigest(),
        "correct": sum(r["correct"] for r in rows),
        "labeled": len(rows),
        "proposal_count": len(proposals),
        "missing_predictions": sum(r["actual"] is None for r in rows),
        "wrong_without_review": sum(not r["correct"] and r["requires_review"] is False for r in rows),
        "status": run.status.value,
        "gate": run.gate,
        "rows": rows,
        "unlabeled_proposals": sorted(set(proposals) - set(LABELS)),
    }
    out = PROJECT_ROOT / "docs/evidence/heldout-probe.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"Probe: {result['correct']}/{result['labeled']} target matches; "
        f"{result['wrong_without_review']} wrong without review"
    )


if __name__ == "__main__":
    anyio.run(main)
