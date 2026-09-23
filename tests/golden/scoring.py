"""Scoring against fixture ground truth, kept apart from the golden tests so that the metrics are
defined once, can be unit-tested on tiny inputs, and read like the thresholds in thresholds.yaml."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PrecisionRecall:
    precision: float
    recall: float
    true_positives: int


def precision_recall(found: set[str], expected: set[str]) -> PrecisionRecall:
    """Set-based precision/recall. Precision is 1.0 when nothing was found (nothing wrong was claimed)."""
    tp = len(found & expected)
    return PrecisionRecall(
        precision=tp / len(found) if found else 1.0,
        recall=tp / len(expected) if expected else 1.0,
        true_positives=tp,
    )


def primary_key_scores(found: Mapping[str, list[str]], truth: Mapping[str, list[str]]) -> PrecisionRecall:
    """A key counts only if every column matches, in order. Tables absent from the truth are ignored."""
    hits = sum(1 for table, pk in truth.items() if found.get(table) == pk)
    claimed = sum(1 for table in found if table in truth)
    return PrecisionRecall(
        precision=hits / claimed if claimed else 1.0, recall=hits / len(truth) if truth else 1.0, true_positives=hits
    )


def mapping_top1(proposed: Mapping[str, str], truth: Mapping[str, str | None]) -> float:
    """Share of ground-truth columns mapped correctly. A column whose truth is None is correct only
    when nothing was proposed for it (a proposal routed to review still counts as a miss)."""
    if not truth:
        return 1.0
    correct = sum(
        1
        for col, expected in truth.items()
        if (expected is None and col not in proposed) or (col in proposed and proposed[col] == expected)
    )
    return correct / len(truth)


def unexpected_proposals(proposed: Mapping[str, Any], truth: Mapping[str, str | None]) -> list[str]:
    """Columns that should stay unmapped but received a proposal."""
    return sorted(col for col, expected in truth.items() if expected is None and col in proposed)
