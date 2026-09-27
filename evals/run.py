"""Evaluation harness entrypoint (POD-801): `uv run poe eval` or `python -m evals.run [--case G01 ...]`.

Scores the seven handoff dimensions — tool correctness, evidence fidelity, calculation fidelity,
permission fidelity, uncertainty calibration, recovery, cost/latency — over the golden cases in
`evals/cases.yaml`, writes `evals/reports/latest.{json,md}`, and exits non-zero when any gate in
`evals/thresholds.yaml` is not met.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import yaml

from evals.checks import CheckResult, run_check
from evals.drivers import run_case
from src.fixtures.generate import ensure_fixture
from src.settings import get_settings

HERE = Path(__file__).resolve().parent
DIMENSIONS = ["tool_correctness", "evidence", "calculation", "permission", "uncertainty", "recovery", "cost"]


async def evaluate(case_ids: list[str] | None, workdir: Path) -> dict[str, Any]:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    if case_ids is not None:
        unknown = set(case_ids) - {c["id"] for c in cases}
        if unknown:
            raise ValueError(f"unknown eval case ids: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in case_ids]
    if not cases:
        raise ValueError("eval case selection must not be empty")
    if any(not c.get("checks") for c in cases):
        raise ValueError("every eval case must contain at least one check")
    fixtures_dir = get_settings().fixtures_dir
    for name in sorted({c["fixture"] for c in cases}):
        ensure_fixture(name, fixtures_dir)
    cache: dict[str, Any] = {}
    results: list[CheckResult] = []
    per_case: list[dict[str, Any]] = []
    started = time.monotonic()
    for case in cases:
        t0 = time.monotonic()
        try:
            cr = await run_case(case, workdir, cache)
            case_results = [await run_check(case["id"], cr, spec) for spec in case["checks"]]
        except Exception as exc:  # a crashed driver fails every check of the case, visibly
            case_results = [
                CheckResult(case["id"], spec["check"], "recovery", False, f"driver error: {exc!r}")
                for spec in case["checks"]
            ]
        results += case_results
        passed = all(r.passed for r in case_results)
        per_case.append(
            {
                "id": case["id"],
                "title": case["title"],
                "passed": passed,
                "seconds": round(time.monotonic() - t0, 2),
                "evidences": case.get("evidences", []),
                "checks": [asdict(r) for r in case_results],
            }
        )
        mark = "PASS" if passed else "FAIL"
        print(f"{mark} {case['id']:4} {case['title']}  ({per_case[-1]['seconds']}s)", file=sys.stderr)
        for r in case_results:
            if not r.passed:
                print(f"       x {r.check}: {r.detail}", file=sys.stderr)
    by_dim: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_dim[r.dimension].append(r.passed)
    dims = {
        d: {"passed": sum(v), "total": len(v), "rate": round(sum(v) / len(v), 4) if v else None}
        for d in DIMENSIONS
        for v in [by_dim.get(d, [])]
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "total_seconds": round(time.monotonic() - started, 1),
        "cases": per_case,
        "dimensions": dims,
        "cases_passed": sum(c["passed"] for c in per_case),
        "cases_total": len(per_case),
    }


def gate(report: dict[str, Any], thresholds: dict[str, Any], full_run: bool) -> list[str]:
    failures = []
    if not report["cases_total"] or not any(d["total"] for d in report["dimensions"].values()):
        failures.append("no cases or checks were evaluated")
    if report["cases_passed"] != report["cases_total"]:
        failures.append("one or more cases failed")
    if full_run and report["cases_passed"] < thresholds["min_cases_passing"]:
        failures.append(f"only {report['cases_passed']} cases passed (< {thresholds['min_cases_passing']})")
    for dim, minimum in thresholds["dimensions"].items():
        rate = report["dimensions"][dim]["rate"]
        if rate is not None and rate < minimum:
            failures.append(f"dimension {dim}: {rate:.2%} < {minimum:.0%}")
    if report["total_seconds"] > thresholds["max_total_seconds"]:
        failures.append(f"eval took {report['total_seconds']}s (> {thresholds['max_total_seconds']}s)")
    return failures


def to_markdown(report: dict[str, Any], failures: list[str]) -> str:
    lines = [
        "# Evaluation report",
        "",
        f"Generated {report['generated_at']} in {report['total_seconds']}s. "
        f"**{report['cases_passed']}/{report['cases_total']} cases passed.** "
        + ("Gate: **PASS**" if not failures else "Gate: **FAIL** — " + "; ".join(failures)),
        "",
        "## Dimensions",
        "",
        "| dimension | checks passed | rate |",
        "|---|---|---|",
    ]
    for dim, d in report["dimensions"].items():
        rate = "n/a" if d["rate"] is None else f"{d['rate']:.0%}"
        lines.append(f"| {dim} | {d['passed']}/{d['total']} | {rate} |")
    lines += ["", "## Cases", "", "| id | case | result | seconds | evidence for |", "|---|---|---|---|---|"]
    for c in report["cases"]:
        lines.append(
            f"| {c['id']} | {c['title']} | {'pass' if c['passed'] else '**FAIL**'} | {c['seconds']} | "
            f"{'; '.join(c['evidences'])} |"
        )
    lines += ["", "## Check details", ""]
    for c in report["cases"]:
        for chk in c["checks"]:
            lines.append(
                f"- `{c['id']}` {chk['check']} ({chk['dimension']}): "
                f"{'pass' if chk['passed'] else 'FAIL'} — {chk['detail']}"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="run only these case ids")
    parser.add_argument("--keep", action="store_true", help="keep the eval working directory")
    parser.add_argument("--snapshot", action="store_true", help="also write a dated, committable report copy")
    args = parser.parse_args(argv)
    # Short segments: each case's dbt sandbox nests deeply, and Windows paths stop at 260 characters.
    workdir = get_settings().var_root / "ev" / datetime.now(UTC).strftime("%m%d%H%M%S")
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        report = anyio.run(evaluate, args.case, workdir)
    except ValueError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        parser.error(str(exc))
    thresholds = yaml.safe_load((HERE / "thresholds.yaml").read_text(encoding="utf-8"))
    failures = gate(report, thresholds, full_run=not args.case)
    report["gate"] = {"passed": not failures, "failures": failures}
    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    (out / "latest.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    (out / "latest.md").write_text(to_markdown(report, failures), encoding="utf-8", newline="\n")
    if args.snapshot and not args.case:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        (out / f"{day}.md").write_text(to_markdown(report, failures), encoding="utf-8", newline="\n")
    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
    print(
        f"\n{report['cases_passed']}/{report['cases_total']} cases passed in {report['total_seconds']}s; "
        f"gate {'PASS' if not failures else 'FAIL'}",
        file=sys.stderr,
    )
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
