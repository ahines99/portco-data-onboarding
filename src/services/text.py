"""Name normalization and similarity used by entity, join and mapping inference."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

from src.domain.ontology import load_abbreviations

ID_SUFFIXES = ("_id", "_no", "_num", "_code", "_key", "_ref", "_nr", "_cd", "id", "no", "nr")
ID_TOKENS = frozenset({"id", "no", "number", "num", "key", "code", "ref", "reference", "nr"})
MONEY_TOKENS = frozenset(
    {
        "amount",
        "price",
        "total",
        "mrr",
        "arr",
        "revenue",
        "cost",
        "salary",
        "debit",
        "credit",
        "balance",
        "fee",
        "value",
        "netwr",
        "gross",
        "net",
        "bookings",
    }
)
QUANTITY_TOKENS = frozenset({"qty", "quantity", "count", "units", "fkimg"})
NAME_TOKENS = frozenset({"name", "nm", "name1", "maktx", "txt50"})
CURRENCY_TOKENS = frozenset({"currency", "ccy", "curr", "waers", "waerk"})


@lru_cache(maxsize=4096)
def raw_tokens(name: str) -> tuple[str, ...]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return tuple(t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t)


@lru_cache(maxsize=4096)
def tokens(name: str) -> frozenset[str]:
    """Raw tokens plus abbreviation expansions (e.g. `cust_nm` -> cust, nm, customer, name)."""
    abbrev = load_abbreviations()
    out: set[str] = set()
    for t in raw_tokens(name):
        out.add(t)
        if t in abbrev:
            out.update(abbrev[t].split())
    return frozenset(out)


def singular(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def singular_tokens(name: str) -> frozenset[str]:
    return frozenset(singular(t) for t in tokens(name))


def jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def strip_id_suffix(name: str) -> str:
    low = name.lower()
    for suf in ID_SUFFIXES:
        if low.endswith(suf) and len(low) > len(suf) + 1:
            return low[: -len(suf)].rstrip("_")
    return low


def char_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, strip_id_suffix(a), strip_id_suffix(b)).ratio()


def is_id_like(name: str) -> bool:
    return bool(set(raw_tokens(name)) & ID_TOKENS) or name.lower().endswith(("id", "nr", "no"))


def is_money_like(name: str) -> bool:
    return bool(tokens(name) & MONEY_TOKENS)


def is_name_like(name: str) -> bool:
    return bool(set(raw_tokens(name)) & NAME_TOKENS)


def is_currency_like(name: str) -> bool:
    return bool(tokens(name) & CURRENCY_TOKENS)
