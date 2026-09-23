"""Identifier safety (audit finding C1).

Source schema, table and column names are untrusted: they end up inside generated dbt SQL and
YAML, which dbt renders with Jinja before executing. Only plain identifiers are allowed through;
anything else is excluded at profiling time and reported by a hash, never by its text.
"""

from __future__ import annotations

import re

from src.domain.errors import PolicyViolation
from src.domain.hashing import sha256_text

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
SAFE_COMPANY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def is_safe_identifier(name: str) -> bool:
    return bool(SAFE_IDENTIFIER.fullmatch(name))


def redacted(name: str) -> str:
    """A stable, harmless stand-in for an unsafe identifier."""
    return f"unsafe_{sha256_text(name)[:10]}"


def assert_safe(*names: str) -> None:
    for name in names:
        if not is_safe_identifier(name):
            raise PolicyViolation(f"unsafe identifier {redacted(name)} cannot be used in generated code")


def assert_safe_company(company_id: str) -> None:
    if not SAFE_COMPANY_ID.fullmatch(company_id):
        raise PolicyViolation("company id must be alphanumeric with '_' or '-' (max 64 characters)")
