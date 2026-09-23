"""Untrusted source text and prompt-injection heuristics (POD-703).

Anything retrieved from a source (table/column comments, names, category values) is data,
never instructions. `UntrustedText` makes that explicit in the type system: it cannot be
concatenated into a prompt without calling `render_as_data()`, which fences and escapes it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

_RULES: dict[str, re.Pattern[str]] = {
    "role_marker": re.compile(r"(^|\b)(system|assistant|user|developer)\s*:", re.I),
    "override_instruction": re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|all|earlier)\b.{0,20}"
        r"\b(instructions?|rules?|prompts?|guidance)\b",
        re.I,
    ),
    "approval_coercion": re.compile(
        r"\b(approve|certify|publish|mark)\b.{0,30}\b(all|everything|every|now|immediately|approved)\b", re.I
    ),
    "tool_invocation": re.compile(r"\b(call|invoke|run|execute)\b.{0,20}\b(tool|function|command)\b", re.I),
    "url": re.compile(r"https?://", re.I),
    "prompt_markup": re.compile(r"</?(system|instructions?|prompt)>", re.I),
}


def injection_signals(text: str | None) -> list[str]:
    """Names of the heuristics the text trips. Empty means nothing suspicious was found."""
    if not text:
        return []
    return [name for name, rx in _RULES.items() if rx.search(text)]


def looks_like_injection(text: str | None) -> bool:
    return bool(injection_signals(text))


class UntrustedText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    origin: str
    signals: list[str] = []

    @classmethod
    def of(cls, text: str, origin: str) -> UntrustedText:
        return cls(text=text, origin=origin, signals=injection_signals(text))

    @property
    def flagged(self) -> bool:
        return bool(self.signals)

    def render_as_data(self, max_len: int = 200) -> str:
        """Fence the text as quoted data. Flagged text is withheld entirely."""
        if self.flagged:
            return f"<untrusted origin={self.origin!r} withheld=true signals={','.join(self.signals)}/>"
        clipped = self.text[:max_len].replace("<", "&lt;").replace(">", "&gt;")
        return f"<untrusted origin={self.origin!r}>{clipped}</untrusted>"

    def __str__(self) -> str:  # never silently leak into f-strings
        return self.render_as_data()
