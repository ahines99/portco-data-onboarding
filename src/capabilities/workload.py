"""Bound expensive work in the single-instance HTTP deployment."""

from typing import Any

import anyio
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

from src.capabilities.common import error_result

EXPENSIVE = frozenset(
    {
        "start_onboarding_run",
        "resume_run",
        "rerun_from_step",
        "generate_dbt_artifacts",
        "run_sandbox_tests",
        "publish_run",
        "profile_schema",
        "infer_entities",
        "infer_joins",
        "propose_canonical_mapping",
    }
)


class WorkloadMiddleware:
    def __init__(self, limit: int = 1) -> None:
        self.limiter = anyio.CapacityLimiter(limit)

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if ctx.method != "tools/call" or (ctx.params or {}).get("name") not in EXPENSIVE:
            return await call_next(ctx)
        try:
            self.limiter.acquire_nowait()
        except anyio.WouldBlock:
            return error_result(
                {
                    "code": "DEPENDENCY_FAILED",
                    "retryable": True,
                    "message": "workflow capacity is busy; retry after the current operation completes",
                }
            )
        try:
            return await call_next(ctx)
        finally:
            self.limiter.release()
