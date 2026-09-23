"""Bearer-token auth for the HTTP transport (POD-509).

Dev tokens come from `PORTCO_HTTP_TOKENS`: `token=principal:role:company1|company2;...`.
Each token becomes an AccessToken whose scopes encode the role and tenant scope; the
server resolves a `Principal` from it on every call. Production would swap this verifier for
an OAuth/JWT verifier without touching any tool.

Fail closed: a token without a company list is scoped to no tenant (grant all with `*`
explicitly), and a malformed entry is dropped with a warning, never defaulted to a role.
"""

import hmac

import structlog
from mcp.server.auth.provider import AccessToken

from src.settings import Settings

ROLES = frozenset({"agent", "reviewer", "admin"})
log = structlog.get_logger(__name__)


def parse_tokens(spec: str) -> dict[str, tuple[str, str, list[str]]]:
    out: dict[str, tuple[str, str, list[str]]] = {}
    for n, part in enumerate(p.strip() for p in spec.split(";") if p.strip()):
        token, _, rest = part.partition("=")
        # Principal ids may contain ':' (e.g. agent:claude), so split role and companies from the right.
        parts = rest.rsplit(":", 2)
        if len(parts) == 3 and parts[1] in ROLES:
            principal, role, companies = parts
        else:
            principal, _, role = rest.rpartition(":")
            companies = ""
        if not token or not principal or role not in ROLES:
            log.warning("http_token_dropped", entry=n, reason="expected token=principal:role:companies")
            continue
        scope = [c for c in companies.split("|") if c]
        if not scope:
            log.warning("http_token_unscoped", entry=n, principal=principal)
        out[token] = (principal, role, scope)
    return out


class StaticTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        secret = settings.http_tokens.get_secret_value() if settings.http_tokens else ""
        self._tokens = parse_tokens(secret)

    async def verify_token(self, token: str) -> AccessToken | None:
        for known, (principal, role, companies) in self._tokens.items():
            if hmac.compare_digest(known, token):
                return AccessToken(
                    token=token, client_id=principal, scopes=[f"role:{role}", *(f"company:{c}" for c in companies)]
                )
        return None
