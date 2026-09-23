"""Defensive SQL guard (POD-300). Every query the adapter sends is parsed and checked here.

Allowed: exactly one SELECT (CTEs fine) whose tables are CTEs, tables in allowlisted schemas,
or allowlisted catalog table functions. Everything else raises `PolicyViolation`.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from src.domain.errors import PolicyViolation

CATALOG_FUNCTIONS = frozenset({"duckdb_tables", "duckdb_columns", "duckdb_schemas"})
DENIED_FUNCTION_PREFIXES = ("read_", "glob", "getenv", "sniff_", "parquet_", "iceberg_", "delta_", "http")


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

    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    allowed = {s.lower() for s in allowed_schemas}

    for node in root.walk():
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name.startswith(DENIED_FUNCTION_PREFIXES) or type(node).__name__.lower().startswith("read"):
                raise PolicyViolation(f"function {name!r} is not allowed")

    for table in root.find_all(exp.Table):
        target = table.this
        if isinstance(target, exp.Identifier):
            if not table.db and table.name.lower() in cte_names:
                continue
            if table.db.lower() not in allowed:
                raise PolicyViolation(f"schema {table.db or '<default>'!r} is not allowlisted")
        elif isinstance(target, exp.Anonymous):
            if target.name.lower() not in CATALOG_FUNCTIONS:
                raise PolicyViolation(f"table function {target.name!r} is not allowed")
        else:
            raise PolicyViolation(f"table source {type(target).__name__} is not allowed")
