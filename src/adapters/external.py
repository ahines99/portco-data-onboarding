"""Source adapters (POD-300).

`SourceAdapter` is the only way domain services touch source data, and it exposes
aggregate reads only: counts, ratios, min/max of numeric and date columns, pattern-match
counts, and containment statistics. There is no row-fetch method. The one narrow exception
is `low_cardinality_values`, which returns only operator-approved category labels that also
pass the PII and prompt-injection guards (ADR-0003).
"""

from __future__ import annotations

import contextlib
import re
import threading
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import duckdb
from pydantic import BaseModel

from src.adapters.sql_guard import check_select
from src.domain.errors import (
    NotFound,
    PolicyViolation,
    SourceTimeout,
    SourceUnavailable,
    ValidationFailed,
)
from src.domain.hashing import content_hash
from src.domain.pii_guard import value_is_pii
from src.domain.project_models import ConnectionSpec
from src.domain.untrusted import UntrustedText, looks_like_injection
from src.observability import span

SYSTEM_SCHEMAS = frozenset({"information_schema", "pg_catalog", "main"})
NUMERIC_PREFIXES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "NUMERIC",
)
INTEGER_PREFIXES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
)
SAFE_CATEGORY = re.compile(r"^[A-Za-z0-9 _&./()\-]{1,40}$")
# Labels of these columns are people (sales reps, owners, employees), never categories.
PERSON_COLUMN_TOKENS = frozenset(
    {"name", "owner", "rep", "manager", "user", "employee", "contact", "person", "assignee", "salesperson", "author"}
)


def _column_tokens(column: str) -> set[str]:
    return set(re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", column).lower()))


def type_family(dtype: str) -> str:
    t = dtype.upper()
    if t.startswith(NUMERIC_PREFIXES):
        return "integer" if t.startswith(INTEGER_PREFIXES) else "decimal"
    if t == "DATE":
        return "date"
    if t.startswith("TIMESTAMP"):
        return "timestamp"
    if t == "BOOLEAN":
        return "boolean"
    if t.startswith(("VARCHAR", "TEXT", "CHAR", "STRING")):
        return "string"
    return "other"


class ColumnMeta(BaseModel):
    name: str
    dtype: str
    ordinal: int
    nullable: bool
    comment: UntrustedText | None = None

    @property
    def family(self) -> str:
        return type_family(self.dtype)


class TableMeta(BaseModel):
    schema_name: str
    table_name: str
    comment: UntrustedText | None = None
    columns: list[ColumnMeta]

    @property
    def qualified(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


class ColumnStats(BaseModel):
    non_null: int
    distinct: int
    min_value: str | None = None
    max_value: str | None = None
    mean_value: float | None = None
    integer_valued: bool | None = None
    negative_count: int | None = None
    true_count: int | None = None


class Containment(BaseModel):
    distinct_left: int
    distinct_matched: int
    rows_left: int
    rows_orphan: int

    @property
    def ratio(self) -> float:
        return self.distinct_matched / self.distinct_left if self.distinct_left else 0.0

    @property
    def orphan_rate(self) -> float:
        return self.rows_orphan / self.rows_left if self.rows_left else 0.0


class PairDifference(BaseModel):
    rows_compared: int
    rows_differing: int
    mean_relative_difference: float | None


class CategoryValues(BaseModel):
    values: list[str] | None
    withheld_reason: str | None = None


class ConnectionProbe(BaseModel):
    reachable: bool
    engine_version: str
    schemas: list[str]


class SourceAdapter(Protocol):
    spec: ConnectionSpec
    query_count: int

    def probe(self) -> ConnectionProbe: ...
    def verify_read_only(self) -> bool: ...
    def list_schemas(self) -> list[str]: ...
    def list_tables(self, schema: str) -> list[str]: ...
    def describe_table(self, schema: str, table: str) -> TableMeta: ...
    def row_count(self, schema: str, table: str) -> int: ...
    def column_stats(self, schema: str, table: str, columns: Sequence[ColumnMeta]) -> dict[str, ColumnStats]: ...
    def pattern_counts(
        self, schema: str, table: str, column: str, patterns: dict[str, tuple[str, bool]]
    ) -> dict[str, int]: ...
    def luhn_count(self, schema: str, table: str, column: str) -> int: ...
    def normalized_distinct(self, schema: str, table: str, column: str) -> int: ...
    def distinct_count_multi(self, schema: str, table: str, columns: Sequence[str]) -> int: ...
    def containment(self, left: tuple[str, str, str], right: tuple[str, str, str]) -> Containment: ...
    def pair_difference(self, schema: str, table: str, a: str, b: str) -> PairDifference: ...
    def low_cardinality_values(self, schema: str, table: str, column: str, max_values: int) -> CategoryValues: ...
    def fingerprint(self) -> str: ...
    def close(self) -> None: ...


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _luhn_sql(expr: str) -> str:
    d = f"CAST(substr(reverse({expr}), i + 1, 1) AS INTEGER)"
    return (
        f"(list_sum(list_transform(range(length({expr})), lambda i: CASE WHEN i % 2 = 1 "
        f"THEN {d} * 2 - CASE WHEN {d} >= 5 THEN 9 ELSE 0 END ELSE {d} END)) % 10 = 0)"
    )


class DuckDBAdapter:
    def __init__(self, spec: ConnectionSpec, timeout_seconds: float = 60.0) -> None:
        self.spec = spec
        self.timeout = timeout_seconds
        self.query_count = 0
        path = Path(spec.path)
        if not path.exists():
            raise SourceUnavailable(f"source for connection {spec.connection_id} is not reachable")
        try:
            self.con = duckdb.connect(str(path), read_only=spec.read_only)
        except duckdb.Error as exc:
            raise SourceUnavailable(f"could not open connection {spec.connection_id}") from exc
        self._tables: dict[tuple[str, str], TableMeta] = {}
        self._allowed: set[str] | None = None

    # ------------------------------------------------------------------ plumbing

    def close(self) -> None:
        with contextlib.suppress(duckdb.Error):
            self.con.close()

    def allowed_schemas(self) -> set[str]:
        if self._allowed is None:
            rows = self._raw_catalog(
                "SELECT DISTINCT schema_name FROM duckdb_tables() WHERE database_name = current_database()"
            )
            present = {r[0] for r in rows} - SYSTEM_SCHEMAS
            if set(self.spec.schemas) - present:
                raise NotFound("requested schema is not present in the source")
            self._allowed = {s for s in present if not self.spec.schemas or s in self.spec.schemas}
        return self._allowed

    def _raw_catalog(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        check_select(sql, set())
        return self._execute(sql, params)

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        self.query_count += 1
        timer = threading.Timer(self.timeout, self.con.interrupt)
        timer.start()
        try:
            with span("adapter.query", connection=self.spec.connection_id, n=self.query_count):
                return self.con.execute(sql, list(params)).fetchall()
        except duckdb.InterruptException as exc:
            raise SourceTimeout("source query exceeded its time budget") from exc
        except (duckdb.IOException, duckdb.ConnectionException) as exc:
            raise SourceUnavailable("source became unavailable") from exc
        finally:
            timer.cancel()

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        check_select(sql, self.allowed_schemas())
        return self._execute(sql, params)

    def _table(self, schema: str, table: str) -> TableMeta:
        key = (schema, table)
        if key not in self._tables:
            if schema not in self.allowed_schemas():
                raise PolicyViolation(f"schema {schema!r} is not allowlisted")
            self._tables[key] = self.describe_table(schema, table)
        return self._tables[key]

    def _qt(self, schema: str, table: str) -> str:
        self._table(schema, table)
        return f"{_q(schema)}.{_q(table)}"

    def _qc(self, schema: str, table: str, column: str) -> str:
        meta = self._table(schema, table)
        if column not in {c.name for c in meta.columns}:
            raise NotFound(f"column {schema}.{table}.{column} does not exist")
        return _q(column)

    # ------------------------------------------------------------------ connection

    def probe(self) -> ConnectionProbe:
        version = self._raw_catalog("SELECT version()")[0][0]
        return ConnectionProbe(reachable=True, engine_version=str(version), schemas=sorted(self.allowed_schemas()))

    def verify_read_only(self) -> bool:
        """Require an explicit engine read-only denial, never infer it from an arbitrary error."""
        schema = sorted(self.allowed_schemas())[0] if self.allowed_schemas() else "main"
        started = False
        try:
            self.con.execute("BEGIN")
            started = True
            self.con.execute(f"CREATE TABLE {_q(schema)}.{_q('__portco_write_probe_' + uuid4().hex)} (x INTEGER)")
        except duckdb.InvalidInputException as exc:
            return (
                started
                and 'cannot execute statement of type "create"' in str(exc).lower()
                and "which is attached in read-only mode" in str(exc).lower()
            )
        except duckdb.Error:
            return False
        finally:
            if started:
                with contextlib.suppress(duckdb.Error):
                    self.con.execute("ROLLBACK")
        return False

    def list_schemas(self) -> list[str]:
        return sorted(self.allowed_schemas())

    def list_tables(self, schema: str) -> list[str]:
        if schema not in self.allowed_schemas():
            raise PolicyViolation(f"schema {schema!r} is not allowlisted")
        rows = self._raw_catalog(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = current_database() "
            "AND schema_name = ? ORDER BY table_name",
            [schema],
        )
        return [r[0] for r in rows]

    def describe_table(self, schema: str, table: str) -> TableMeta:
        trow = self._raw_catalog(
            "SELECT comment FROM duckdb_tables() WHERE database_name = current_database() "
            "AND schema_name = ? AND table_name = ?",
            [schema, table],
        )
        if not trow:
            raise NotFound(f"table {schema}.{table} does not exist")
        crows = self._raw_catalog(
            "SELECT column_name, data_type, is_nullable, comment, column_index FROM duckdb_columns() "
            "WHERE database_name = current_database() AND schema_name = ? AND table_name = ? "
            "ORDER BY column_index",
            [schema, table],
        )
        comment = trow[0][0]
        return TableMeta(
            schema_name=schema,
            table_name=table,
            comment=UntrustedText.of(comment, f"{schema}.{table}") if comment else None,
            columns=[
                ColumnMeta(
                    name=n,
                    dtype=t,
                    ordinal=int(i),
                    nullable=bool(nl),
                    comment=UntrustedText.of(c, f"{schema}.{table}.{n}") if c else None,
                )
                for n, t, nl, c, i in crows
            ],
        )

    def row_count(self, schema: str, table: str) -> int:
        return int(self._query(f"SELECT count(*) FROM {self._qt(schema, table)}")[0][0])

    # ------------------------------------------------------------------ aggregates

    def column_stats(self, schema: str, table: str, columns: Sequence[ColumnMeta]) -> dict[str, ColumnStats]:
        qt = self._qt(schema, table)
        parts: list[str] = []
        for i, col in enumerate(columns):
            c = self._qc(schema, table, col.name)
            parts += [f"count({c}) AS nn{i}", f"count(DISTINCT {c}) AS d{i}"]
            fam = col.family
            if fam in {"integer", "decimal", "date", "timestamp"}:
                parts += [f"CAST(min({c}) AS VARCHAR) AS mn{i}", f"CAST(max({c}) AS VARCHAR) AS mx{i}"]
            if fam in {"integer", "decimal"}:
                parts += [
                    f"CAST(avg({c}) AS DOUBLE) AS av{i}",
                    f"count(*) FILTER (WHERE {c} <> trunc({c})) AS fr{i}",
                    f"count(*) FILTER (WHERE {c} < 0) AS ng{i}",
                ]
            if fam == "boolean":
                parts.append(f"count(*) FILTER (WHERE {c}) AS tr{i}")
        if not parts:
            return {}
        row = self._query(f"SELECT {', '.join(parts)} FROM {qt}")[0]
        names = [p.rsplit(" AS ", 1)[1] for p in parts]
        vals = dict(zip(names, row, strict=True))
        out: dict[str, ColumnStats] = {}
        for i, col in enumerate(columns):
            fam = col.family
            out[col.name] = ColumnStats(
                non_null=int(vals[f"nn{i}"]),
                distinct=int(vals[f"d{i}"]),
                min_value=vals.get(f"mn{i}"),
                max_value=vals.get(f"mx{i}"),
                mean_value=float(vals[f"av{i}"]) if vals.get(f"av{i}") is not None else None,
                integer_valued=(int(vals[f"fr{i}"]) == 0) if fam in {"integer", "decimal"} else None,
                negative_count=int(vals[f"ng{i}"]) if fam in {"integer", "decimal"} else None,
                true_count=int(vals[f"tr{i}"]) if fam == "boolean" else None,
            )
        return out

    def pattern_counts(
        self, schema: str, table: str, column: str, patterns: dict[str, tuple[str, bool]]
    ) -> dict[str, int]:
        if not patterns:
            return {}
        qt, c = self._qt(schema, table), self._qc(schema, table, column)
        names = list(patterns)
        exprs = [
            f"count(*) FILTER (WHERE {'regexp_full_match' if patterns[n][1] else 'regexp_matches'}"
            f"(CAST({c} AS VARCHAR), ?)) AS p{i}"
            for i, n in enumerate(names)
        ]
        row = self._query(
            f"SELECT {', '.join(exprs)} FROM {qt} WHERE {c} IS NOT NULL", [patterns[n][0] for n in names]
        )[0]
        return {n: int(v) for n, v in zip(names, row, strict=True)}

    def luhn_count(self, schema: str, table: str, column: str) -> int:
        qt, c = self._qt(schema, table), self._qc(schema, table, column)
        sql = (
            f"SELECT count(*) FILTER (WHERE {_luhn_sql('s')}) FROM (SELECT CAST({c} AS VARCHAR) AS s "
            f"FROM {qt} WHERE regexp_full_match(CAST({c} AS VARCHAR), '[0-9]{{13,19}}')) AS cards"
        )
        return int(self._query(sql)[0][0])

    def normalized_distinct(self, schema: str, table: str, column: str) -> int:
        qt, c = self._qt(schema, table), self._qc(schema, table, column)
        sql = (
            f"SELECT count(DISTINCT regexp_replace(lower(CAST({c} AS VARCHAR)), '[^a-z0-9]', '', 'g')) "
            f"FROM {qt} WHERE {c} IS NOT NULL"
        )
        return int(self._query(sql)[0][0])

    def distinct_count_multi(self, schema: str, table: str, columns: Sequence[str]) -> int:
        qt = self._qt(schema, table)
        cols = [self._qc(schema, table, c) for c in columns]
        where = " AND ".join(f"{c} IS NOT NULL" for c in cols)
        sql = f"SELECT count(*) FROM (SELECT DISTINCT {', '.join(cols)} FROM {qt} WHERE {where}) AS d"
        return int(self._query(sql)[0][0])

    def containment(self, left: tuple[str, str, str], right: tuple[str, str, str]) -> Containment:
        lt, lc = self._qt(left[0], left[1]), self._qc(*left)
        rt, rc = self._qt(right[0], right[1]), self._qc(*right)
        sql = (
            f"WITH l AS (SELECT DISTINCT CAST({lc} AS VARCHAR) AS v FROM {lt} WHERE {lc} IS NOT NULL), "
            f"r AS (SELECT DISTINCT CAST({rc} AS VARCHAR) AS v FROM {rt} WHERE {rc} IS NOT NULL), "
            f"lr AS (SELECT CAST({lc} AS VARCHAR) AS v FROM {lt} WHERE {lc} IS NOT NULL) "
            "SELECT (SELECT count(*) FROM l), (SELECT count(*) FROM l WHERE v IN (SELECT v FROM r)), "
            "(SELECT count(*) FROM lr), (SELECT count(*) FROM lr WHERE v NOT IN (SELECT v FROM r))"
        )
        a, b, c, d = self._query(sql)[0]
        return Containment(distinct_left=int(a), distinct_matched=int(b), rows_left=int(c), rows_orphan=int(d))

    def pair_difference(self, schema: str, table: str, a: str, b: str) -> PairDifference:
        qt, ca, cb = self._qt(schema, table), self._qc(schema, table, a), self._qc(schema, table, b)
        sql = (
            f"SELECT count(*), count(*) FILTER (WHERE {ca} <> {cb}), "
            f"CAST(avg(abs({ca} - {cb}) / nullif(abs({ca}), 0)) AS DOUBLE) "
            f"FROM {qt} WHERE {ca} IS NOT NULL AND {cb} IS NOT NULL"
        )
        n, diff, rel = self._query(sql)[0]
        return PairDifference(
            rows_compared=int(n),
            rows_differing=int(diff),
            mean_relative_difference=float(rel) if rel is not None else None,
        )

    def low_cardinality_values(self, schema: str, table: str, column: str, max_values: int) -> CategoryValues:
        qt, c = self._qt(schema, table), self._qc(schema, table, column)
        if _column_tokens(column) & PERSON_COLUMN_TOKENS:
            return CategoryValues(values=None, withheld_reason="person_like_column")
        domain = self.spec.category_domains.get(f"{schema}.{table}.{column}")
        if domain is None:
            return CategoryValues(values=None, withheld_reason="unapproved_category_domain")
        rows = self._query(
            f"SELECT DISTINCT CAST({c} AS VARCHAR) AS v FROM {qt} WHERE {c} IS NOT NULL "
            f"ORDER BY v LIMIT {int(max_values) + 1}"
        )
        values = [str(r[0]) for r in rows]
        if len(values) > max_values:
            return CategoryValues(values=None, withheld_reason="too_many_values")
        for v in values:
            if looks_like_injection(v):
                return CategoryValues(values=None, withheld_reason="injection_suspected")
            if value_is_pii(v) or not SAFE_CATEGORY.match(v):
                return CategoryValues(values=None, withheld_reason="pii_or_unsafe_value")
            if v not in domain:
                return CategoryValues(values=None, withheld_reason="unapproved_category_value")
        return CategoryValues(values=values)

    def fingerprint(self) -> str:
        catalog = []
        for schema in self.list_schemas():
            for table in self.list_tables(schema):
                meta = self._table(schema, table)
                catalog.append(
                    {
                        "t": meta.qualified,
                        "cols": [(c.name, c.dtype) for c in meta.columns],
                        "rows": self.row_count(schema, table),
                        "values": self.value_checksum(schema, table),
                        "comment": meta.comment.text if meta.comment else None,
                    }
                )
        return content_hash(catalog)

    def value_checksum(self, schema: str, table: str) -> str:
        """Order-independent checksum of every row, so an in-place value edit changes the fingerprint
        (a row count and schema alone would not). Returned as an opaque aggregate, never values."""
        qt = self._qt(schema, table)
        return str(self._query(f"SELECT CAST(sum(hash(t)) AS VARCHAR) FROM {qt} AS t")[0][0])


# --------------------------------------------------------------------------- registry


class ConnectionRegistry:
    """Resolves connection ids. `fixture:<name>` maps to a generated fixture database."""

    def __init__(self, fixtures_dir: Path, sources_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir
        self.sources_dir = sources_dir
        self._extra: dict[str, ConnectionSpec] = {}

    def register(self, spec: ConnectionSpec) -> None:
        self._extra[spec.connection_id] = spec

    def resolve(self, connection_id: str) -> ConnectionSpec:
        base, _, query = connection_id.partition("?")
        if query:
            if not query.startswith("schemas="):
                raise ValidationFailed("unsupported connection option")
            schemas = sorted(s for s in query.removeprefix("schemas=").split(",") if s)
            registered = self.resolve(base)
            if not schemas:
                return registered.model_copy(update={"connection_id": connection_id})
            if registered.schemas and not set(schemas).issubset(registered.schemas):
                raise PolicyViolation("requested schemas exceed the registered allowlist")
            return registered.model_copy(update={"connection_id": connection_id, "schemas": schemas})
        if connection_id in self._extra:
            return self._extra[connection_id]
        if connection_id.startswith("csv:") and self.sources_dir is not None:
            from src.adapters.csv_source import resolve_csv

            return resolve_csv(connection_id, self.sources_dir)
        if not connection_id.startswith("fixture:"):
            raise NotFound(f"unknown connection {connection_id!r}")
        from src.fixtures.generate import build_fixture, ensure_fixture, fixture_names

        name = connection_id.removeprefix("fixture:")
        if name not in fixture_names():
            raise NotFound(f"unknown fixture connection {connection_id!r}")
        path = ensure_fixture(name, self.fixtures_dir)
        as_of = _fixture_as_of(name, build_fixture)
        from src.fixtures.category_domains import fixture_category_domains

        return ConnectionSpec(
            connection_id=connection_id,
            company_id=name,
            path=str(path),
            as_of=as_of,
            category_domains=fixture_category_domains(name),
        )

    def open(self, connection_id: str) -> DuckDBAdapter:
        spec = self.resolve(connection_id)
        if spec.kind != "duckdb":
            raise ValidationFailed(f"unsupported connection kind {spec.kind}")
        return DuckDBAdapter(spec)


_AS_OF_CACHE: dict[str, date] = {}


def _fixture_as_of(name: str, build: Any) -> date:
    if name not in _AS_OF_CACHE:
        base = name.partition("__")[0]
        from src.fixtures import portco_a, portco_b

        _AS_OF_CACHE[name] = {"portco_a": portco_a.AS_OF, "portco_b": portco_b.AS_OF}.get(base) or build(name).as_of
    return _AS_OF_CACHE[name]
