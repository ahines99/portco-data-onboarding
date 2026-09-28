"""Frozen unfamiliar-schema benchmark; inference never reads evaluator labels.

The worker uses a Python audit hook as a regression guard, not an OS security sandbox.
Cases and labels are public; independence is agent authorship before mapper changes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent / "unfamiliar"
FROZEN_MANIFEST_SHA256 = "2610a148aaa31dd01cb842acdd5233405e4925025f29a98e13fd3b7dfa364fd0"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(root: Path = ROOT) -> dict[str, Any]:
    if digest(root / "manifest.json") != FROZEN_MANIFEST_SHA256:
        raise ValueError("Frozen benchmark manifest changed; create a new benchmark version instead")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        if digest(root / name) != expected:
            raise ValueError(f"Frozen benchmark file changed: {name}")
    return manifest


def install_label_guard() -> None:
    labels = (ROOT / "labels").resolve()

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event != "open" or not args or not isinstance(args[0], (str, bytes, Path)):
            return
        candidate = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).resolve()
        if candidate == labels or labels in candidate.parents:
            raise PermissionError("Evaluator labels are forbidden in inference worker")

    sys.addaudithook(audit)


async def infer(input_path: Path, output: Path) -> None:
    install_label_guard()
    import duckdb

    from src.domain.models import Principal, Role, StepName
    from src.domain.project_models import ConnectionSpec
    from src.settings import Settings
    from src.workflows.facade import OnboardingService

    source = output.parent / "source.duckdb"
    with duckdb.connect(str(source)) as conn:
        conn.execute(input_path.read_text(encoding="utf-8"))
    before = digest(source)
    settings = Settings(var_root=output.parent / "state", env="test", llm_enabled=False, log_level="ERROR")
    service = OnboardingService.build(settings)
    service.connections.register(
        ConnectionSpec(connection_id="benchmark", company_id="benchmark", path=str(source), schemas=["raw"])
    )
    principal = Principal(principal_id="agent:unfamiliar-benchmark", role=Role.AGENT)
    run = await service.start_run(principal, "benchmark", stop_after=StepName.CANONICAL_MAPPING)
    with service.store.tx() as tx:
        observed_steps = [step.step for step in tx.steps.list(run.run_id)]
    result = {
        "status": run.status.value,
        "source_unchanged": before == digest(source),
        "label_guard_installed": True,
        "llm_enabled": False,
        "publication_attempted": "publish" in observed_steps,
        "observed_steps": observed_steps,
        "entities": service.artifact(principal, run.run_id, StepName.ENTITY_INFERENCE).model_dump(mode="json"),
        "joins": service.artifact(principal, run.run_id, StepName.JOIN_INFERENCE).model_dump(mode="json"),
        "mapping": service.artifact(principal, run.run_id, StepName.CANONICAL_MAPPING).model_dump(mode="json"),
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    service.store.engine.dispose()


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def join_key(join: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            [
                f"{join['left_table']}.{','.join(join['left_columns'])}",
                f"{join['right_table']}.{','.join(join['right_columns'])}",
            ]
        )
    )


def score(prediction: dict[str, Any], labels: dict[str, Any]) -> dict[str, Any]:
    proposals = prediction["mapping"]["proposals"]
    targets = labels["mappings"]
    known = sum(value is not None for value in targets.values())
    confidence: dict[str, list[bool]] = defaultdict(list)
    proposed_sources = set()
    correct = 0
    errors = []
    unit_errors = []
    unsafe = []
    unit_correct = unit_attempted = 0
    for proposal in proposals:
        source = f"{proposal['source_table']}.{proposal['source_column']}"
        target = f"{proposal['canonical_entity']}.{proposal['canonical_field']}"
        hit = targets.get(source) == target and source not in proposed_sources
        if source in proposed_sources:
            unsafe.append(f"duplicate_source_proposal:{source}")
        proposed_sources.add(source)
        correct += hit
        confidence[proposal["confidence"]].append(hit)
        reviewed = proposal["requires_review"]
        if not hit:
            errors.append({"source": source, "predicted": target, "expected": targets.get(source)})
        if (not hit or source in labels["must_review"]) and not reviewed:
            unsafe.append(f"unreviewed_mapping:{source}")
        if source in labels["units"]:
            unit_attempted += 1
            unit_hit = hit and proposal.get("suggested_transform") == labels["units"][source]
            unit_correct += unit_hit
            if not unit_hit:
                unit_errors.append(
                    {
                        "source": source,
                        "predicted": proposal.get("suggested_transform"),
                        "expected": labels["units"][source],
                        "mapping_correct": hit,
                    }
                )
            if not unit_hit and not reviewed:
                unsafe.append(f"unreviewed_unit:{source}")
    candidates = {item["table"]: item for item in prediction["entities"]["candidates"]}
    entity_correct = sum(
        table in candidates and candidates[table].get("canonical_entity") == entity
        for table, entity in labels["entities"].items()
    )
    for table, expected in labels["entities"].items():
        actual = candidates.get(table, {})
        if actual.get("canonical_entity") != expected and actual.get("confidence") == "high":
            unsafe.append(f"high_confidence_wrong_entity:{table}")
    expected_joins = {tuple(sorted(pair)) for pair in labels["joins"]}
    joins = prediction["joins"]["joins"]
    correct_joins = len({join_key(join) for join in joins} & expected_joins)
    for join in joins:
        if join_key(join) not in expected_joins and not join["requires_review"]:
            unsafe.append(f"unreviewed_wrong_join:{join_key(join)}")
    integrity = (
        prediction["source_unchanged"]
        and prediction["label_guard_installed"]
        and not prediction["llm_enabled"]
        and not prediction["publication_attempted"]
    )
    ambiguous = {source for source, target in targets.items() if target is None}
    return {
        "entity_correct": entity_correct,
        "entity_total": len(labels["entities"]),
        "entity_accuracy": ratio(entity_correct, len(labels["entities"])),
        "mapping_correct": correct,
        "mapping_proposed": len(proposals),
        "mapping_labelled_positive": known,
        "mapping_precision": ratio(correct, len(proposals)),
        "mapping_recall": ratio(correct, known),
        "mapping_coverage": ratio(len(proposed_sources & targets.keys()), len(targets)),
        "abstained_fields": sorted(targets.keys() - proposed_sources),
        "ambiguous_fields": len(ambiguous),
        "correct_ambiguous_abstentions": len(ambiguous - proposed_sources),
        "review_proposals": sum(p["requires_review"] for p in proposals),
        "review_rate": ratio(sum(p["requires_review"] for p in proposals), len(proposals)),
        "unresolved_field_burden": len(targets.keys() - proposed_sources),
        "join_correct": correct_joins,
        "join_proposed": len(joins),
        "join_expected": len(expected_joins),
        "join_precision": ratio(correct_joins, len(joins)),
        "join_recall": ratio(correct_joins, len(expected_joins)),
        "units_correct": unit_correct,
        "units_attempted": unit_attempted,
        "units_expected": len(labels["units"]),
        "unit_accuracy_when_proposed": ratio(unit_correct, unit_attempted),
        "confidence_reliability": {
            level: {"count": len(hits), "correct": sum(hits), "accuracy": ratio(sum(hits), len(hits))}
            for level, hits in sorted(confidence.items())
        },
        "mapping_errors": errors,
        "unit_errors": unit_errors,
        "join_errors": [list(join_key(join)) for join in joins if join_key(join) not in expected_joins],
        "integrity_passed": integrity,
        "unsafe_decisions": unsafe,
        "safety_passed": integrity and not unsafe,
    }


def run_benchmark(output: Path) -> dict[str, Any]:
    manifest = verify_manifest()
    results = {}
    for case in manifest["cases"]:
        with tempfile.TemporaryDirectory(prefix="portco-unfamiliar-") as work:
            workdir = Path(work)
            input_copy = workdir / "input.sql"
            input_copy.write_bytes((ROOT / "inputs" / f"{case}.sql").read_bytes())
            prediction_path = workdir / "prediction.json"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "evals.unfamiliar_benchmark",
                    "--worker",
                    str(input_copy),
                    "--output",
                    str(prediction_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            # Labels first enter this evaluator after inference has terminated.
            prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
            labels = json.loads((ROOT / "labels" / f"{case}.json").read_text(encoding="utf-8"))
            results[case] = score(prediction, labels)
    report = {
        "benchmark_version": 1,
        "manifest_sha256": FROZEN_MANIFEST_SHA256,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "inference_source_sha256": {
            str(path).replace("\\", "/"): digest(path) for path in sorted(Path("src/services").glob("*.py"))
        },
        "provenance": (
            "Separately agent-authored frozen synthetic cases; not external human or fully blinded evaluation"
        ),
        "confidence_interpretation": "Empirical categorical correctness; heuristic scores are not probabilities",
        "label_separation": (
            "Labels loaded only by evaluator after label-guarded inference subprocess exits; not an OS sandbox"
        ),
        "accuracy_floor": None,
        "cases": results,
        "safety_passed": all(result["safety_passed"] for result in results.values()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("var/unfamiliar-benchmark.json"))
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--enforce-safety", action="store_true")
    args = parser.parse_args()
    if args.worker:
        asyncio.run(infer(args.worker, args.output))
        return
    report = run_benchmark(args.output)
    print(json.dumps({"report": str(args.output), "safety_passed": report["safety_passed"]}))
    if args.enforce_safety and not report["safety_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
