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
SSN = re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")
# Stand-alone digit runs only: not part of a hex hash, identifier, or decimal fraction.
CARD = re.compile(r"(?<![0-9A-Za-z.])\d{13,19}(?![0-9A-Za-z]|\.\d)")
PHONE = re.compile(r"^\+?\d[\d ()\-.]{7,}\d$")


def luhn_valid(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d >= 5 else d * 2
        total += d
    return total % 10 == 0


def detect(text: str) -> list[str]:
    kinds: list[str] = []
    if EMAIL.search(text):
        kinds.append("email")
    if SSN.search(text):
        kinds.append("national_id")
    if any(luhn_valid(m.group(0)) for m in CARD.finditer(text)):
        kinds.append("payment_card")
    return kinds


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
