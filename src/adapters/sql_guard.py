"""Defensive SQL guard (POD-300). Every query the adapter sends is parsed and checked here.

Allowed: exactly one SELECT (CTEs fine) whose tables are CTEs visible from where they are
referenced, schema-qualified tables in allowlisted schemas of the current database (never
catalog-qualified, so an attached database cannot be named), or allowlisted catalog table
functions. Settings and variable readers are denied. Everything else raises `PolicyViolation`.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from src.domain.errors import PolicyViolation

CATALOG_FUNCTIONS = frozenset({"duckdb_tables", "duckdb_columns", "duckdb_schemas"})
DENIED_FUNCTION_PREFIXES = ("read_", "glob", "getenv", "sniff_", "parquet_", "iceberg_", "delta_", "http")
DENIED_FUNCTIONS = frozenset(
    {"current_setting", "getvariable", "setvariable", "query", "query_table", "duckdb_secrets", "duckdb_settings"}
)


def _cte_in_scope(table: exp.Table) -> bool:
    """True if an enclosing query's WITH clause defines this (unqualified) table name."""
    name = table.name.lower()
    node = table.parent
    while node is not None:
        with_ = node.args.get("with_") if isinstance(node, exp.Query) else None
        if isinstance(with_, exp.With) and any(c.alias_or_name.lower() == name for c in with_.expressions):
            return True
        node = node.parent
    return False


def check_select(sql: str, allowed_schemas: set[str]) -> None:
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise PolicyViolation("query could not be parsed by the SQL guard") from exc
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise PolicyViolation("exactly one statement is allowed")
    root = statements[0]
    if not isinstance(root, exp.Select):
        raise PolicyViolation(f"only SELECT is allowed (got {type(root).__name__.upper()})")

    allowed = {s.lower() for s in allowed_schemas}

    for node in root.walk():
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if (
                name in DENIED_FUNCTIONS
                or name.startswith(DENIED_FUNCTION_PREFIXES)
                or type(node).__name__.lower().startswith("read")
            ):
                raise PolicyViolation(f"function {name!r} is not allowed")

    for table in root.find_all(exp.Table):
        target = table.this
        if table.catalog:
            raise PolicyViolation("catalog-qualified tables are not allowed")
        if isinstance(target, exp.Identifier):
            if not table.db and _cte_in_scope(table):
                continue
            if table.db.lower() not in allowed:
                raise PolicyViolation(f"schema {table.db or '<default>'!r} is not allowlisted")
        elif isinstance(target, exp.Anonymous):
            if target.name.lower() not in CATALOG_FUNCTIONS:
                raise PolicyViolation(f"table function {target.name!r} is not allowed")
        else:
            raise PolicyViolation(f"table source {type(target).__name__} is not allowed")
