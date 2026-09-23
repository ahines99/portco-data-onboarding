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

from evals.checks import mapping_scores
from evals.drivers import ADMIN, CaseRun, build_service, drive
from src.domain.models import StepName
from src.settings import PROJECT_ROOT, get_settings

OUT = PROJECT_ROOT / "evals" / "reports" / "judge_comparison.md"


async def score(fixture: str, llm: bool, mode: str, root: Any) -> dict[str, Any]:
    svc = build_service(root / f"{fixture}_{'judge' if llm else 'base'}", llm_enabled=llm, llm_mode=mode)
    run = await drive(svc, fixture, "gate_a")
    acc, buckets = mapping_scores(CaseRun(svc, run, 0.0))
    ms = svc.artifact(ADMIN, run.run_id, StepName.CANONICAL_MAPPING)
    judged = [p for p in ms.proposals if p.judge]
    applied = [p for p in judged if p.judge and p.judge.get("applied")]
    cost = sum(float((p.judge or {}).get("usage", {}).get("cost_usd", 0.0)) for p in judged)
    return {
        "accuracy": round(acc, 4),
        "calibration": {k: round(sum(v) / len(v), 3) for k, v in buckets.items() if v},
        "consulted": len(judged),
        "applied": len(applied),
        "abstained": sum(1 for p in judged if (p.judge or {}).get("choice") == "ABSTAIN"),
        "cost_usd": round(cost, 4),
    }


async def main_async(mode: str) -> str:
    root = get_settings().var_root / "judge_eval"
    shutil.rmtree(root, ignore_errors=True)
    rows = []
    verdicts = []
    for fixture in ("portco_a", "portco_b"):
        base = await score(fixture, False, mode, root)
        judged = await score(fixture, True, mode, root)
        better = judged["accuracy"] > base["accuracy"]
        no_regression = judged["calibration"].get("high", 1.0) >= base["calibration"].get("high", 1.0)
        verdicts.append(better and no_regression)
        rows.append(
            f"| {fixture} | {base['accuracy']:.3f} | {judged['accuracy']:.3f} | {judged['consulted']} | "
            f"{judged['applied']} | {judged['abstained']} | {base['calibration']} | {judged['calibration']} | "
            f"${judged['cost_usd']:.4f} |"
        )
    decision = (
        "ENABLE by default"
        if all(verdicts)
        else "KEEP OPT-IN (no measured improvement over the deterministic baseline)"
    )
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
