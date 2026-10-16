"""Defensive SQL guard (POD-300). Every query the adapter sends is parsed and checked here.

Allowed: exactly one SELECT (CTEs fine) whose tables are CTEs visible from where they are
referenced, schema-qualified tables in allowlisted schemas of the current database (never
catalog-qualified, so an attached database cannot be named), or allowlisted catalog table
functions. Settings and variable readers are denied. Everything else raises `PolicyViolation`.

CTE scope is lexical and follows declaration order: a non-recursive CTE sees the CTEs declared
before it in its own WITH plus those of enclosing queries, never itself or a later sibling
(DuckDB binds such names to physical tables). A name declared at or after the current position
of the WITH being bound hides any outer CTE of that name, so it is treated as a physical table
rather than guessed. Recursive CTEs are rejected outright. Any unqualified name not bound to a
visible CTE is a physical default-schema table, which is never allowlisted.
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
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _fold(name: str) -> str:
    """DuckDB matches identifiers case-insensitively for ASCII letters only."""
    return name.translate(_ASCII_LOWER)


def _check_table(table: exp.Table, visible: frozenset[str], allowed: set[str]) -> None:
    target = table.this
    if table.catalog:
        raise PolicyViolation("catalog-qualified tables are not allowed")
    if isinstance(target, exp.Identifier):
        if not table.db and _fold(table.name) in visible:
            return
        if _fold(table.db) not in allowed:
            raise PolicyViolation(f"schema {table.db or '<default>'!r} is not allowlisted")
    elif isinstance(target, exp.Anonymous):
        if target.name.lower() not in CATALOG_FUNCTIONS:
            raise PolicyViolation(f"table function {target.name!r} is not allowed")
    else:
        raise PolicyViolation(f"table source {type(target).__name__} is not allowed")


def _check_scope(node: exp.Expression, visible: frozenset[str], allowed: set[str], seen: set[int]) -> None:
    if isinstance(node, exp.Table):
        seen.add(id(node))
        _check_table(node, visible, allowed)
    with_ = node.args.get("with_")
    if isinstance(with_, exp.With):
        if with_.args.get("recursive"):
            raise PolicyViolation("recursive CTEs are not allowed")
        names = [_fold(cte.alias_or_name) for cte in with_.expressions]
        if len(set(names)) != len(names):
            raise PolicyViolation("duplicate CTE names are not allowed")
        for position, cte in enumerate(with_.expressions):
            # Self and later siblings are unbound here and also hide same-named outer CTEs.
            scope = (visible - frozenset(names[position:])) | frozenset(names[:position])
            _check_scope(cte, scope, allowed, seen)
        visible = visible | frozenset(names)
    for child in node.iter_expressions():
        if child is not with_:
            _check_scope(child, visible, allowed, seen)


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

    allowed = {_fold(s) for s in allowed_schemas}

    for node in root.walk():
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if (
                name in DENIED_FUNCTIONS
                or name.startswith(DENIED_FUNCTION_PREFIXES)
                or type(node).__name__.lower().startswith("read")
            ):
                raise PolicyViolation(f"function {name!r} is not allowed")

    seen: set[int] = set()
    _check_scope(root, frozenset(), allowed, seen)
    # Fail closed if any table reference escaped the scope walk.
    if any(id(table) not in seen for table in root.find_all(exp.Table)):
        raise PolicyViolation("table reference could not be bound by the SQL guard")
