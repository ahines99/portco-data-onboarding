"""Real signed JWTs, HTTP transport enforcement, production startup and bounded work."""

import json
import time
from io import BytesIO
from types import SimpleNamespace

import anyio
import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from src.capabilities.common import ServerState
from src.capabilities.jwt_auth import JwtTokenVerifier
from src.capabilities.workload import WorkloadMiddleware
from src.domain.errors import Forbidden
from src.mcp_server import build_http_app, build_server
from src.settings import Settings
from tests.conftest import make_service

pytestmark = [pytest.mark.security, pytest.mark.anyio]


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwt_settings(tmp_path, **changes):
    values = dict(
        _env_file=None,
        env="test",
        var_root=tmp_path,
        auth_mode="jwt",
        jwt_issuer_url="https://identity.example/",
        jwt_jwks_url="https://identity.example/jwks",
        jwt_audience="https://portco.example",
        http_base_url="https://portco.example",
    )
    return Settings(**(values | changes))


def access_token(key, claims=None, headers=None):
    now = int(time.time())
    payload = {
        "iss": "https://identity.example/",
        "aud": "https://portco.example",
        "sub": "user:operator",
        "iat": now,
        "exp": now + 600,
        "portco_role": "agent",
        "portco_companies": ["portco_a"],
    }
    payload.update(claims or {})
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "key-one", "typ": "JWT"} | (headers or {}))


@pytest.fixture
def jwks_endpoint(signing_key, monkeypatch):
    # Exercise the real PyJWKClient cache/parser while replacing only the network endpoint.
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    keys = [{**public, "kid": "key-one", "alg": "RS256", "use": "sig"}]
    calls = []

    class Endpoint:
        def open(self, request, timeout):
            assert request.full_url == "https://identity.example/jwks"
            assert timeout == 5
            calls.append(request.full_url)
            return BytesIO(json.dumps({"keys": keys}).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Endpoint())
    return keys, calls


async def test_signed_token_maps_only_verified_identity_and_tenants(tmp_path, signing_key, jwks_endpoint):
    verifier = JwtTokenVerifier(jwt_settings(tmp_path))
    token = access_token(signing_key)
    result = await verifier.verify_token(token)
    assert result and result.client_id == "user:operator"
    assert result.scopes == ["role:agent", "company:portco_a"]
    assert result.resource == "https://portco.example" and result.expires_at
    assert await verifier.verify_token(token)
    assert len(jwks_endpoint[1]) == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.example/"},
        {"aud": "other-api"},
        {"exp": 1},
        {"iat": 1},
        {"sub": ""},
        {"sub": "x" * 129},
        {"sub": "user\nadmin"},
        {"portco_role": "root"},
        {"portco_role": ["admin"]},
        {"portco_companies": "*"},
        {"portco_companies": ["*"]},
        {"portco_companies": []},
        {"portco_companies": ["../other"]},
        {"portco_companies": [42]},
        {"portco_companies": None},
        {"exp": "9999999999"},
        {"iat": True},
        {"nbf": 9999999999},
        {"exp": 9999999999},
    ],
)
async def test_invalid_signed_claims_fail_closed(tmp_path, signing_key, jwks_endpoint, claims):
    assert await JwtTokenVerifier(jwt_settings(tmp_path)).verify_token(access_token(signing_key, claims)) is None


@pytest.mark.parametrize("field", ["iss", "aud", "sub", "exp", "iat", "portco_role", "portco_companies"])
async def test_required_claims_cannot_be_omitted(tmp_path, signing_key, jwks_endpoint, field):
    data = jwt.decode(access_token(signing_key), options={"verify_signature": False})
    del data[field]
    token = jwt.encode(data, signing_key, algorithm="RS256", headers={"kid": "key-one"})
    assert await JwtTokenVerifier(jwt_settings(tmp_path)).verify_token(token) is None


@pytest.mark.parametrize(
    "headers",
    [
        {"kid": "unknown"},
        {"jku": "https://attacker.example/keys"},
        {"jwk": {}},
        {"x5u": "https://attacker.example/cert"},
        {"crit": ["unknown"]},
        {"typ": "id+jwt"},
    ],
)
async def test_token_header_cannot_select_trust_policy(tmp_path, signing_key, jwks_endpoint, headers):
    assert (
        await JwtTokenVerifier(jwt_settings(tmp_path)).verify_token(access_token(signing_key, headers=headers)) is None
    )


async def test_wrong_signature_unsigned_hmac_and_oversized_tokens_rejected(tmp_path, signing_key, jwks_endpoint):
    verifier = JwtTokenVerifier(jwt_settings(tmp_path))
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = [
        access_token(other),
        jwt.encode({}, key="", algorithm="none"),
        jwt.encode({}, "test-only-secret-not-a-real-credential-123", algorithm="HS256"),
        "x" * 16385,
        "broken",
    ]
    for token in tokens:
        assert await verifier.verify_token(token) is None


async def test_rotated_and_removed_keys_obey_cache_lifetime(tmp_path, signing_key, jwks_endpoint):
    verifier = JwtTokenVerifier(jwt_settings(tmp_path))
    old = access_token(signing_key)
    assert await verifier.verify_token(old)
    replacement = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(replacement.public_key()))
    jwks_endpoint[0][:] = [{**public, "kid": "key-two", "alg": "RS256", "use": "sig"}]
    fresh = access_token(replacement, headers={"kid": "key-two"})
    assert await verifier.verify_token(fresh) is None  # unknown-kid refresh cooldown
    assert len(jwks_endpoint[1]) == 1
    verifier.jwks.jwk_set_cache.put(None)  # simulate expiry of the documented five-minute cache
    assert await verifier.verify_token(fresh)
    assert await verifier.verify_token(old) is None


async def test_jwks_outage_fails_closed_without_leaking_response(tmp_path, signing_key, monkeypatch):
    verifier = JwtTokenVerifier(jwt_settings(tmp_path))

    def unavailable(*args):
        raise jwt.PyJWKClientConnectionError("private upstream diagnostics")

    monkeypatch.setattr(verifier.jwks, "get_signing_key_from_jwt", unavailable)
    assert await verifier.verify_token(access_token(signing_key)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"auth_mode": "static"},
        {"database_url": "sqlite:///state.db"},
        {"var_root": "relative"},
        {"require_distinct_reviewer": False},
        {"faults": "adapter.aggregate:timeout"},
        {"http_tokens": "dev=reviewer:reviewer:*"},
        {"jwt_jwks_url": "http://identity.example/jwks"},
        {"jwt_issuer_url": "https://user:password@identity.example"},
        {"http_base_url": "https://portco.example/#fragment"},
        {"jwt_audience": ""},
    ],
)
def test_unsafe_production_configuration_rejected(tmp_path, changes):
    with pytest.raises(ValidationError):
        jwt_settings(
            tmp_path, **({"env": "production", "database_url": "postgresql+psycopg://db/app?sslmode=require"} | changes)
        )


def test_production_has_no_local_identity_fallback(tmp_path):
    settings = jwt_settings(tmp_path, env="production", database_url="postgresql+psycopg://db/app?sslmode=require")
    with pytest.raises(Forbidden):
        ServerState(settings=settings).principal()
    with pytest.raises(RuntimeError):
        build_server(settings, with_auth=False)
    with pytest.raises(RuntimeError):
        build_server(settings, principal=lambda: None)


async def test_real_http_jwt_auth_tenant_and_role_enforcement(
    tmp_path, fixtures_dir, signing_key, jwks_endpoint, monkeypatch
):
    settings = jwt_settings(tmp_path, env="production", database_url="postgresql+psycopg://db/app?sslmode=require")
    service = make_service(tmp_path)
    app = build_http_app(settings, service=service)
    transport = httpx2.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=transport, base_url=settings.http_base_url) as http:
            for token in (None, access_token(signing_key, {"aud": "wrong"}), "invalid"):
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                assert (
                    await http.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                ).status_code == 401
            assert (await http.get("/readyz")).status_code == 200
            metadata = await http.get("/.well-known/oauth-protected-resource")
            assert metadata.status_code == 200
            assert metadata.json()["authorization_servers"] == [settings.jwt_issuer_url]
            auth = {"Authorization": f"Bearer {access_token(signing_key)}"}
            for extra, status in [({"Host": "attacker.example"}, 421), ({"Origin": "https://attacker.example"}, 403)]:
                response = await http.post(
                    "/mcp", headers=auth | extra, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                )
                assert response.status_code == status
            response = await http.post(
                "/mcp", headers=auth | {"Content-Type": "application/json"}, content=b" " * 262145
            )
            assert response.status_code == 413
        async with (
            httpx2.AsyncClient(
                transport=transport, headers={"Authorization": f"Bearer {access_token(signing_key)}"}
            ) as http,
            streamable_http_client(settings.http_base_url + "/mcp", http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as client,
        ):
            await client.initialize()
            denied = await client.call_tool("start_onboarding_run", {"connection_id": "fixture:portco_b"})
            assert denied.is_error and denied.structured_content["code"] == "FORBIDDEN"

            run = await client.call_tool("start_onboarding_run", {"connection_id": "fixture:portco_a"})
            body = run.structured_content
            assert not run.is_error and body["gate"] == "mapping_review"
            denied = await client.call_tool(
                "submit_mapping_review",
                {
                    "run_id": body["run_id"],
                    "gate": body["gate"],
                    "subject_hash": body["pending_items"][0]["subject_hash"],
                    "decisions": [{"item_key": body["pending_items"][0]["item_key"], "decision": "approve"}],
                },
            )
            assert denied.is_error and denied.structured_content["code"] == "FORBIDDEN"

        from scripts.smoke_live import probe

        original_client = httpx2.AsyncClient
        monkeypatch.setattr(httpx2, "AsyncClient", lambda **kw: original_client(transport=transport, **kw))
        evidence = await probe(settings.http_base_url, access_token(signing_key))
        assert evidence["gate"] == "mapping_review" and evidence["review_method"] == "none"
        assert evidence["anonymous_and_invalid_tokens_denied"]


async def test_capacity_rejects_parallel_work_and_releases_after_failure():
    middleware = WorkloadMiddleware()
    entered, release = anyio.Event(), anyio.Event()
    ctx = SimpleNamespace(method="tools/call", params={"name": "start_onboarding_run"})

    async def hold(_ctx):
        entered.set()
        await release.wait()
        return "done"

    async with anyio.create_task_group() as group:
        group.start_soon(middleware, ctx, hold)
        await entered.wait()
        rejected = await middleware(ctx, hold)
        assert rejected.is_error and rejected.structured_content["retryable"]
        release.set()

    async def fail(_ctx):
        raise ValueError("test")

    with pytest.raises(ValueError):
        await middleware(ctx, fail)
    assert await middleware(ctx, hold) == "done"
