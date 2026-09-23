"""PII guard (POD-702).

Scans any outbound structure (MCP tool results, resources, prompts, LLM inputs, log records)
for raw PII: planted canary values plus generic detectors for emails, national IDs and
Luhn-valid card numbers. A violation blocks the response; it never gets "cleaned".
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 123-45-6789 or 123 45 6789 (same separator twice).
SSN = re.compile(r"(?<![\d-])\d{3}([- ])\d{2}\1\d{4}(?![\d-])")
# Stand-alone digit runs only: not part of a hex hash, identifier, or decimal fraction.
CARD = re.compile(r"(?<![0-9A-Za-z.])\d{13,19}(?![0-9A-Za-z]|\.\d)")
# Grouped card numbers (4-4-4-4[-3], Amex 4-6-5) with spaces or dashes; Luhn-checked after stripping.
CARD_GROUPED = re.compile(
    r"(?<![0-9A-Za-z.-])(?:\d{4}(?:[ -]\d{4}){3}(?:[ -]\d{1,3})?|\d{4}[ -]\d{6}[ -]\d{5})(?![0-9A-Za-z])"
)
# Phone numbers inside free text: international (+44 20 7946 0958) or (555) 123-4567 forms.
PHONE_INTL = re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?\(?\d{1,4}\)?(?:[ .-]\d{2,4}){2,4}(?!\w)")
PHONE_PAREN = re.compile(r"(?<!\w)\(\d{3}\)\s?\d{3}[ .-]\d{4}(?!\w)")
PHONE = re.compile(r"^\+?\d[\d ()\-.]{7,}\d$")  # a whole value that is a phone number
SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{8,}|(?:postgres(?:ql)?(?:\+\w+)?|mysql)://[^\s:/]+:[^\s@]+@)")


def luhn_valid(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d >= 5 else d * 2
        total += d
    return total % 10 == 0


def _card_spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in CARD.finditer(text) if luhn_valid(m.group(0))]
    for m in CARD_GROUPED.finditer(text):
        digits = re.sub(r"[ -]", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            spans.append(m.span())
    return spans


def detect(text: str) -> list[str]:
    kinds: list[str] = []
    if EMAIL.search(text):
        kinds.append("email")
    if SSN.search(text):
        kinds.append("national_id")
    if _card_spans(text):
        kinds.append("payment_card")
    if PHONE_INTL.search(text) or PHONE_PAREN.search(text):
        kinds.append("phone")
    return kinds


def mask(text: str, canaries: Iterable[str] = ()) -> str:
    """`text` with every detected PII value (and secret-looking token) replaced by a marker."""
    for c in canaries:
        if c:
            text = text.replace(c, "[PII]")
    for pattern in (EMAIL, SSN, PHONE_INTL, PHONE_PAREN, SECRET):
        text = pattern.sub("[PII]" if pattern is not SECRET else "[SECRET]", text)
    for start, end in sorted(_card_spans(text), reverse=True):
        text = text[:start] + "[PII]" + text[end:]
    return text


def value_is_pii(value: str) -> bool:
    return bool(detect(value)) or bool(PHONE.match(value.strip()))


@dataclass(frozen=True)
class Violation:
    path: str
    kind: str


class PiiGuard:
    def __init__(self, canaries: Iterable[str] = (), *, detectors: bool = True) -> None:
        self.canaries = tuple(c for c in canaries if c)
        self.detectors = detectors

    def scan_text(self, text: str, path: str = "$") -> list[Violation]:
        out = [Violation(path, "canary") for c in self.canaries if c in text]
        if self.detectors:
            out += [Violation(path, k) for k in detect(text)]
        return out

    def scan(self, obj: Any, path: str = "$") -> list[Violation]:
        if isinstance(obj, BaseModel):
            return self.scan(obj.model_dump(mode="json"), path)
        if isinstance(obj, str):
            return self.scan_text(obj, path)
        if isinstance(obj, dict):
            out: list[Violation] = []
            for k, v in obj.items():
                out += self.scan_text(str(k), f"{path}.<key>")
                out += self.scan(v, f"{path}.{k}")
            return out
        if isinstance(obj, list | tuple | set):
            out = []
            for i, v in enumerate(obj):
                out += self.scan(v, f"{path}[{i}]")
            return out
        return []
