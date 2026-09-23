"""The golden scoring functions themselves, on hand-built inputs."""

from __future__ import annotations

import pytest

from tests.golden.scoring import mapping_top1, precision_recall, primary_key_scores, unexpected_proposals

pytestmark = pytest.mark.unit


def test_precision_recall() -> None:
    s = precision_recall({"a", "b", "x"}, {"a", "b", "c", "d"})
    assert (s.precision, s.recall, s.true_positives) == (2 / 3, 0.5, 2)
    assert precision_recall(set(), {"a"}).precision == 1.0 and precision_recall(set(), set()).recall == 1.0


def test_primary_keys_need_every_column_in_order() -> None:
    truth = {"s.t1": ["id"], "s.t2": ["a", "b"]}
    s = primary_key_scores({"s.t1": ["id"], "s.t2": ["b", "a"], "s.other": ["x"]}, truth)
    assert (s.recall, s.precision) == (0.5, 0.5)  # s.other is not in the truth and is ignored


def test_mapping_top1_counts_unmapped_columns_and_misses() -> None:
    truth = {"t.a": "e.f", "t.b": None, "t.c": "e.g", "t.d": None}
    proposed = {"t.a": "e.f", "t.c": "e.h", "t.d": "e.x"}
    assert mapping_top1(proposed, truth) == 0.5  # a right, b correctly unmapped; c wrong, d spurious
    assert unexpected_proposals(proposed, truth) == ["t.d"]
    assert mapping_top1({}, {}) == 1.0
