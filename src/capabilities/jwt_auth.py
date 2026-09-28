"""Asymmetric access-token verification against one operator-configured issuer/JWKS.

No URL or verification algorithm is accepted from the token. The issuer owns the role
and tenant claims. A token for another API or a user-editable profile is not authority.
"""

import re

import anyio
import jwt
from mcp.server.auth.provider import AccessToken

from src.capabilities.auth import ROLES
from src.settings import Settings

COMPANY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class JwtTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jwks = jwt.PyJWKClient(
            settings.jwt_jwks_url, timeout=5, lifespan=300, cache_keys=False, cooldown_duration=30
        )
        # Bound authentication work separately from dbt/application worker threads.
        self.limiter = anyio.CapacityLimiter(4)

    async def verify_token(self, token: str) -> AccessToken | None:
        if len(token) > 16384:
            return None
        return await anyio.to_thread.run_sync(self._verify, token, limiter=self.limiter)

    def _verify(self, token: str) -> AccessToken | None:
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") not in ("JWT", "at+jwt")
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 256
                or any(k in header for k in ("jku", "jwk", "x5u", "crit"))
            ):
                return None
            key = self.jwks.get_signing_key_from_jwt(token)
            if key.key_type != "RSA" or key.algorithm_name != "RS256" or getattr(key.key, "key_size", 0) < 2048:
                return None
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.settings.jwt_issuer_url,
                audience=self.settings.jwt_audience,
                leeway=self.settings.jwt_clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
            subject = claims["sub"]
            role = claims.get(self.settings.jwt_role_claim)
            companies = claims.get(self.settings.jwt_companies_claim)
            if (
                not isinstance(subject, str)
                or not subject.strip()
                or len(subject) > 128
                or any(ord(c) < 32 for c in subject)
                or not isinstance(role, str)
                or role not in ROLES
                or not isinstance(companies, list)
                or not 1 <= len(companies) <= 100
                or any(not isinstance(c, str) or not COMPANY.fullmatch(c) for c in companies)
                or type(claims["exp"]) is not int
                or type(claims["iat"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= self.settings.jwt_max_lifetime_seconds
            ):
                return None
            return AccessToken(
                token=token,
                client_id=subject,
                subject=subject,
                scopes=[f"role:{role}", *(f"company:{c}" for c in sorted(set(companies)))],
                expires_at=claims["exp"],
                resource=self.settings.http_base_url,
            )
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OSError):
            # No token, claim, endpoint response or transport exception is logged.
            return None
