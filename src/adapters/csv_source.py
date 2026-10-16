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
from collections.abc import Iterator
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
# The resolver reads registrations with this bound, so import must never write a larger one.
MAX_REGISTRATION_BYTES = MAX_MANIFEST_BYTES
MAX_CATEGORY_LABELS = 1000
MAX_CATEGORY_LABEL_CHARS = 256
DECIMAL_TYPE = re.compile(r"DECIMAL\(([1-9][0-9]?),([0-9]{1,2})\)")
SCALAR_TYPES = {"VARCHAR", "INTEGER", "BIGINT", "BOOLEAN", "DATE", "TIMESTAMP"}
INTEGER_LIMITS = {"INTEGER": 2**31, "BIGINT": 2**63}
# Snapshot catalog name (source.duckdb) plus DuckDB built-in catalogs/schemas: these make
# two-part names ambiguous, cannot be created, or are hidden from the adapter.
RESERVED_SCHEMAS = frozenset({"main", "information_schema", "pg_catalog", "source", "system", "temp", "memory"})
TIMESTAMP_FRACTION = re.compile(r"[.,]([0-9]+)")
DUCKDB_MIN_LINE_SIZE = 2 * 1024 * 1024
# Canonical staged format: every non-null value quoted, NULL an unquoted empty field.
LOAD_OPTIONS = (
    "header=false, auto_detect=false, delim=',', quote='\"', escape='\"', nullstr='', "
    "allow_quoted_nulls=false, strict_mode=true, new_line='\\n', encoding='utf-8'"
)


class CsvTable(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    schema_name: str
    table_name: str
    file: str
    columns: dict[str, str] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_table(self) -> CsvTable:
        assert_safe(self.schema_name, self.table_name, *self.columns)
        if self.schema_name.lower() in RESERVED_SCHEMAS:
            raise ValidationFailed(
                "schema names main, information_schema, pg_catalog, source, system, temp and memory are reserved"
            )
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
        # DuckDB folds identifier case; PostgreSQL quoted names do not. Never merge them.
        spellings: dict[str, set[str]] = {}
        for t in self.tables:
            spellings.setdefault(t.schema_name.lower(), set()).add(t.schema_name)
        if any(len(names) > 1 for names in spellings.values()):
            raise ValidationFailed("schema names differing only by letter case are unsupported; use one spelling")
        names = {(t.schema_name.lower(), t.table_name.lower()) for t in self.tables}
        if len(names) != len(self.tables):
            raise ValidationFailed("table names must be unique within a schema, ignoring letter case")
        columns = {f"{t.schema_name}.{t.table_name}.{c}" for t in self.tables for c in t.columns}
        if not set(self.category_domains).issubset(columns):
            raise ValidationFailed("category domain keys must exactly match a declared schema.table.column")
        # Domains are label sets: drop duplicates, then bound what reaches the registration.
        self.category_domains = {k: list(dict.fromkeys(v)) for k, v in self.category_domains.items()}
        for labels in self.category_domains.values():
            if len(labels) > MAX_CATEGORY_LABELS or any(len(label) > MAX_CATEGORY_LABEL_CHARS for label in labels):
                raise ValidationFailed(
                    f"category domains allow at most {MAX_CATEGORY_LABELS} distinct labels per column "
                    f"of at most {MAX_CATEGORY_LABEL_CHARS} characters"
                )
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
    if dtype in INTEGER_LIMITS:
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            raise ValueError("invalid integer")
        integer = int(value)
        if not -INTEGER_LIMITS[dtype] <= integer < INTEGER_LIMITS[dtype]:
            raise ValueError("integer out of range")
        return integer
    if dtype == "BOOLEAN":
        if value.lower() not in {"true", "false"}:
            raise ValueError("invalid boolean")
        return value.lower() == "true"
    if dtype == "DATE":
        return date.fromisoformat(value)
    if dtype == "TIMESTAMP":
        # fromisoformat silently truncates beyond microseconds; only zero digits may be dropped.
        fraction = TIMESTAMP_FRACTION.search(value)
        if fraction is not None and fraction[1][6:].strip("0"):
            raise ValueError("timestamp precision exceeds microseconds")
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
        if not number.is_finite() or abs(number) >= Decimal(10) ** (precision - scale):
            raise ValueError("decimal would round or overflow")
        exact = number.quantize(Decimal(10) ** -scale)
        if number != exact:
            raise ValueError("decimal would round or overflow")
    return exact


def _canonical(value: Any) -> str | None:
    """Unambiguous text for an already validated value, parsed back exactly by DuckDB."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    raise TypeError("unsupported staged value")


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _receipt(
    manifest: CsvManifest, inputs: list[dict[str, Any]], snapshot_sha256: str, provenance: dict[str, Any] | None
) -> dict[str, Any]:
    receipt = {
        "format_version": 1,
        "connection_id": f"csv:{manifest.source_id}",
        "company_id": manifest.company_id,
        "as_of": manifest.as_of.isoformat(),
        "schemas": sorted({t.schema_name for t in manifest.tables}),
        "category_domains": manifest.category_domains,
        "snapshot_sha256": snapshot_sha256,
        "manifest_sha256": hashlib.sha256(manifest.model_dump_json().encode()).hexdigest(),
        "inputs": inputs,
    }
    if provenance is not None:
        receipt["provenance"] = provenance
    return receipt


def _registration_text(receipt: dict[str, Any]) -> str:
    text = json.dumps(receipt, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_REGISTRATION_BYTES:
        raise ValidationFailed("source registration would exceed its size limit; reduce category domains")
    return text


def check_registration_budget(manifest: CsvManifest, provenance: dict[str, Any] | None) -> None:
    """Reject, before any work, metadata whose largest possible registration is unresolvable."""
    digest = "0" * 64
    inputs = [{"table": f"{t.schema_name}.{t.table_name}", "sha256": digest, "rows": MAX_ROWS} for t in manifest.tables]
    _registration_text(_receipt(manifest, inputs, digest, provenance))


def _stage_rows(reader: Iterator[list[str]], table: CsvTable, path: Path, total_rows: int) -> tuple[int, int, int]:
    """Validate every row in Python and write it in the canonical staged format.

    Returns (rows, running total rows, longest staged line in characters).
    """
    dtypes = list(table.columns.values())
    rows = longest = 0
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, quoting=csv.QUOTE_NOTNULL, lineterminator="\n")
        for row in reader:
            if len(row) != len(dtypes):
                raise ValidationFailed("CSV row width does not match the declared columns")
            rows += 1
            total_rows += 1
            if total_rows > MAX_ROWS:
                raise ValidationFailed("source input exceeds its row limit")
            # The trailing ordinal keeps order explicit and every staged line nonempty.
            staged = [_canonical(_cell(value, dtype)) for value, dtype in zip(row, dtypes, strict=True)]
            longest = max(longest, writer.writerow([*staged, str(rows)]))
    return rows, total_rows, longest


def _load_connection(db: Path, staged: list[Path]) -> duckdb.DuckDBPyConnection:
    """Open the snapshot with file access limited to exactly the private staged files."""
    con = duckdb.connect(
        str(db),
        config={"threads": "1", "autoinstall_known_extensions": "false", "autoload_known_extensions": "false"},
    )
    try:
        # DuckDB only accepts allowed paths before external access is disabled; then lock both.
        con.execute("SET allowed_paths = ?", [[str(p) for p in staged]])
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        if con.execute("SELECT current_setting('enable_external_access')").fetchone() != (False,):
            raise ValidationFailed("could not restrict snapshot file access")
    except BaseException:
        con.close()
        raise
    return con


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
        check_registration_budget(manifest, provenance)
        root = _no_links(extract_root)
        store = _no_links(sources_root)
        store.mkdir(parents=True, exist_ok=True)
        destination = store / manifest.source_id
        if destination.exists():
            raise Conflict("source id already exists; use a new id for a new snapshot")
        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=store))
        db = staging / "source.duckdb"
        load_dir = staging / "load"
        load_dir.mkdir()
        staged = [load_dir / f"table-{n:02d}.csv" for n in range(len(manifest.tables))]
        inputs: list[dict[str, Any]] = []
        total_bytes = total_rows = 0
        with _load_connection(db, staged) as con:
            con.execute("BEGIN TRANSACTION")
            for table, staged_path in zip(manifest.tables, staged, strict=True):
                data = _read(_input_path(root, table.file), MAX_BYTES - total_bytes)
                total_bytes += len(data)
                reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
                if next(reader, None) != list(table.columns):
                    raise ValidationFailed("CSV header must exactly match the declared column order")
                rows, total_rows, longest = _stage_rows(reader, table, staged_path, total_rows)
                qualified = f'"{table.schema_name}"."{table.table_name}"'
                con.execute(f'CREATE SCHEMA IF NOT EXISTS "{table.schema_name}"')
                declarations = ", ".join(f'"{name}" {dtype}' for name, dtype in table.columns.items())
                con.execute(f"CREATE TABLE {qualified} ({declarations})")
                # Declared types only (validated above): positional names avoid identifier quoting.
                types = ", ".join(f"'c{i}': '{dtype}'" for i, dtype in enumerate(table.columns.values()))
                select = ", ".join(f"c{i}" for i in range(len(table.columns)))
                # UTF-8 needs at most four bytes per staged character.
                line_size = max(DUCKDB_MIN_LINE_SIZE, 4 * longest + 16)
                con.execute(
                    f"INSERT INTO {qualified} SELECT {select} FROM read_csv(?, columns={{{types}, 'r': 'BIGINT'}}, "
                    f"{LOAD_OPTIONS}, max_line_size={line_size}) ORDER BY r",
                    [str(staged_path)],
                )
                staged_path.unlink()
                inputs.append(
                    {
                        "table": f"{table.schema_name}.{table.table_name}",
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "rows": rows,
                    }
                )
            con.execute("COMMIT")
            con.execute("CHECKPOINT")
        load_dir.rmdir()
        receipt = _receipt(manifest, inputs, _sha(db), provenance)
        (staging / "registration.json").write_text(_registration_text(receipt), encoding="utf-8")
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
    except (OSError, ValueError, TypeError, ArithmeticError, csv.Error, duckdb.Error, ValidationError):
        raise ValidationFailed("CSV import failed; check manifest, encoding and declared column types") from None
    finally:
        if staging is not None:
            shutil.rmtree(staging)


def _registration(connection_id: str, sources_root: Path) -> tuple[Path, dict[str, Any]]:
    """Read only the small server-owned registration file, never the snapshot."""
    name = connection_id.removeprefix("csv:")
    assert_safe_company(name)
    directory = _no_links(sources_root / name)
    if not directory.is_dir():
        raise NotFound("CSV source is not registered")
    try:
        receipt = json.loads(_read(directory / "registration.json", MAX_REGISTRATION_BYTES))
        if receipt["format_version"] != 1 or receipt["connection_id"] != connection_id:
            raise ValueError("invalid registration")
        if not isinstance(receipt["company_id"], str):
            raise TypeError("invalid registration")
    except DomainError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise ValidationFailed("CSV registration is invalid or unavailable") from None
    assert_safe_company(receipt["company_id"])
    return directory, receipt


def resolve_csv_owner(connection_id: str, sources_root: Path) -> str:
    """Company that owns a registered CSV source, for authorization before any snapshot work.

    Side-effect free: it neither opens nor hashes the snapshot, so a denied caller cannot make
    the server read another tenant's data. Use `resolve_csv` once access is authorized.
    """
    return str(_registration(connection_id, sources_root)[1]["company_id"])


def resolve_csv(connection_id: str, sources_root: Path) -> ConnectionSpec:
    """Resolve only server-owned registration; verify snapshot integrity on every use."""
    directory, receipt = _registration(connection_id, sources_root)
    try:
        db = _no_links(directory / "source.duckdb")
        if _sha(db) != receipt["snapshot_sha256"]:
            raise ValidationFailed("registered CSV snapshot integrity check failed")
        return ConnectionSpec(
            connection_id=connection_id,
            company_id=receipt["company_id"],
            path=str(db),
            schemas=receipt["schemas"],
            category_domains=receipt["category_domains"],
            as_of=receipt["as_of"],
        )
    except DomainError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise ValidationFailed("CSV registration is invalid or unavailable") from None
