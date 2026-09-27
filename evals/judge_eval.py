"""Judge vs deterministic baseline (POD-608): `python -m evals.judge_eval [--mode replay|record|live]`.

Compares top-1 mapping accuracy, abstention rate and per-confidence calibration on fixtures A and B.
The judge ships enabled only if it beats the baseline on accuracy with no calibration regression
(ADR-0010). Live/record modes need Anthropic credentials; replay (default) never touches the network.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from typing import Any

import anyio

from evals.checks import mapping_coverage, mapping_scores
from evals.drivers import ADMIN, CaseRun, build_service, drive
from src.domain.models import Confidence, StepName
from src.domain.ontology import load_ontology
from src.domain.project_models import ColumnProfile, MappingProposal, ScoredTarget, SemanticType, TableProfile
from src.services.judge import ClaudeJudge
from src.services.mapping import _apply_judge
from src.settings import PROJECT_ROOT, get_settings

OUT = PROJECT_ROOT / "evals" / "reports" / "judge_comparison.md"


def total_cost(verdicts: list[dict[str, Any]]) -> float | None:
    usages = [v["usage"] for v in verdicts if v.get("usage")]
    if any(u.get("cost_usd") is None for u in usages):
        return None
    return round(sum(float(u["cost_usd"]) for u in usages), 4)


async def score(fixture: str, llm: bool, mode: str, root: Any) -> dict[str, Any]:
    svc = build_service(root / f"{fixture}_{'judge' if llm else 'base'}", llm_enabled=llm, llm_mode=mode)
    run = await drive(svc, fixture, "gate_a")
    acc, buckets = mapping_scores(CaseRun(svc, run, 0.0))
    ms = svc.artifact(ADMIN, run.run_id, StepName.CANONICAL_MAPPING)
    judged = [p for p in ms.proposals if p.judge]
    applied = [p for p in judged if p.judge and p.judge.get("applied")]
    cost = total_cost([p.judge or {} for p in judged])
    return {
        "accuracy": round(acc, 4),
        "calibration": {k: round(sum(v) / len(v), 3) for k, v in buckets.items() if v},
        "consulted": len(judged),
        "applied": len(applied),
        "abstained": sum(1 for p in judged if (p.judge or {}).get("choice") == "ABSTAIN"),
        "cost_usd": cost,
        "truth_coverage": mapping_coverage(CaseRun(svc, run, 0.0)),
    }


def challenge_scores(mode: str, judge: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Held-out reranking probes, never supplied to deterministic mapping rules as training data.

    These isolate the judge's candidate-choice task; they are not full pipeline accuracy estimates.
    Stable evidence ids permit cassette replay across runs. Both recoverable mistakes and already
    correct proposals must be represented, including low and medium confidence.
    """
    judge = judge or ClaudeJudge.from_settings(get_settings().model_copy(update={"llm_mode": mode}))
    ontology = load_ontology()
    cases = [
        ("KUNAG", SemanticType.ID, "status", "customer_id", "customer_id", Confidence.MEDIUM),
        ("payment_due_on", SemanticType.DATE, "invoice_date", "due_date", "due_date", Confidence.LOW),
        ("document_currency", SemanticType.CATEGORY, "currency", "status", "currency", Confidence.MEDIUM),
        ("invoice_issued_on", SemanticType.DATE, "invoice_date", "due_date", "invoice_date", Confidence.LOW),
    ]
    base_hits, judge_hits = [], []
    base_buckets: dict[str, list[bool]] = {}
    judge_buckets: dict[str, list[bool]] = {}
    verdicts = []
    for column, semantic, first, alternative, expected, confidence in cases:
        col = ColumnProfile(
            table="heldout.billing_document",
            column=column,
            ordinal=1,
            dtype="DATE" if semantic is SemanticType.DATE else "VARCHAR",
            row_count=100,
            non_null_count=100,
            null_pct=0.0,
            distinct_count=80,
            uniqueness_ratio=0.8,
            inferred_semantic_type=semantic,
        )
        table = TableProfile(schema_name="heldout", table_name="billing_document", row_count=100, columns=[col])
        proposal = MappingProposal(
            mapping_key=f"heldout.billing_document.{column}",
            source_table=table.qualified,
            source_column=column,
            source_field=f"{table.qualified}.{column}",
            canonical_entity="invoice",
            canonical_field=first,
            confidence=confidence,
            score=0.6,
            rationale="held-out candidate ambiguity",
            requires_review=True,
            reason_codes=["LOW_CONFIDENCE"],
            alternatives=[ScoredTarget(entity="invoice", field=alternative, score=0.58)],
            evidence_ids=["6f1c2a9e-3b7d-4c55-9a51-0d2f7e1b8c44"],
        )
        result = _apply_judge(judge, proposal, col, table, ontology)
        base_hits.append(first == expected)
        judge_hits.append(result.canonical_field == expected)
        # Fixed baseline-confidence cohorts avoid hiding regression by moving examples between buckets.
        base_buckets.setdefault(confidence.value, []).append(base_hits[-1])
        judge_buckets.setdefault(confidence.value, []).append(judge_hits[-1])
        verdicts.append(result.judge or {})
    base = {
        "accuracy": sum(base_hits) / len(cases),
        "calibration": {k: sum(v) / len(v) for k, v in base_buckets.items()},
    }
    judged = {
        "accuracy": sum(judge_hits) / len(cases),
        "calibration": {k: sum(v) / len(v) for k, v in judge_buckets.items()},
        "consulted": len(verdicts),
        "applied": sum(bool(v.get("applied")) for v in verdicts),
        "abstained": sum(v.get("choice") == "ABSTAIN" for v in verdicts),
        "cost_usd": total_cost(verdicts),
    }
    return base, judged


def enablement_decision(comparisons: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> tuple[bool, list[str]]:
    reasons = []
    if not comparisons or not any(name == "heldout_challenges" for name, _, _ in comparisons):
        reasons.append("held-out challenge evidence is required")
    improved = False
    for name, base, judged in comparisons:
        if judged["accuracy"] < base["accuracy"]:
            reasons.append(f"{name}: accuracy regressed")
        improved |= judged["accuracy"] - base["accuracy"] >= 0.01
        for bucket in base["calibration"].keys() | judged["calibration"].keys():
            if bucket not in judged["calibration"] or judged["calibration"][bucket] < base["calibration"].get(
                bucket, 0
            ):
                reasons.append(f"{name}: {bucket} calibration regressed or lacks comparable evidence")
    if not improved:
        reasons.append("no accuracy improvement of at least one percentage point")
    return not reasons, reasons


async def main_async(mode: str) -> str:
    root = get_settings().var_root / "judge_eval"
    shutil.rmtree(root, ignore_errors=True)
    rows = []
    comparisons = []
    for fixture in ("portco_a", "portco_b"):
        base = await score(fixture, False, mode, root)
        judged = await score(fixture, True, mode, root)
        comparisons.append((fixture, base, judged))
    comparisons.append(("heldout_challenges", *challenge_scores(mode)))
    for fixture, base, judged in comparisons:
        cost_text = "unknown" if judged["cost_usd"] is None else f"${judged['cost_usd']:.4f}"
        rows.append(
            f"| {fixture} | {base['accuracy']:.3f} | {judged['accuracy']:.3f} | {judged['consulted']} | "
            f"{judged['applied']} | {judged['abstained']} | {base['calibration']} | {judged['calibration']} | "
            f"{cost_text} |"
        )
    eligible, reasons = enablement_decision(comparisons)
    decision = "ELIGIBLE for reviewed enablement" if eligible else f"KEEP OPT-IN ({'; '.join(reasons)})"
    live_note = (
        ""
        if mode != "replay"
        else "\n> Run in **replay** mode: without recorded cassettes the judge abstains everywhere, so this "
        "report shows the no-regression path only. Record a live comparison with "
        "`PORTCO_ANTHROPIC_API_KEY=... python -m evals.judge_eval --mode record`.\n"
    )
    return "\n".join(
        [
            "# Judge vs deterministic baseline",
            "",
            f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} in `{mode}` mode.",
            live_note,
            "| fixture | baseline top-1 | judge top-1 | consulted | applied | abstained | baseline calibration | "
            "judge calibration | judge cost |",
            "|---|---|---|---|---|---|---|---|---|",
            *rows,
            "",
            "Fixture accuracy/calibration covers labeled columns only; it is not whole-output precision. "
            + "; ".join(
                f"{name}: {base.get('truth_coverage')}" for name, base, _ in comparisons if "truth_coverage" in base
            ),
            "Held-out rows test reranking using fixed baseline-confidence cohorts; "
            "fixtures report output-confidence buckets. "
            "The rule permits equality on saturated fixtures, requires >= 1 percentage point improvement elsewhere, "
            "and rejects regression in any populated confidence bucket. Default configuration remains disabled.",
            "",
            f"**Decision:** {decision}. The judge may only reorder deterministic candidates or abstain; "
            "it never clears review and never raises confidence above MEDIUM, so it cannot bypass a human gate.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["replay", "record", "live"], default="replay")
    args = parser.parse_args()
    text = anyio.run(main_async, args.mode)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
