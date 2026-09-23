"""Generate docs/data_contracts.md from the contract models (POD-904). Run: `uv run poe docs`."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.export_schemas import MODELS, schema_for

OUT = Path(__file__).resolve().parents[1] / "docs" / "data_contracts.md"


def _type(prop: dict[str, Any]) -> str:
    if "$ref" in prop:
        return prop["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in prop:
        return " \\| ".join(_type(p) for p in prop["anyOf"])
    if prop.get("type") == "array":
        return f"list[{_type(prop.get('items', {}))}]"
    if "enum" in prop:
        return " \\| ".join(f"`{v}`" for v in prop["enum"])
    if "const" in prop:
        return f"`{prop['const']}`"
    fmt = prop.get("format")
    return f"{prop.get('type', 'any')}{f' ({fmt})' if fmt else ''}"


def render() -> str:
    lines = [
        "# Data contracts",
        "",
        "Generated from the Pydantic models by `scripts/gen_data_contracts.py`; do not edit by hand.",
        "JSON Schemas live in `contracts/` and a test fails if they drift from the models.",
        "",
        "Every persisted contract carries `schema_version`. No contract has a field that can carry row values.",
        "",
    ]
    for name, model in MODELS.items():
        schema = schema_for(model)
        lines += [f"## `{model.__name__}` ({name})", ""]
        if model.__doc__:
            lines += [model.__doc__.strip().splitlines()[0], ""]
        lines += ["| field | type | required | description |", "|---|---|---|---|"]
        required = set(schema.get("required", []))
        for field, prop in schema.get("properties", {}).items():
            desc = (prop.get("description") or "").replace("|", "\\|")
            lines.append(f"| `{field}` | {_type(prop)} | {'yes' if field in required else ''} | {desc} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
