"""Loader and validator for the canonical PE ontology (POD-103)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.project_models import PiiClass

ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "ontology"

FieldType = Literal["string", "integer", "decimal", "date", "timestamp", "boolean"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldDef(_Strict):
    type: FieldType
    required: bool = False
    pii: PiiClass | None = None
    unit: Literal["currency_major", "currency_minor", "count", "ratio"] | None = None
    description: str = ""


class Lookup(_Strict):
    field: str
    from_entity: str
    join_on: str


class EntityDef(_Strict):
    description: str
    kind: Literal["dimension", "fact"]
    mart: str
    id_fields: list[str]
    table_synonyms: list[str] = Field(default_factory=list)
    lookups: list[Lookup] = Field(default_factory=list)
    fields: dict[str, FieldDef]


class Relationship(_Strict):
    from_: str = Field(alias="from")
    to: str
    cardinality: Literal["1:1", "N:1", "1:N", "N:M"]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class SemanticDef(_Strict):
    kind: Literal["simple", "derived", "reference_only"]
    model: str | None = None
    measure: str | None = None
    agg: Literal["sum", "count_distinct", "count", "max", "min", "average"] | None = None
    expr: str | None = None
    time_dimension: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class MetricDef(_Strict):
    description: str
    grain: Literal["month"]
    formula: str
    requires: list[str]
    semantic: SemanticDef
    pitfall: str | None = None


class Ontology(_Strict):
    version: str
    entities: dict[str, EntityDef]
    synonyms: dict[str, list[str]]
    relationships: list[Relationship]
    semantic_traps: list[str]
    metrics: dict[str, MetricDef]

    @model_validator(mode="after")
    def _validate(self) -> Ontology:
        errors: list[str] = []
        field_names = {f for e in self.entities.values() for f in e.fields}

        for name, entity in self.entities.items():
            for fid in entity.id_fields:
                if fid not in entity.fields:
                    errors.append(f"{name}: id field {fid} not defined")
            for lk in entity.lookups:
                target = self.entities.get(lk.from_entity)
                if target is None or lk.field not in target.fields or lk.join_on not in entity.fields:
                    errors.append(f"{name}: invalid lookup {lk}")

        owner: dict[str, str] = {}
        for fname, syns in self.synonyms.items():
            if fname not in field_names:
                errors.append(f"synonyms for unknown field {fname}")
            for syn in syns:
                key = syn.lower()
                if key in owner and owner[key] != fname:
                    errors.append(f"synonym {syn!r} claimed by both {owner[key]} and {fname}")
                owner[key] = fname

        for rel in self.relationships:
            for ref in (rel.from_, rel.to):
                if not self.has_field(ref):
                    errors.append(f"relationship references unknown field {ref}")

        for mname, metric in self.metrics.items():
            for ref in metric.requires:
                if not self.has_field(ref):
                    errors.append(f"metric {mname} requires unknown field {ref}")
            for dep in metric.semantic.depends_on:
                if dep not in self.metrics:
                    errors.append(f"metric {mname} depends on unknown metric {dep}")
            if metric.semantic.kind == "simple" and not (
                metric.semantic.model and metric.semantic.measure and metric.semantic.agg
            ):
                errors.append(f"metric {mname}: simple metric needs model, measure, agg")

        if errors:
            raise ValueError("invalid ontology:\n  " + "\n  ".join(errors))
        return self

    # ------------------------------------------------------------------ lookups

    def has_field(self, ref: str) -> bool:
        entity, _, field = ref.partition(".")
        return entity in self.entities and field in self.entities[entity].fields

    def field(self, entity: str, field: str) -> FieldDef:
        return self.entities[entity].fields[field]

    def synonym_owner(self) -> dict[str, str]:
        return {s.lower(): f for f, syns in self.synonyms.items() for s in syns}

    def metric_bearing_fields(self) -> set[str]:
        """Measure-carrying fields (money) required by at least one metric."""
        out: set[str] = set()
        for metric in self.metrics.values():
            for ref in metric.requires:
                entity, _, field = ref.partition(".")
                if self.field(entity, field).unit == "currency_major":
                    out.add(ref)
        return out

    def metrics_requiring(self, ref: str) -> list[str]:
        return sorted(m for m, d in self.metrics.items() if ref in d.requires)

    def metric_dependents(self, metric: str) -> set[str]:
        """Metrics that transitively depend on `metric` (used for partial certification)."""
        out: set[str] = set()
        frontier = {metric}
        while frontier:
            nxt = {m for m, d in self.metrics.items() if set(d.semantic.depends_on) & frontier and m not in out}
            out |= nxt
            frontier = nxt
        return out

    def as_resource(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def _load_yaml(name: str) -> Any:
    return yaml.safe_load((ONTOLOGY_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_ontology() -> Ontology:
    return Ontology.model_validate(_load_yaml("pe_canonical_v1.yaml"))


@lru_cache(maxsize=1)
def load_abbreviations() -> dict[str, str]:
    raw = _load_yaml("abbreviations.yaml")
    return {str(k).lower(): str(v).lower() for k, v in raw.items()}


@lru_cache(maxsize=1)
def load_scoring() -> dict[str, Any]:
    data: dict[str, Any] = _load_yaml("scoring.yaml")
    return data
