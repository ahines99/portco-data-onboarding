"""Boot the actual production entry point (`python -m src.serve`) against isolated local services.

Production mode refuses SQLite, static tokens, a plain-HTTP JWKS endpoint and a database without TLS.
This smoke therefore supplies only disposable, local stand-ins:

- a PostgreSQL URL in the provider's `DATABASE_URL` form, for a TLS-enabled server the caller
  started for this purpose (CI uses a throwaway container). The entry point's own URL preparation
  converts it to psycopg with `sslmode=require`;
- RSA signing keys, a throwaway CA and an HTTPS JWKS endpoint generated in memory. Only the server
  process trusts that CA (`SSL_CERT_FILE`); nothing is installed system-wide;
- a temporary persistent root (the `/data` analogue) and a non-default `PORT`.

It verifies startup with migration to head over TLS, `/healthz`, `/readyz`, protected-resource
metadata, rejection of anonymous, wrong-audience and untrusted-key tokens and of a foreign Host or
Origin, an authorized MCP call that starts a synthetic run, graceful termination, and that the run
survives a restart. Tokens and the database password never reach the output, the evidence file or
the logs it checks. Never point this at a database holding data you need: migrations run and
synthetic runs are written there.

Run from the repository root: `uv run python -m scripts.smoke_production --database-url URL`.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import ipaddress
import json
import os
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx2
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.engine import URL, make_url

REPO = Path(__file__).resolve().parents[1]
AUDIENCE = "https://portco-production-smoke-api"
ROLE_CLAIM, COMPANIES_CLAIM = "portco_role", "portco_companies"
LOOPBACK = "127.0.0.1"


# --------------------------------------------------------------------------- keys, certificates, tokens


def new_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def loopback_tls_material() -> tuple[bytes, bytes, bytes]:
    """A throwaway CA and a server certificate for 127.0.0.1/localhost: (ca_pem, cert_pem, key_pem)."""
    now = dt.datetime.now(dt.UTC)
    ca_key, server_key = new_rsa_key(), new_rsa_key()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "portco production smoke CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    server = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(LOOPBACK))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    return ca.public_bytes(pem), server.public_bytes(pem), _pem(server_key)


def public_jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}


def mint(
    key: rsa.RSAPrivateKey,
    *,
    kid: str,
    issuer: str,
    audience: str,
    subject: str,
    role: str,
    companies: list[str],
    lifetime: int = 600,
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + lifetime,
        ROLE_CLAIM: role,
        COMPANIES_CLAIM: companies,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid, "typ": "JWT"})


# --------------------------------------------------------------------------- local HTTPS JWKS issuer


@dataclass
class JwksServer:
    """A loopback HTTPS endpoint serving one JWK set; stands in for the identity provider's JWKS."""

    keys: list[dict[str, Any]]
    cert_pem: bytes
    key_pem: bytes
    requests: int = 0
    _server: ThreadingHTTPServer | None = field(default=None, repr=False)

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.server_address[1])

    @property
    def issuer(self) -> str:
        return f"https://{LOOPBACK}:{self.port}/"

    @property
    def jwks_url(self) -> str:
        return f"https://{LOOPBACK}:{self.port}/.well-known/jwks.json"

    def __enter__(self) -> JwksServer:
        owner = self
        body = json.dumps({"keys": self.keys}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/.well-known/jwks.json":
                    self.send_error(404)
                    return
                owner.requests += 1
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        with tempfile.TemporaryDirectory() as tmp:  # the TLS context reads key material from files
            cert, key = Path(tmp) / "server.pem", Path(tmp) / "server.key"
            cert.write_bytes(self.cert_pem)
            key.write_bytes(self.key_pem)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert, key)
        server = ThreadingHTTPServer((LOOPBACK, 0), Handler)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        self._server = server
        threading.Thread(target=server.serve_forever, name="jwks", daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


# --------------------------------------------------------------------------- production process


def normalized_database_url(database_url: str) -> URL:
    """The URL the entry point derives from a provider `DATABASE_URL` (psycopg, TLS required)."""
    url = make_url(database_url)
    if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise ValueError("the production smoke requires a PostgreSQL URL")
    url = url.set(drivername="postgresql+psycopg")
    if "sslmode" not in url.query:
        url = url.update_query_dict({"sslmode": "require"})
    return url


def server_environment(
    *,
    database_url: str,
    var_root: Path,
    port: int,
    issuer: str,
    jwks_url: str,
    ca_file: Path,
    audience: str = AUDIENCE,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment for `python -m src.serve`, mirroring render.yaml with local stand-ins.

    Inherited `PORTCO_*` and database variables are dropped so a developer or CI test profile
    (for example `PORTCO_ENV=test` or fault injection) cannot leak into the production boot.
    """
    inherited = os.environ if base_env is None else base_env
    env = {
        k: v
        for k, v in inherited.items()
        if not k.startswith("PORTCO_") and k not in {"DATABASE_URL", "PORT", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    env.update(
        {
            "PORTCO_ENV": "production",
            "PORTCO_AUTH_MODE": "jwt",
            "PORTCO_VAR_ROOT": str(var_root),
            "PORTCO_SEED_SYNTHETIC": "true",
            "PORTCO_REQUIRE_DISTINCT_REVIEWER": "true",
            "PORTCO_LLM_ENABLED": "false",
            "PORTCO_LOG_LEVEL": "INFO",
            "DATABASE_URL": database_url,
            "PORTCO_HTTP_BASE_URL": f"https://{LOOPBACK}:{port}",
            "PORTCO_JWT_ISSUER_URL": issuer,
            "PORTCO_JWT_JWKS_URL": jwks_url,
            "PORTCO_JWT_AUDIENCE": audience,
            "PORT": str(port),
            # Trust the throwaway CA for the JWKS fetch in this process only.
            "SSL_CERT_FILE": str(ca_file),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


@contextmanager
def production_server(env: dict[str, str], log: Path) -> Iterator[subprocess.Popen[bytes]]:
    with log.open("ab") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.serve"], cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT
        )
        try:
            yield proc
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=30)


def stop_gracefully(proc: subprocess.Popen[bytes], timeout: float = 45) -> dict[str, Any]:
    """SIGTERM as a platform would send it; on POSIX a clean uvicorn shutdown exits 0."""
    if proc.poll() is not None:
        raise RuntimeError(f"production server exited early with {proc.returncode}")
    graceful_signal = os.name == "posix"
    if graceful_signal:
        proc.send_signal(signal.SIGTERM)
    else:  # Windows has no SIGTERM delivery to a console child; this is a forced stop
        proc.terminate()
    code = proc.wait(timeout=timeout)
    if graceful_signal and code != 0:
        raise RuntimeError(f"production server did not shut down cleanly after SIGTERM (exit {code})")
    return {"signal": "SIGTERM" if graceful_signal else "TerminateProcess", "exit_code": code}


async def wait_ready(base: str, proc: subprocess.Popen[bytes], timeout: float) -> float:
    started = time.monotonic()
    async with httpx2.AsyncClient(timeout=5) as client:
        while time.monotonic() - started < timeout:
            if proc.poll() is not None:
                raise RuntimeError(f"production server exited during startup with {proc.returncode}")
            try:
                if (await client.get(f"{base}/readyz")).status_code == 200:
                    return round(time.monotonic() - started, 1)
            except httpx2.HTTPError:
                pass
            await asyncio.sleep(1)
    raise RuntimeError(f"production server was not ready within {timeout:.0f} seconds")


def wait_for_database(url: URL, timeout: float = 90) -> dict[str, Any]:
    """Wait for TLS connections (container init restarts the server) and report TLS and schema state."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(url, connect_args={"connect_timeout": 5}, poolclass=NullPool)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                with engine.connect() as conn:
                    tls = conn.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()
                    tables = conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar()
                    version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar() if tables else None
                    return {"tls": bool(tls), "alembic_version": version}
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
    finally:
        engine.dispose()


def migration_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(REPO / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


# --------------------------------------------------------------------------- HTTP and MCP checks


@dataclass
class Tokens:
    agent: str
    wrong_audience: str
    untrusted_key: str

    def secrets(self) -> list[str]:
        return [self.agent, self.wrong_audience, self.untrusted_key]


def tokens_for(issuer: str, signing: rsa.RSAPrivateKey, kid: str, audience: str = AUDIENCE) -> Tokens:
    def token(key: rsa.RSAPrivateKey, aud: str) -> str:
        return mint(
            key, kid=kid, issuer=issuer, audience=aud, subject="smoke:agent", role="agent", companies=["portco_a"]
        )

    return Tokens(
        agent=token(signing, audience),
        wrong_audience=token(signing, "https://another-api.example"),
        untrusted_key=token(new_rsa_key(), audience),  # same kid, key the issuer never published
    )


async def exercise_http(base: str, tokens: Tokens) -> dict[str, Any]:
    """Probe liveness, readiness, metadata and fail-closed authentication; returns observed results."""
    from scripts.smoke_container import check

    initialize = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    observed: dict[str, Any] = {}
    async with httpx2.AsyncClient(timeout=30, follow_redirects=False) as http:
        observed["healthz"] = (await http.get(f"{base}/healthz")).status_code
        ready = await http.get(f"{base}/readyz")
        observed["readyz"] = ready.status_code
        observed["readyz_body"] = ready.json()
        metadata = await http.get(f"{base}/.well-known/oauth-protected-resource")
        observed["protected_resource"] = metadata.json().get("resource") if metadata.status_code == 200 else None

        async def post(token: str | None, **headers: str) -> int:
            if token:
                headers["Authorization"] = f"Bearer {token}"
            headers.setdefault("Accept", "application/json, text/event-stream")
            return (await http.post(f"{base}/mcp", json=initialize, headers=headers)).status_code

        observed["anonymous"] = await post(None)
        observed["wrong_audience"] = await post(tokens.wrong_audience)
        observed["untrusted_signing_key"] = await post(tokens.untrusted_key)
        host = base.split("://", 1)[1]
        observed["foreign_host"] = await post(tokens.agent, Host="attacker.example")
        observed["foreign_origin"] = await post(tokens.agent, Host=host, Origin="https://attacker.example")
    run = await check(base, tokens.agent)  # anonymous/invalid 401, MCP healthcheck (database ok), start a run
    observed["run"] = {"run_id": run["run_id"], "status": run["status"], "gate": run.get("gate")}
    return observed


def assert_http(observed: Mapping[str, Any], base: str) -> list[str]:
    """Failures in the observed HTTP results (empty when everything was rejected or served as expected)."""
    expected = {
        "healthz": 200,
        "readyz": 200,
        "anonymous": 401,
        "wrong_audience": 401,
        "untrusted_signing_key": 401,
        "foreign_host": 421,
        "foreign_origin": 403,
    }
    failures = [
        f"{name}: HTTP {observed.get(name)} (expected {code})"
        for name, code in expected.items()
        if observed.get(name) != code
    ]
    if observed.get("readyz_body") != {"status": "ready"}:
        failures.append(f"readyz body {observed.get('readyz_body')!r}")
    if str(observed.get("protected_resource") or "").rstrip("/") != base.replace("http://", "https://", 1):
        failures.append(f"protected resource metadata names {observed.get('protected_resource')!r}")
    run = observed.get("run") or {}
    if run.get("status") != "needs_review" or run.get("gate") != "mapping_review":
        failures.append(f"synthetic run stopped at {run.get('status')}/{run.get('gate')}, expected mapping review")
    return failures


async def run_status(base: str, token: str, run_id: str) -> dict[str, Any]:
    from scripts.smoke_container import check

    return await check(base, token, run_id)


# --------------------------------------------------------------------------- orchestration


def smoke(database_url: str, port: int, out: Path, startup_timeout: float) -> dict[str, Any]:
    db_url = normalized_database_url(database_url)
    head = migration_head()
    database_before = wait_for_database(db_url)
    if not database_before["tls"]:
        raise RuntimeError("the database connection is not using TLS")
    signing, kid = new_rsa_key(), "smoke-key-1"
    ca_pem, cert_pem, key_pem = loopback_tls_material()
    base = f"http://{LOOPBACK}:{port}"  # TLS terminates at the platform proxy in a real deployment
    result: dict[str, Any] = {
        "checked_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "entry_point": "python -m src.serve",
        "source_commit": _git_commit(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "port": port,
        "database": {"host": db_url.host, "port": db_url.port, "name": db_url.database, "tls": True},
        "alembic_before": database_before["alembic_version"],
        "alembic_head": head,
        "scope": (
            "Local production-profile smoke with a disposable PostgreSQL, generated keys and a local JWKS. "
            "Not a hosted deployment, provider TLS/proxy, identity-provider MFA or a restore rehearsal."
        ),
    }
    with (
        tempfile.TemporaryDirectory(prefix="portco-prod-smoke-") as tmp,
        JwksServer([public_jwk(signing, kid)], cert_pem, key_pem) as jwks,
    ):
        root = Path(tmp)
        (root / "ca.pem").write_bytes(ca_pem)
        env = server_environment(
            database_url=database_url,
            var_root=root / "data",
            port=port,
            issuer=jwks.issuer,
            jwks_url=jwks.jwks_url,
            ca_file=root / "ca.pem",
        )
        tokens = tokens_for(jwks.issuer, signing, kid)
        log = out.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(b"")
        with production_server(env, log) as proc:
            result["startup_seconds"] = asyncio.run(wait_ready(base, proc, startup_timeout))
            schema = wait_for_database(db_url, timeout=10)
            result["alembic_after_startup"] = schema["alembic_version"]
            observed = asyncio.run(exercise_http(base, tokens))
            result["http"] = observed
            result["first_stop"] = stop_gracefully(proc)
        failures = assert_http(observed, base)
        if schema["alembic_version"] != head:
            failures.append(f"database schema {schema['alembic_version']!r} is not at head {head!r}")
        run_id = observed["run"]["run_id"]
        with production_server(env, log) as proc:
            result["restart_seconds"] = asyncio.run(wait_ready(base, proc, startup_timeout))
            after = asyncio.run(run_status(base, tokens.agent, run_id))
            result["after_restart"] = {
                "run_id": after.get("run_id"),
                "status": after.get("status"),
                "gate": after.get("gate"),
            }
            result["second_stop"] = stop_gracefully(proc)
        if (after.get("status"), after.get("gate")) != ("needs_review", "mapping_review"):
            failures.append(f"run did not persist across restart: {result['after_restart']}")
        result["jwks_requests"] = jwks.requests
        if not jwks.requests:
            failures.append("the server never fetched the JWKS")
        logged = log.read_text(encoding="utf-8", errors="replace")
        if any(secret in logged for secret in tokens.secrets()) or (db_url.password and db_url.password in logged):
            failures.append("a token or the database password appeared in the server log")
        if not (root / "data" / "fixtures").is_dir():
            failures.append("synthetic fixtures were not seeded under the persistent root")
    result["failures"] = failures
    result["passed"] = not failures
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def _git_commit() -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("PORTCO_PRODUCTION_SMOKE_DATABASE_URL"),
        help="disposable TLS PostgreSQL in DATABASE_URL form (or PORTCO_PRODUCTION_SMOKE_DATABASE_URL)",
    )
    parser.add_argument("--port", type=int, default=18080, help="non-default PORT for the entry point")
    parser.add_argument("--out", type=Path, default=REPO / "var" / "production-smoke.json")
    parser.add_argument("--startup-timeout", type=float, default=240)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or PORTCO_PRODUCTION_SMOKE_DATABASE_URL is required")
    if args.port == 8000:
        parser.error("use a non-default port so PORT handling is exercised")
    result = smoke(args.database_url, args.port, args.out, args.startup_timeout)
    for failure in result["failures"]:
        print(f"FAIL: {failure}", file=sys.stderr)
    if result["passed"]:
        print(f"PASS: production entry point smoke; evidence saved to {args.out}")
        return 0
    print(f"production entry point smoke failed; evidence and server log next to {args.out}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
