"""PII guard middleware (POD-702): every tool result, resource read and prompt is scanned.

A violation blocks the response (it is never "cleaned") and returns POLICY_VIOLATION.
"""

from typing import Any

import structlog
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError

from src.capabilities.common import error_result
from src.domain.pii_guard import PiiGuard

log = structlog.get_logger(__name__)
GUARDED = {"tools/call", "resources/read", "prompts/get"}


class PiiGuardMiddleware:
    def __init__(self, guard: PiiGuard) -> None:
        self.guard = guard
        self.blocked = 0

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        result = await call_next(ctx)
        if ctx.method not in GUARDED or result is None:
            return result
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        violations = self.guard.scan(payload)
        if not violations:
            return result
        self.blocked += 1
        log.warning(
            "pii_guard_blocked",
            method=ctx.method,
            kinds=sorted({v.kind for v in violations}),
            paths=[v.path for v in violations][:5],
        )
        message = "response blocked by the PII guard: it contained data classified as personal information"
        if ctx.method == "tools/call":
            return error_result({"code": "POLICY_VIOLATION", "message": message, "retryable": False})
        raise MCPError(code=-32603, message=message)
