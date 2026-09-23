"""Fixture generation and ground truth (POD-104, 105, 106)."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from src.domain.ontology import load_ontology
from src.fixtures.base import content_digest
from src.fixtures.generate import build_fixture, fixture_names, ground_truth_path, load_ground_truth
from src.fixtures.variants import EXPECTED, VARIANTS

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name", ["portco_a", "portco_b"])
def test_generation_is_reproducible_and_matches_committed_truth(name: str) -> None:
    a, b = build_fixture(name), build_fixture(name)
    assert content_digest(a) == content_digest(b)
    committed = yaml.safe_load(ground_truth_path(name).read_text(encoding="utf-8"))
    assert committed["content_digest"] == content_digest(a), "regenerate with `poe fixtures`"


@pytest.mark.parametrize("name", ["portco_a", "portco_b"])
def test_ground_truth_targets_exist_in_ontology(name: str) -> None:
    ont = load_ontology()
    truth = load_ground_truth(name)
    for col, target in truth["mappings"].items():
        if target is not None:
            assert ont.has_field(target), (col, target)
    for table, entity in truth["entities"].items():
        assert entity in ont.entities, table


def test_fixtures_share_no_names() -> None:
    a, b = load_ground_truth("portco_a"), load_ground_truth("portco_b")
    cols_a = {c.split(".", 2)[2].lower() for c in a["mappings"]}
    cols_b = {c.split(".", 2)[2].lower() for c in b["mappings"]}
    assert not {t.split(".")[1].lower() for t in a["entities"]} & {t.split(".")[1].lower() for t in b["entities"]}
    assert len(cols_a & cols_b) <= 1, cols_a & cols_b  # nothing shared beyond incidental names


def test_every_variant_has_expected_outcome() -> None:
    assert set(VARIANTS) == set(EXPECTED)
    for v in VARIANTS:
        assert f"portco_a__{v}" in fixture_names()
        assert ground_truth_path(f"portco_a__{v}").exists()


def test_canaries_are_planted(truth_a: dict[str, Any]) -> None:
    fx = build_fixture("portco_a")
    blob = repr([t.rows for t in fx.tables])
    for canary in truth_a["canaries"]:
        assert canary in blob


def test_not_applicable_metrics_declared_for_b(truth_b: dict[str, Any]) -> None:
    assert {"arr", "mrr", "nrr"} <= set(truth_b["not_applicable_metrics"])
