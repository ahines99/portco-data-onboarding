"""Execute the generated semantic definitions at their supported monthly grain.

This deliberately reads artifact YAML, not the ontology's formula registry: a defect
in generation must affect the value compared with the independent source reference.
The supported subset is explicit; unsupported definitions fail closed.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import duckdb
import yaml

from src.domain.errors import ValidationFailed

CURRENCY_METRICS = frozenset({"billings", "mrr", "arr"})


def _ident(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValidationFailed("unsupported semantic identifier")
    return '"' + value + '"'


def execute_metrics(
    con: duckdb.DuckDBPyConnection, files: dict[str, str], names: list[str]
) -> dict[str, dict[str, Any]]:
    """Execute simple measures and dependency-ordered derived metric expressions."""
    metrics: dict[str, dict[str, Any]] = {}
    measures: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for path, text in files.items():
        if not path.startswith("models/semantic/") or not path.endswith((".yml", ".yaml")):
            continue
        data = yaml.safe_load(text) or {}
        for metric in data.get("metrics", []):
            if metric["name"] in metrics:
                raise ValidationFailed("duplicate semantic metric")
            metrics[metric["name"]] = metric
        for model in data.get("semantic_models", []):
            for measure in model.get("measures", []):
                if measure["name"] in measures:
                    raise ValidationFailed("duplicate semantic measure")
                measures[measure["name"]] = (model, measure)
    if set(metrics) != set(names):
        raise ValidationFailed("generated metric manifest does not match semantic definitions")
    values: dict[str, dict[str, Any]] = {}
    visiting: set[str] = set()

    def evaluate(name: str) -> dict[str, Any]:
        if name in values:
            return values[name]
        if name in visiting or name not in metrics:
            raise ValidationFailed("missing or cyclic semantic metric dependency")
        visiting.add(name)
        metric = metrics[name]
        params = metric["type_params"]
        if metric["type"] == "simple":
            measure_name = params["measure"]
            if not isinstance(measure_name, str) or measure_name not in measures:
                raise ValidationFailed("missing semantic measure")
            model, measure = measures[measure_name]
            match = re.fullmatch(r"ref\('([A-Za-z_][A-Za-z0-9_]*)'\)", model["model"])
            if match is None:
                raise ValidationFailed("unsupported semantic model reference")
            time = _ident(model["defaults"]["agg_time_dimension"])
            key = f"strftime({time}, '%Y-%m')"
            if name in CURRENCY_METRICS:
                key += " || '|' || currency"
            expression = measure.get("expr", measure_name)
            agg = measure["agg"]
            if agg == "count_distinct":
                aggregation = f"count(DISTINCT ({expression}))"
            elif agg in {"sum", "count", "max", "min", "average"}:
                aggregation = f"{'avg' if agg == 'average' else agg}({expression})"
            else:
                raise ValidationFailed("unsupported semantic aggregation")
            rows = con.execute(f"SELECT {key}, {aggregation} FROM {_ident(match[1])} GROUP BY 1").fetchall()
            result = {str(k): v for k, v in rows}
        elif metric["type"] == "derived":
            dependencies = [entry["name"] for entry in params["metrics"]]
            if not dependencies:
                raise ValidationFailed("derived metric has no dependencies")
            inputs = {dep: evaluate(dep) for dep in dependencies}
            keys = set().union(*(set(v) for v in inputs.values()))
            result = {}
            for key in sorted(keys):
                projection = ", ".join(f"? AS {_ident(dep)}" for dep in dependencies)
                row = con.execute(
                    f"SELECT {params['expr']} FROM (SELECT {projection})",
                    [inputs[dep].get(key, Decimal(0)) for dep in dependencies],
                ).fetchone()
                assert row is not None
                result[key] = row[0]
        else:
            raise ValidationFailed("unsupported semantic metric type")
        visiting.remove(name)
        values[name] = result
        return result

    for name in names:
        evaluate(name)
    return values
