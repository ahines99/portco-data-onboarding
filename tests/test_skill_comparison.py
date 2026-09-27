"""The comparison scorer must reject missing or non-comparable live evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.compare_skills import prepare, score


def reviewed_manifest(tmp_path: Path) -> Path:
    prepare(tmp_path)
    manifest = tmp_path / "comparison.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
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
