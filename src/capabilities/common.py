"""Shared MCP plumbing: server state, principal resolution, and the typed error contract (POD-507)."""

import functools
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import CallToolResult, TextContent

from src.domain.errors import DomainError, ErrorCode, ValidationFailed
from src.domain.models import Principal, Role
from src.settings import Settings, get_settings

log = structlog.get_logger(__name__)


@dataclass
class ServerState:
    settings: Settings = field(default_factory=get_settings)
    service: Any = None
    principal_override: Callable[[], Principal] | None = None
    service_factory: Callable[[], Any] | None = None

    def svc(self) -> Any:
        if self.service is None:
            if self.service_factory is not None:
                self.service = self.service_factory()
            else:
                from src.workflows.facade import OnboardingService

                self.service = OnboardingService.build(self.settings)
        return self.service

    def principal(self) -> Principal:
        if self.principal_override is not None:
            return self.principal_override()
        token = get_access_token()
        if token is not None:
            return principal_from_token(token.client_id, token.scopes)
        return Principal(principal_id=self.settings.local_principal_id, role=Role(self.settings.local_principal_role))


def principal_from_token(client_id: str, scopes: list[str]) -> Principal:
    role = next((s.split(":", 1)[1] for s in scopes if s.startswith("role:")), "agent")
    companies = tuple(s.split(":", 1)[1] for s in scopes if s.startswith("company:"))  # none -> no tenants
    return Principal(principal_id=client_id, role=Role(role), company_ids=companies)


def parse_uuid(value: str, name: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ValidationFailed(f"{name} must be a UUID") from exc


def error_result(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))], structured_content=payload, is_error=True
    )


def tool_errors[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Map domain errors to typed tool errors; never leak stack traces, SQL or values."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except DomainError as exc:
            return error_result(exc.to_dict())  # type: ignore[return-value]
        except Exception:
            correlation = uuid.uuid4().hex[:12]
            log.exception("tool_crashed", tool=fn.__name__, correlation_id=correlation)
            payload = {
                "code": ErrorCode.INTERNAL.value,
                "retryable": False,
                "message": f"internal error (correlation id {correlation})",
            }
            return error_result(payload)  # type: ignore[return-value]

    return wrapper
