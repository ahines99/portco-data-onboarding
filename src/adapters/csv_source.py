"""Local operator ingestion of typed CSV extracts into immutable source snapshots.

Not a remote upload API. The operator and the source-store filesystem are trusted,
just as with the existing local DuckDB sources. Source values never enter receipts.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path, PureWindowsPath
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.domain.errors import Conflict, DomainError, NotFound, ValidationFailed
from src.domain.identifiers import assert_safe, assert_safe_company
from src.domain.project_models import ConnectionSpec

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 250_000
MAX_MANIFEST_BYTES = 1024 * 1024
DECIMAL_TYPE = re.compile(r"DECIMAL\(([1-9][0-9]?),([0-9]{1,2})\)")
SCALAR_TYPES = {"VARCHAR", "INTEGER", "BIGINT", "BOOLEAN", "DATE", "TIMESTAMP"}


class CsvTable(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    schema_name: str
    table_name: str
    file: str
    columns: dict[str, str] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_table(self) -> CsvTable:
        assert_safe(self.schema_name, self.table_name, *self.columns)
        if self.schema_name.lower() in {"main", "information_schema", "pg_catalog"}:
            raise ValueError("reserved source schema")
        if len({n.lower() for n in self.columns}) != len(self.columns):
            raise ValueError("duplicate column")
        for dtype in self.columns.values():
            match = DECIMAL_TYPE.fullmatch(dtype)
            if dtype not in SCALAR_TYPES and not (match and 0 <= int(match[2]) <= int(match[1]) <= 38):
                raise ValueError("unsupported column type")
        return self


class CsvManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source_id: str
    company_id: str
    as_of: date
    tables: list[CsvTable] = Field(min_length=1, max_length=32)
    category_domains: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_manifest(self) -> CsvManifest:
        assert_safe_company(self.source_id)
        assert_safe_company(self.company_id)
        names = {(t.schema_name.lower(), t.table_name.lower()) for t in self.tables}
        if len(names) != len(self.tables):
            raise ValueError("duplicate table")
        columns = {f"{t.schema_name}.{t.table_name}.{c}" for t in self.tables for c in t.columns}
        if not set(self.category_domains).issubset(columns):
            raise ValueError("unknown category column")
        return self


def _no_links(path: Path) -> Path:
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink() or component.is_junction():
            raise ValidationFailed("symbolic links and junctions are not permitted for source ingestion")
    return absolute.resolve()


def _read(path: Path, limit: int) -> bytes:
    path = _no_links(path)
    if not path.is_file():
        raise ValidationFailed("source input must be a regular file")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("source input exceeds its byte limit")
    return data


def _input_path(root: Path, name: str) -> Path:
    # Reject Windows drive/UNC syntax even when running on Linux.
    relative = Path(name)
    if (
        relative.is_absolute()
        or PureWindowsPath(name).drive
        or "\\" in name
        or any(p in {".", ".."} for p in name.split("/"))
        or relative.suffix.lower() != ".csv"
    ):
        raise ValidationFailed("CSV paths must be relative files beneath the extract directory")
    path = _no_links(root / relative)
    if not path.is_relative_to(root):
        raise ValidationFailed("CSV path escapes the extract directory")
    return path


def _cell(value: str, dtype: str) -> Any:
    if value == r"\N":
        return None
    if dtype == "VARCHAR":
        return value
    if dtype in {"INTEGER", "BIGINT"}:
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            raise ValueError("invalid integer")
        return int(value)
    if dtype == "BOOLEAN":
        if value.lower() not in {"true", "false"}:
            raise ValueError("invalid boolean")
        return value.lower() == "true"
    if dtype == "DATE":
        return date.fromisoformat(value)
    if dtype == "TIMESTAMP":
        result = datetime.fromisoformat(value)
        if result.tzinfo is not None:
            raise ValueError("timezone requires explicit operator normalization")
        return result
    match = DECIMAL_TYPE.fullmatch(dtype)
    assert match is not None
    precision, scale = int(match[1]), int(match[2])
    with localcontext() as ctx:
        ctx.prec = 80
        number = Decimal(value)
        if (
            not number.is_finite()
            or abs(number) >= Decimal(10) ** (precision - scale)
            or number != number.quantize(Decimal(10) ** -scale)
        ):
            raise ValueError("decimal would round or overflow")
    return number


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def import_csv(
    manifest_path: Path,
    extract_root: Path,
    sources_root: Path,
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, materialize, and atomically register one snapshot; never overwrite."""
    staging: Path | None = None
    try:
        manifest = CsvManifest.model_validate_json(_read(manifest_path, MAX_MANIFEST_BYTES))
        root = _no_links(extract_root)
        store = _no_links(sources_root)
        store.mkdir(parents=True, exist_ok=True)
        destination = store / manifest.source_id
        if destination.exists():
            raise Conflict("source id already exists; use a new id for a new snapshot")
        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=store))
        db = staging / "source.duckdb"
        inputs: list[dict[str, Any]] = []
        total_bytes = total_rows = 0
        with duckdb.connect(str(db), config={"enable_external_access": "false", "threads": "1"}) as con:
            con.execute("BEGIN TRANSACTION")
            for table in manifest.tables:
                data = _read(_input_path(root, table.file), MAX_BYTES - total_bytes)
                total_bytes += len(data)
                reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
                if next(reader, None) != list(table.columns):
                    raise ValidationFailed("CSV header must exactly match the declared column order")
                qualified = f'"{table.schema_name}"."{table.table_name}"'
                con.execute(f'CREATE SCHEMA IF NOT EXISTS "{table.schema_name}"')
                declarations = ", ".join(f'"{name}" {dtype}' for name, dtype in table.columns.items())
                con.execute(f"CREATE TABLE {qualified} ({declarations})")
                sql = f"INSERT INTO {qualified} VALUES ({','.join('?' for _ in table.columns)})"
                batch: list[list[Any]] = []
                rows = 0
                for row in reader:
                    if len(row) != len(table.columns):
                        raise ValidationFailed("CSV row width does not match the declared columns")
                    rows += 1
                    total_rows += 1
                    if total_rows > MAX_ROWS:
                        raise ValidationFailed("source input exceeds its row limit")
                    batch.append(
                        [_cell(value, dtype) for value, dtype in zip(row, table.columns.values(), strict=True)]
                    )
                    if len(batch) == 1000:
                        con.executemany(sql, batch)
                        batch.clear()
                if batch:
                    con.executemany(sql, batch)
                inputs.append(
                    {
                        "table": f"{table.schema_name}.{table.table_name}",
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "rows": rows,
                    }
                )
            con.execute("COMMIT")
            con.execute("CHECKPOINT")
        receipt = {
            "format_version": 1,
            "connection_id": f"csv:{manifest.source_id}",
            "company_id": manifest.company_id,
            "as_of": manifest.as_of.isoformat(),
            "schemas": sorted({t.schema_name for t in manifest.tables}),
            "category_domains": manifest.category_domains,
            "snapshot_sha256": _sha(db),
            "manifest_sha256": hashlib.sha256(manifest.model_dump_json().encode()).hexdigest(),
            "inputs": inputs,
        }
        if provenance is not None:
            receipt["provenance"] = provenance
        (staging / "registration.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        # Both files become visible together; a nonempty existing directory cannot be replaced.
        try:
            os.rename(staging, destination)
        except OSError:
            if destination.exists():
                raise Conflict("source id already exists; use a new id for a new snapshot") from None
            raise
        staging = None
        return receipt
    except DomainError:
        raise
    except (OSError, ValueError, ArithmeticError, csv.Error, duckdb.Error, ValidationError):
        raise ValidationFailed("CSV import failed; check manifest, encoding and declared column types") from None
    finally:
        if staging is not None:
            shutil.rmtree(staging)


def resolve_csv(connection_id: str, sources_root: Path) -> ConnectionSpec:
    """Resolve only server-owned registration; verify snapshot integrity on every use."""
    name = connection_id.removeprefix("csv:")
    assert_safe_company(name)
    directory = _no_links(sources_root / name)
    if not directory.is_dir():
        raise NotFound("CSV source is not registered")
    try:
        receipt = json.loads(_read(directory / "registration.json", MAX_MANIFEST_BYTES))
        db = _no_links(directory / "source.duckdb")
        if receipt["format_version"] != 1 or receipt["connection_id"] != connection_id:
            raise ValueError("invalid registration")
        if _sha(db) != receipt["snapshot_sha256"]:
            raise ValidationFailed("registered CSV snapshot integrity check failed")
        spec = ConnectionSpec(
            connection_id=connection_id,
            company_id=receipt["company_id"],
            path=str(db),
            schemas=receipt["schemas"],
            category_domains=receipt["category_domains"],
            as_of=receipt["as_of"],
        )
        assert_safe_company(spec.company_id)
        return spec
    except DomainError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise ValidationFailed("CSV registration is invalid or unavailable") from None
