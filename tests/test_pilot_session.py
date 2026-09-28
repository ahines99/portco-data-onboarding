"""Synthetic timing records test measurement integrity, never human participation."""

import csv
import json

import pytest

from scripts.pilot_session import FIELDS, prepare, summarize


def write_intervals(path, rows):
    with (path / "intervals.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        writer.writerows(rows)


def row(start="2026-09-28T10:00:00Z", end="2026-09-28T10:01:00Z", **changes):
    values = dict(zip(FIELDS, ["a1", "t1", "assisted", "op1", "operator", "task", "mapping", start, end], strict=True))
    values.update(changes)
    return [values[field] for field in FIELDS]


def test_preparation_keeps_consent_and_outcomes_unknown(tmp_path):
    target = tmp_path / "private"
    prepare(target, "synthetic-test")
    record = json.loads((target / "pilot.json").read_text())
    assert record["status"] == "not_started"
    assert record["authorization"]["private_consent_reference"] is None
    assert record["attempts"] == []
    assert record["observed_summary"]["percentage_reduction"] is None
    assert summarize(target)["attempts"] == {}
    with pytest.raises(ValueError, match="already exists"):
        prepare(target, "synthetic-test")


def test_separates_setup_reviewer_machine_and_missing_time(tmp_path):
    write_intervals(
        tmp_path,
        [
            row(),
            row("2026-09-28T09:50:00Z", "2026-09-28T09:52:00Z", phase="setup"),
            row(actor="rev1", role="reviewer", activity="review"),
            row(actor="cpu1", role="machine", activity="compute"),
        ],
    )
    report = summarize(tmp_path)
    times = report["attempts"]["a1"]["seconds"]
    assert times["task"] == {"operator": 60, "reviewer": 60, "machine": 60, "developer": None}
    assert times["setup"]["operator"] == 120
    assert times["training"]["operator"] is None
    assert report["task_completion"] is None
    assert not report["public_release_authorized"]


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        ([row(), row(arm="manual", attempt_id="a2")], "overlapping"),
        ([row(), row(actor="rev1", role="reviewer", task_id="t2")], "exactly one task"),
        ([row(), row("2026-09-28T10:02:00Z", "2026-09-28T10:03:00Z", role="reviewer")], "change roles"),
        ([row(end="2026-09-28T09:00:00Z")], "before"),
        ([row(start="2026-09-28T10:00:00")], "timezone"),
        ([row(end="")], "incomplete"),
        ([row(arm="unknown")], "invalid arm"),
    ],
)
def test_invalid_measurements_cannot_be_summarized(tmp_path, rows, match):
    write_intervals(tmp_path, rows)
    with pytest.raises(ValueError, match=match):
        summarize(tmp_path)


def test_normalizes_offsets_and_allows_adjacent_intervals(tmp_path):
    write_intervals(
        tmp_path,
        [row("2026-09-28T06:00:00-04:00", "2026-09-28T10:01:00Z"), row("2026-09-28T10:01:00Z", "2026-09-28T10:02:00Z")],
    )
    assert summarize(tmp_path)["attempts"]["a1"]["seconds"]["task"]["operator"] == 120
