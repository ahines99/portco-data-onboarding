"""Bearer-token auth for the HTTP transport (POD-509).

Dev tokens come from `PORTCO_HTTP_TOKENS`: `token=principal:role:company1|company2;...`.
Each token becomes an AccessToken whose scopes encode the role and tenant scope; the
server resolves a `Principal` from it on every call. Production would swap this verifier for
an OAuth/JWT verifier without touching any tool.
"""

import hmac

from mcp.server.auth.provider import AccessToken

from src.settings import Settings


def parse_tokens(spec: str) -> dict[str, tuple[str, str, list[str]]]:
    out: dict[str, tuple[str, str, list[str]]] = {}
    for part in (p.strip() for p in spec.split(";") if p.strip()):
        token, _, rest = part.partition("=")
        principal, role, companies = [*rest.split(":"), "", "", ""][:3]
        out[token] = (principal, role or "agent", [c for c in companies.split("|") if c] or ["*"])
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
