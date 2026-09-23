"""Run status transitions (POD-401). Every status change is checked against this table.

A run is advanced only by the worker holding its execution lease; `CLAIMABLE` lists the
statuses a worker may claim from. A RUNNING run whose lease has expired (the worker died)
may also be claimed, which is how crashed runs are recovered.
"""

from __future__ import annotations

from src.domain.errors import Conflict
from src.domain.models import RunStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.RUNNING, S.CANCELLED}),
    S.RUNNING: frozenset({S.PENDING, S.NEEDS_REVIEW, S.COMPLETE, S.FAILED, S.CANCELLED}),
    S.NEEDS_REVIEW: frozenset({S.RUNNING, S.PENDING, S.CANCELLED}),
    S.FAILED: frozenset({S.RUNNING, S.PENDING, S.CANCELLED}),
    S.COMPLETE: frozenset({S.PENDING}),  # rerun_from reopens a completed run
    S.CANCELLED: frozenset(),  # terminal
}

CLAIMABLE: frozenset[S] = frozenset({S.PENDING, S.NEEDS_REVIEW, S.FAILED})


def can_transition(src: S, dst: S) -> bool:
    if src == dst:
        return src is not S.CANCELLED
    return dst in TRANSITIONS[src]


def check_transition(src: S, dst: S) -> None:
    if not can_transition(src, dst):
        raise Conflict(f"a {src.value} run cannot become {dst.value}")
