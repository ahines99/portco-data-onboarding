"""PII guard and call accounting middleware (POD-702, POD-804, POD-805).

Every tool result, resource read and prompt is scanned. A violation blocks the response (it is
never "cleaned") and returns POLICY_VIOLATION.

Each tool call runs inside an `mcp.tool` span with the tool name and principal bound to the log
context. Calls that concern a run (a `run_id` argument, or a run created by the call) are
recorded in that run's audit log as `mcp_tool_called`; agent reads of `evidence://` resources as
`evidence_read`; and a response blocked by the guard as `pii_guard_blocked`, so run metrics
count what the agent actually did.
"""

from typing import Any
from uuid import UUID

import structlog
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError

from src.capabilities.common import ServerState, error_result
from src.domain.models import AuditEvent, Principal
from src.domain.pii_guard import PiiGuard
from src.observability import span

log = structlog.get_logger(__name__)
GUARDED = {"tools/call", "resources/read", "prompts/get"}


def _outcome(result: Any) -> tuple[bool, dict[str, Any]]:
    """(is_error, structured content) of a tool result, whether a model or its wire-format dict."""
    if isinstance(result, dict):
        structured = result.get("structuredContent") or result.get("structured_content") or {}
        return bool(result.get("isError") or result.get("is_error")), structured
    return bool(getattr(result, "is_error", False)), getattr(result, "structured_content", None) or {}


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class PiiGuardMiddleware:
    def __init__(self, guard: PiiGuard, state: ServerState | None = None) -> None:
        self.guard = guard
        self.state = state
        self.blocked = 0

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        params = dict(ctx.params or {})
        tool = str(params.get("name", "")) if ctx.method == "tools/call" else ""
        principal = self._principal()
        with structlog.contextvars.bound_contextvars(
            tool_name=tool or None, principal=principal.principal_id if principal else None
        ):
            if tool:
                with span("mcp.tool", tool=tool, principal=principal.principal_id if principal else None) as sp:
                    result = await self._guarded(ctx, call_next)
                    sp.set_attribute("outcome", "error" if _outcome(result)[0] else "ok")
                self._account_tool(tool, params.get("arguments") or {}, result, principal)
                return result
            result = await self._guarded(ctx, call_next)
            if ctx.method == "resources/read":
                self._account_read(str(params.get("uri", "")), principal)
            return result

    async def _guarded(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        result = await call_next(ctx)
        if ctx.method not in GUARDED or result is None:
            return result
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        violations = self.guard.scan(payload)
        if not violations:
            return result
        self.blocked += 1
        kinds = sorted({v.kind for v in violations})
        log.warning("pii_guard_blocked", method=ctx.method, kinds=kinds, paths=[v.path for v in violations][:5])
        args = dict(ctx.params or {}).get("arguments") or {}
        self._audit(_uuid(args.get("run_id")), "pii_guard_blocked", {"method": ctx.method, "kinds": kinds})
        message = "response blocked by the PII guard: it contained data classified as personal information"
        if ctx.method == "tools/call":
            return error_result({"code": "POLICY_VIOLATION", "message": message, "retryable": False})
        raise MCPError(code=-32603, message=message)

    # ------------------------------------------------------------------ accounting

    def _principal(self) -> Principal | None:
        if self.state is None:
            return None
        try:
            return self.state.principal()
        except Exception:  # accounting must never break a call
            return None

    def _account_tool(self, tool: str, args: dict[str, Any], result: Any, principal: Principal | None) -> None:
        is_error, structured = _outcome(result)
        run_id = _uuid(args.get("run_id")) or _uuid(structured.get("run_id"))
        payload: dict[str, Any] = {"tool": tool, "is_error": is_error}
        if is_error and "code" in structured:
            payload["code"] = structured["code"]
        self._audit(run_id, "mcp_tool_called", payload, principal)

    def _account_read(self, uri: str, principal: Principal | None) -> None:
        if not uri.startswith("evidence://") or self.state is None:
            return
        evidence_id = _uuid(uri.removeprefix("evidence://"))
        if evidence_id is None:
            return
        try:
            with self.state.svc().store.tx() as tx:
                _, run_id, _ = tx.evidence.get(evidence_id)
        except Exception:
            return
        self._audit(run_id, "evidence_read", {"evidence_id": str(evidence_id)}, principal)

    def _audit(
        self, run_id: UUID | None, event_type: str, payload: dict[str, Any], principal: Principal | None = None
    ) -> None:
        if run_id is None or self.state is None:
            return
        principal = principal or self._principal()
        try:
            svc = self.state.svc()
            with svc.store.tx() as tx:
                run = tx.runs.get(run_id)
                if principal is None or not principal.can_access(run.company_id):
                    return  # never write into another tenant's audit log
                tx.audit.append(
                    AuditEvent(
                        run_id=run_id,
                        step=run.current_step or "",
                        actor=principal.principal_id,
                        event_type=event_type,
                        payload=payload,
                    )
                )
        except Exception:  # accounting must never break a call
            log.warning("mcp_accounting_failed", event_type=event_type)
