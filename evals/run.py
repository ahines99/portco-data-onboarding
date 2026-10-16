"""Evaluation harness entrypoint (POD-801): `uv run poe eval` or `python -m evals.run [--case G01 ...]`.

Scores the seven handoff dimensions — tool correctness, evidence fidelity, calculation fidelity,
permission fidelity, uncertainty calibration, recovery, cost/latency — over the golden cases in
`evals/cases.yaml`, writes `evals/reports/latest.{json,md}`, and exits non-zero when any gate in
`evals/thresholds.yaml` is not met.

A full run (no `--case`) must evaluate exactly the pinned case identities with a minimum number of
checks in every dimension; a `--case` selection is reported as partial and gates only what it ran.
Every report records its provenance once: source commit and dirty state, input digests, runtime
and invocation, so a copied report can be tied to the evaluated source state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import yaml

from evals.checks import CheckResult, run_check
from evals.drivers import run_case
from src.fixtures.generate import ensure_fixture
from src.settings import Settings, get_settings

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIMENSIONS = ["tool_correctness", "evidence", "calculation", "permission", "uncertainty", "recovery", "cost"]
PROVENANCE_FILES = {
    "cases": "evals/cases.yaml",
    "thresholds": "evals/thresholds.yaml",
    "lockfile": "uv.lock",
    "pyproject": "pyproject.toml",
}
PROVENANCE_PACKAGES = ("portco-data-onboarding", "dbt-core", "dbt-duckdb", "duckdb", "mcp", "pydantic", "sqlalchemy")


async def evaluate(case_ids: list[str] | None, workdir: Path) -> dict[str, Any]:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    duplicates = sorted(i for i, n in Counter(c["id"] for c in cases).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate eval case ids: {', '.join(duplicates)}")
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
    # Unknown (for example misspelled) dimensions stay visible in the report so the gate rejects them.
    dims = {
        d: {"passed": sum(v), "total": len(v), "rate": round(sum(v) / len(v), 4) if v else None}
        for d in DIMENSIONS + sorted(set(by_dim) - set(DIMENSIONS))
        for v in [by_dim.get(d, [])]
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "scope": "partial" if case_ids is not None else "full",
        "total_seconds": round(time.monotonic() - started, 1),
        "cases": per_case,
        "dimensions": dims,
        "cases_passed": sum(c["passed"] for c in per_case),
        "cases_total": len(per_case),
    }


def gate(report: dict[str, Any], thresholds: dict[str, Any], full_run: bool) -> list[str]:
    """Return gate failures; an empty list means the gate passed.

    Every run fails on failed cases, unknown dimensions, misconfigured thresholds and rates below
    their minimum. A full run must additionally cover the pinned case identities exactly once and
    evaluate at least the pinned number of checks in every dimension (audit A16): a dimension
    without checks fails a full run instead of being skipped as "not evaluated".
    """
    failures = []
    dims: dict[str, dict[str, Any]] = report.get("dimensions") or {}
    if not report["cases_total"] or not any(d["total"] for d in dims.values()):
        failures.append("no cases or checks were evaluated")
    if report["cases_passed"] != report["cases_total"]:
        failures.append("one or more cases failed")
    configured: dict[str, float] = thresholds.get("dimensions") or {}
    if unknown := sorted(set(configured) - set(DIMENSIONS)):
        failures.append(f"thresholds name unknown dimension(s): {', '.join(unknown)}")
    if missing := sorted(set(DIMENSIONS) - set(configured)):
        failures.append(f"thresholds omit required dimension(s): {', '.join(missing)}")
    if unknown := sorted(set(dims) - set(DIMENSIONS)):
        failures.append(f"checks reported unknown dimension(s): {', '.join(unknown)}")
    for dim in DIMENSIONS:
        if dim not in configured:
            continue
        rate = (dims.get(dim) or {}).get("rate")
        if rate is None:
            if full_run:
                failures.append(f"dimension {dim}: no checks evaluated in a full run")
        elif rate < configured[dim]:
            failures.append(f"dimension {dim}: {rate:.2%} < {configured[dim]:.0%}")
    if full_run:
        failures += _coverage_failures(report, thresholds)
    if report["total_seconds"] > thresholds["max_total_seconds"]:
        failures.append(f"eval took {report['total_seconds']}s (> {thresholds['max_total_seconds']}s)")
    return failures


def _coverage_failures(report: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    """Full-run population checks: pinned case identities and per-dimension check floors."""
    failures = []
    if report["cases_passed"] < thresholds["min_cases_passing"]:
        failures.append(f"only {report['cases_passed']} cases passed (< {thresholds['min_cases_passing']})")
    required = [str(c) for c in thresholds.get("required_cases") or []]
    if not required:
        failures.append("thresholds must pin required_cases for a full run")
    if duplicated := sorted(i for i, n in Counter(required).items() if n > 1):
        failures.append(f"thresholds pin duplicate case id(s): {', '.join(duplicated)}")
    ids = [str(c["id"]) for c in report.get("cases") or []]
    if duplicated := sorted(i for i, n in Counter(ids).items() if n > 1):
        failures.append(f"case id(s) evaluated more than once: {', '.join(duplicated)}")
    if missing := sorted(set(required) - set(ids)):
        failures.append(f"required case(s) not evaluated: {', '.join(missing)}")
    if unexpected := sorted(set(ids) - set(required)):
        failures.append(f"case(s) not pinned in thresholds required_cases: {', '.join(unexpected)}")
    floors: dict[str, Any] = thresholds.get("min_checks") or {}
    if unknown := sorted(set(floors) - set(DIMENSIONS)):
        failures.append(f"min_checks names unknown dimension(s): {', '.join(unknown)}")
    dims: dict[str, dict[str, Any]] = report.get("dimensions") or {}
    for dim in DIMENSIONS:
        floor = floors.get(dim)
        if not isinstance(floor, int) or isinstance(floor, bool) or floor < 1:
            failures.append(f"min_checks must pin a positive check count for dimension {dim}")
            continue
        total = (dims.get(dim) or {}).get("total", 0)
        if total < floor:
            failures.append(f"dimension {dim}: only {total} checks evaluated (< {floor} required)")
    return failures


def _sha256_lf(paths: list[Path], root: Path = ROOT) -> str:
    """SHA-256 over relative names and LF-normalized bytes, so Windows and Linux checkouts agree."""
    h = hashlib.sha256()
    for path in paths:
        h.update(path.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _package_versions() -> dict[str, str | None]:
    from importlib.metadata import PackageNotFoundError, version

    out: dict[str, str | None] = {}
    for name in PROVENANCE_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def provenance(argv: list[str], case_ids: list[str] | None) -> dict[str, Any]:
    """Identify the evaluated source state once per run (audit T4).

    Records the git commit and whether the working tree differed from it, digests of the corpus,
    thresholds, lockfile, harness and pipeline sources, the runtime, and the invocation. Secrets
    and machine paths are not recorded: environment overrides are listed by name only.
    """
    from src.workflows.versioning import configuration_fingerprint, pipeline_version

    status = _git("status", "--porcelain=v1", "--untracked-files=normal")
    lines = status.splitlines() if status else []
    return {
        "source": {
            "commit": _git("rev-parse", "HEAD"),
            "dirty": None if status is None else bool(lines),
            "modified_tracked_paths": sum(not line.startswith("??") for line in lines),
            "untracked_paths": sum(line.startswith("??") for line in lines),
        },
        "digests": {
            "algorithm": "sha256 over relative path and LF-normalized bytes",
            **{f"{key}_sha256": _sha256_lf([ROOT / rel]) for key, rel in PROVENANCE_FILES.items()},
            "eval_harness_sha256": _sha256_lf(sorted(HERE.glob("*.py"))),
            # The existing step-reuse digest of ontology/, templates/, src/ and uv.lock.
            "pipeline_version": pipeline_version(),
            # Effective baseline settings every case's service starts from (credentials and paths excluded).
            "case_settings_fingerprint": configuration_fingerprint(
                Settings(env="test", step_backoff_base_seconds=0.0, log_level="WARNING")
            ),
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "os": platform.platform(),
            "machine": platform.machine(),
            "packages": _package_versions(),
        },
        "invocation": {
            "command": "python -m evals.run",
            "argv": list(argv),
            "scope": "partial" if case_ids is not None else "full",
            "selected_cases": sorted(case_ids) if case_ids is not None else "all",
            "portco_env_overrides": sorted(k for k in os.environ if k.startswith("PORTCO_")),
            "ci": {k: os.environ[k] for k in ("GITHUB_RUN_ID", "GITHUB_SHA", "GITHUB_WORKFLOW") if k in os.environ},
        },
    }


def to_markdown(report: dict[str, Any], failures: list[str]) -> str:
    partial = report.get("scope") == "partial"
    lines = [
        "# Evaluation report",
        "",
        f"Generated {report['generated_at']} in {report['total_seconds']}s. "
        f"**{report['cases_passed']}/{report['cases_total']} cases passed.** "
        + ("Gate: **PASS**" if not failures else "Gate: **FAIL** — " + "; ".join(failures)),
        "",
    ]
    if partial:
        lines += [
            "**Partial run:** only the selected cases were evaluated. This is not a full-corpus gate result, "
            "and dimensions without checks were not evaluated.",
            "",
        ]
    lines += ["## Dimensions", "", "| dimension | checks passed | rate |", "|---|---|---|"]
    for dim, d in report["dimensions"].items():
        rate = ("not evaluated" if partial else "n/a") if d["rate"] is None else f"{d['rate']:.0%}"
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
    if prov := report.get("provenance"):
        source, digests, runtime, inv = prov["source"], prov["digests"], prov["runtime"], prov["invocation"]
        lines += [
            "",
            "## Provenance",
            "",
            f"- Source commit: `{source['commit']}`; working tree differs from commit: {source['dirty']} "
            f"({source['modified_tracked_paths']} modified tracked, {source['untracked_paths']} untracked paths)",
            f"- Invocation: `{' '.join([inv['command'], *inv['argv']])}`; scope {inv['scope']}; "
            f"cases {inv['selected_cases']}",
            f"- Runtime: {runtime['implementation']} {runtime['python']} on {runtime['os']} ({runtime['machine']})",
            f"- Digests ({digests['algorithm']}):",
        ]
        lines += [f"  - {key}: `{value}`" for key, value in digests.items() if key != "algorithm"]
        lines.append(
            "- Packages: " + ", ".join(f"{name} {ver or 'not installed'}" for name, ver in runtime["packages"].items())
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="run only these case ids (a partial run)")
    parser.add_argument("--keep", action="store_true", help="keep the eval working directory")
    parser.add_argument("--snapshot", action="store_true", help="also write a dated, committable report copy")
    args = parser.parse_args(argv)
    invocation = sys.argv[1:] if argv is None else list(argv)
    # Short segments: each case's dbt sandbox nests deeply, and Windows paths stop at 260 characters.
    workdir = get_settings().var_root / "ev" / datetime.now(UTC).strftime("%m%d%H%M%S")
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        report = anyio.run(evaluate, args.case, workdir)
    except ValueError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        parser.error(str(exc))
    report["provenance"] = provenance(invocation, args.case)
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
    scope = "partial run (selected cases only); " if args.case else ""
    print(
        f"\n{report['cases_passed']}/{report['cases_total']} cases passed in {report['total_seconds']}s; "
        f"{scope}gate {'PASS' if not failures else 'FAIL'}",
        file=sys.stderr,
    )
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
