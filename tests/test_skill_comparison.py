"""The comparison scorer must reject missing or non-comparable live evidence."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.compare_skills import prepare, score


def reviewed_manifest(tmp_path: Path) -> Path:
    prepare(tmp_path)
    manifest = tmp_path / "comparison.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["annotation_provenance"] = {
        "method": "human_reviewed",
        "exhaustive": True,
        "blinded_independent": False,
    }
    data["scoring_scope"] = "Synthetic unit-test annotations, not live evidence."
    for session in data["sessions"]:
        # Synthetic unit-test records, never saved as live comparison evidence.
        (tmp_path / session["transcript"]).write_text("synthetic test claim\n", encoding="utf-8")
        session.update(model="unit-test", settings={}, reviewer="test", reviewed_at="2026-09-27", violations=[])
        if session["condition"] == "with":
            session["skills_loaded"] = ["schema-profiling"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return manifest


def test_unreviewed_template_is_not_live_evidence(tmp_path: Path) -> None:
    prepare(tmp_path)
    with pytest.raises(ValueError, match="model, reviewer"):
        score(tmp_path / "comparison.json")


def test_scoring_counts_only_line_anchored_violations(tmp_path: Path) -> None:
    manifest = reviewed_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["sessions"][0]["violations"] = [
        {"category": "unsupported_claim", "line": 1, "quote": "synthetic test claim", "reason": "test annotation"}
    ]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    report = score(manifest)
    assert report["counts"] == {"without": 1, "with": 0}
    assert report["fewer_violations_with_skills"]
    data["sessions"][0]["violations"][0]["quote"] = "absent quotation"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="quote"):
        score(manifest)


def test_different_models_cannot_be_compared(tmp_path: Path) -> None:
    manifest = reviewed_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["sessions"][0]["model"] = "different-model"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="same model"):
        score(manifest)


def test_missing_pair_fails_instead_of_reporting_a_partial_comparison(tmp_path: Path) -> None:
    manifest = reviewed_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["sessions"].pop()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        score(manifest)


@pytest.mark.parametrize(
    ("provenance", "approval", "message"),
    [
        (None, "", "annotation_provenance"),
        ({"method": "unknown", "exhaustive": False, "blinded_independent": False}, "", "annotation method"),
        (
            {"method": "human_reviewed", "exhaustive": "false", "blinded_independent": False},
            "",
            "explicit booleans",
        ),
        (
            {"method": "owner_approved_assistant", "exhaustive": False, "blinded_independent": False},
            "",
            "approval_basis",
        ),
        (
            {"method": "owner_approved_assistant", "exhaustive": False, "blinded_independent": True},
            "Approved test candidates",
            "not blinded independent",
        ),
    ],
)
def test_annotation_provenance_must_be_explicit_and_consistent(
    tmp_path: Path, provenance: dict[str, object] | None, approval: str, message: str
) -> None:
    manifest = reviewed_manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["annotation_provenance"] = provenance
    data["approval_basis"] = approval
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        score(manifest)


def test_published_owner_approved_report_reproduces_through_cli(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    evidence = root / "docs" / "evidence" / "live-study"
    manifest = json.loads((evidence / "comparison.json").read_text(encoding="utf-8"))
    for name in ["comparison.json", *(session["transcript"] for session in manifest["sessions"])]:
        shutil.copyfile(evidence / name, tmp_path / name)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "compare_skills.py"), "score", str(tmp_path / "comparison.json")],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    report = json.loads((tmp_path / "scored.json").read_text(encoding="utf-8"))
    assert json.loads(result.stdout)["counts"] == {"without": 3, "with": 3}
    assert report == json.loads((evidence / "scored.json").read_text(encoding="utf-8"))
    assert report["status"] == "owner-approved assistant annotations on live transcripts"
    assert report["approval_basis"] == manifest["approval_basis"]
    assert report["scoring_scope"] == manifest["scoring_scope"]
    assert "Non-exhaustive" in report["review_method"]
    assert "Not a blinded independent study" in report["review_method"]
