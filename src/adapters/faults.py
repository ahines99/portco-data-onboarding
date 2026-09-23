"""Failure injection (POD-406).

Spec grammar (comma-separated):  <target>:<kind>[:nth=N|:once|:always]
  target  adapter.<method>  |  adapter.aggregate (any aggregate method)  |  dbt.build
  kind    timeout | unavailable | crash
Examples: "adapter.aggregate:timeout:nth=3", "adapter.list_tables:unavailable",
          "dbt.build:crash:once".
Refuses to activate when env == "production".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.domain.errors import DependencyFailed, PolicyViolation, SourceTimeout, SourceUnavailable

AGGREGATE_METHODS = frozenset(
    {
        "row_count",
        "column_stats",
        "pattern_counts",
        "luhn_count",
        "normalized_distinct",
        "distinct_count_multi",
        "containment",
        "pair_difference",
        "low_cardinality_values",
    }
)


@dataclass
class Fault:
    target: str
    kind: str
    nth: int | None = None
    once: bool = False
    fired: int = 0

    def matches(self, target: str) -> bool:
        if self.target == target:
            return True
        return self.target == "adapter.aggregate" and target.removeprefix("adapter.") in AGGREGATE_METHODS

    def raise_(self) -> None:
        msg = f"injected fault: {self.target}:{self.kind}"
        if self.kind == "timeout":
            raise SourceTimeout(msg)
        if self.kind == "unavailable":
            raise SourceUnavailable(msg)
        raise DependencyFailed(msg)


@dataclass
class FaultInjector:
    faults: list[Fault] = field(default_factory=list)
    calls: dict[str, int] = field(default_factory=dict)

    @classmethod
    def parse(cls, spec: str, env: str = "dev") -> FaultInjector:
        spec = spec.strip()
        if not spec:
            return cls()
        if env == "production":
            raise PolicyViolation("fault injection is disabled in production")
        faults = []
        for part in spec.split(","):
            bits = part.strip().split(":")
            fault = Fault(target=bits[0], kind=bits[1])
            for opt in bits[2:]:
                if opt.startswith("nth="):
                    fault.nth = int(opt[4:])
                elif opt == "once":
                    fault.once = True
            faults.append(fault)
        return cls(faults)

    @property
    def active(self) -> bool:
        return bool(self.faults)

    def check(self, target: str) -> None:
        self.calls[target] = self.calls.get(target, 0) + 1
        if target.removeprefix("adapter.") in AGGREGATE_METHODS:
            self.calls["adapter.aggregate"] = self.calls.get("adapter.aggregate", 0) + 1
        for f in self.faults:
            if not f.matches(target):
                continue
            count = self.calls[f.target]
            if f.nth is not None:
                if count == f.nth:
                    f.fired += 1
                    f.raise_()
            elif f.once:
                if f.fired == 0:
                    f.fired += 1
                    f.raise_()
            else:
                f.fired += 1
                f.raise_()


class FaultyAdapter:
    """Proxy that consults the injector before delegating each adapter call."""

    def __init__(self, inner: Any, injector: FaultInjector) -> None:
        self._inner = inner
        self._injector = injector

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr) or name.startswith("_") or name == "close":
            return attr

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self._injector.check(f"adapter.{name}")
            return attr(*args, **kwargs)

        return wrapped
