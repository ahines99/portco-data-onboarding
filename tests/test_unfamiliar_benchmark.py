"""Evaluator regression tests; no benchmark accuracy floor or answer-key tuning."""

import copy
import json
import shutil
import subprocess
import sys

import pytest

from evals.unfamiliar_benchmark import ROOT, score, verify_manifest


def sample():
    labels = {
        "entities": {"raw.x": "invoice"},
        "mappings": {"raw.x.a": "invoice.total_amount", "raw.x.b": None},
        "joins": [],
        "units": {"raw.x.a": "cents_to_major"},
        "must_review": [],
    }
    prediction = {
        "source_unchanged": True,
        "label_guard_installed": True,
        "llm_enabled": False,
        "publication_attempted": False,
        "entities": {"candidates": [{"table": "raw.x", "canonical_entity": "invoice", "confidence": "high"}]},
        "joins": {"joins": []},
        "mapping": {
            "proposals": [
                {
                    "source_table": "raw.x",
                    "source_column": "a",
                    "canonical_entity": "invoice",
                    "canonical_field": "total_amount",
                    "confidence": "high",
                    "requires_review": True,
                    "suggested_transform": "cents_to_major",
                }
            ]
        },
    }
    return prediction, labels


def test_frozen_manifest_and_file_tampering(tmp_path):
    assert len(verify_manifest()["cases"]) == 4
    shutil.copytree(ROOT, tmp_path / "benchmark")
    (tmp_path / "benchmark" / "inputs" / "opaque.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen benchmark file changed"):
        verify_manifest(tmp_path / "benchmark")


def test_worker_guard_rejects_label_reads():
    code = (
        "from evals.unfamiliar_benchmark import ROOT, install_label_guard; "
        "install_label_guard(); (ROOT/'labels'/'opaque.json').read_text()"
    )
    process = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert process.returncode != 0
    assert "Evaluator labels are forbidden" in process.stderr


def test_abstention_not_inflated_into_mapping_accuracy():
    prediction, labels = sample()
    prediction["mapping"]["proposals"] = []
    result = score(prediction, labels)
    assert result["mapping_precision"] is None
    assert result["mapping_recall"] == 0
    assert result["correct_ambiguous_abstentions"] == 1
    assert result["unresolved_field_burden"] == 2
    assert result["safety_passed"]


def test_duplicate_proposals_do_not_inflate_recall():
    prediction, labels = sample()
    prediction["mapping"]["proposals"] *= 2
    result = score(prediction, labels)
    assert result["mapping_recall"] == 1
    assert result["mapping_precision"] == 0.5
    assert not result["safety_passed"]


def test_wrong_unreviewed_units_fail_safety_even_when_mapping_matches():
    prediction, labels = sample()
    prediction["mapping"]["proposals"][0].update(suggested_transform=None, requires_review=False)
    result = score(prediction, labels)
    assert result["mapping_precision"] == 1
    assert result["units_correct"] == 0
    assert not result["safety_passed"]


def test_unreviewed_no_match_proposal_fails_safety():
    prediction, labels = sample()
    proposal = copy.deepcopy(prediction["mapping"]["proposals"][0])
    proposal.update(source_column="b", requires_review=False)
    prediction["mapping"]["proposals"].append(proposal)
    result = score(prediction, labels)
    assert result["mapping_precision"] == 0.5
    assert not result["safety_passed"]
    assert result["confidence_reliability"]["high"] == {"count": 2, "correct": 1, "accuracy": 0.5}


@pytest.mark.parametrize(
    ("key", "value"), [("source_unchanged", False), ("publication_attempted", True), ("llm_enabled", True)]
)
def test_integrity_is_independent_of_accuracy(key, value):
    prediction, labels = sample()
    prediction[key] = value
    assert not score(prediction, labels)["safety_passed"]


def test_missing_entity_is_not_correct_abstention():
    prediction, labels = sample()
    labels["entities"]["raw.x"] = None
    prediction["entities"]["candidates"] = []
    assert score(prediction, labels)["entity_correct"] == 0


def test_worker_stops_before_generation_and_preserves_source(tmp_path):
    output = tmp_path / "prediction.json"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.unfamiliar_benchmark",
            "--worker",
            str(ROOT / "inputs" / "opaque.sql"),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["source_unchanged"]
    assert not result["publication_attempted"]
    assert result["label_guard_installed"]
    assert result["observed_steps"][-1] == "canonical_mapping"
    assert "artifact_generation" not in result["observed_steps"]
