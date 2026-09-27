"""Fixture registry and generator entrypoint (`portco fixtures generate`)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from src.fixtures import portco_a, portco_b
from src.fixtures.base import Fixture, content_digest, write_duckdb
from src.fixtures.variants import VARIANTS, build_variant
from src.paths import IN_CHECKOUT
from src.settings import PROJECT_ROOT, get_settings

GROUND_TRUTH_DIR = PROJECT_ROOT / "fixtures"

BASE: dict[str, Callable[[], Fixture]] = {"portco_a": portco_a.build, "portco_b": portco_b.build}


def fixture_names() -> list[str]:
    return [*BASE, *(f"portco_a__{v}" for v in VARIANTS)]


def build_fixture(name: str) -> Fixture:
    if name in BASE:
        return BASE[name]()
    base, _, variant = name.partition("__")
    if base == "portco_a" and variant in VARIANTS:
        return build_variant(variant)
    raise KeyError(f"unknown fixture {name!r}")


def fixture_path(name: str, root: Path | None = None) -> Path:
    return (root or get_settings().fixtures_dir) / f"{name}.duckdb"


def ground_truth_path(name: str) -> Path:
    base, _, variant = name.partition("__")
    if variant:
        return GROUND_TRUTH_DIR / base / "variants" / f"{variant}.yaml"
    return GROUND_TRUTH_DIR / name / "ground_truth.yaml"


def load_ground_truth(name: str) -> dict[str, Any]:
    base, _, variant = name.partition("__")
    truth: dict[str, Any] = yaml.safe_load((GROUND_TRUTH_DIR / base / "ground_truth.yaml").read_text(encoding="utf-8"))
    if variant:
        overlay = yaml.safe_load(ground_truth_path(name).read_text(encoding="utf-8"))
        truth = {**truth, **overlay}
    return truth


def _truth_document(fixture: Fixture) -> dict[str, Any]:
    gt = dict(fixture.ground_truth)
    gt["content_digest"] = content_digest(fixture)
    return gt


def generate(name: str, root: Path | None = None, *, write_truth: bool | None = None) -> Path:
    fixture = build_fixture(name)
    path = fixture_path(name, root)
    write_duckdb(fixture, path)
    if write_truth if write_truth is not None else IN_CHECKOUT:
        doc = _truth_document(fixture)
        target = ground_truth_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if "__" in name:
            doc = {
                k: doc[k]
                for k in (
                    "fixture",
                    "company_id",
                    "variant_of",
                    "variant",
                    "expected_variant",
                    "expected_metrics",
                    "content_digest",
                )
            }
        target.write_text(yaml.safe_dump(doc, sort_keys=True, width=120), encoding="utf-8", newline="\n")
    return path


def ensure_fixture(name: str, root: Path | None = None) -> Path:
    path = fixture_path(name, root)
    if not path.exists():
        generate(name, root, write_truth=False)
    return path


def generate_all(root: Path | None = None) -> list[Path]:
    return [generate(n, root) for n in fixture_names()]
