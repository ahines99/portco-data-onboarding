"""Shared fixture machinery: table containers, deterministic writers, content digests."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from src.domain.hashing import content_hash


@dataclass
class Table:
    schema: str
    name: str
    columns: list[tuple[str, str]]  # (name, duckdb type)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    comment: str | None = None
    column_comments: dict[str, str] = field(default_factory=dict)

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass
class Fixture:
    name: str
    company_id: str
    as_of: date
    tables: list[Table]
    ground_truth: dict[str, Any]

    def table(self, qualified: str) -> Table:
        return next(t for t in self.tables if t.qualified == qualified)


def luhn_complete(prefix: str, length: int, rng: random.Random) -> str:
    """Return a Luhn-valid number of `length` digits starting with `prefix`."""
    digits = [int(d) for d in prefix]
    while len(digits) < length - 1:
        digits.append(rng.randint(0, 9))
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d = d * 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - total % 10) % 10
    return "".join(map(str, digits)) + str(check)


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | Decimal):
        return str(value)
    if isinstance(value, datetime):
        return f"TIMESTAMP '{value.isoformat(sep=' ')}'"
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def write_duckdb(fixture: Fixture, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", ".wal"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    con = duckdb.connect(str(path))
    try:
        for schema in sorted({t.schema for t in fixture.tables}):
            con.execute(f"CREATE SCHEMA {_q(schema)}")
        for t in fixture.tables:
            cols = ", ".join(f"{_q(n)} {typ}" for n, typ in t.columns)
            con.execute(f"CREATE TABLE {_q(t.schema)}.{_q(t.name)} ({cols})")
            for start in range(0, len(t.rows), 500):
                chunk = t.rows[start : start + 500]
                values = ",\n".join("(" + ", ".join(_sql_literal(v) for v in row) + ")" for row in chunk)
                con.execute(f"INSERT INTO {_q(t.schema)}.{_q(t.name)} VALUES {values}")
            if t.comment:
                con.execute(f"COMMENT ON TABLE {_q(t.schema)}.{_q(t.name)} IS {_sql_literal(t.comment)}")
            for col, text in t.column_comments.items():
                con.execute(f"COMMENT ON COLUMN {_q(t.schema)}.{_q(t.name)}.{_q(col)} IS {_sql_literal(text)}")
        con.execute("CHECKPOINT")
    finally:
        con.close()


def content_digest(fixture: Fixture) -> str:
    """Deterministic digest of the logical content (schemas, rows, comments)."""
    return content_hash(
        [
            {
                "table": t.qualified,
                "columns": t.columns,
                "rows": [[_sql_literal(v) for v in row] for row in t.rows],
                "comment": t.comment,
                "column_comments": t.column_comments,
            }
            for t in fixture.tables
        ]
    )
