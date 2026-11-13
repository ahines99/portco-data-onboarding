# syntax=docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Multi-stage image serving the MCP server over streamable HTTP (POD-906).
# Base and tool images are pinned to multi-arch index digests (tag kept for readability);
# Dependabot (.github/dependabot.yml) proposes reviewed digest updates.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --extra postgres --no-install-project
COPY src ./src
COPY ontology ./ontology
COPY templates ./templates
COPY migrations ./migrations
COPY alembic.ini ./
COPY fixtures ./fixtures
COPY demo ./demo
RUN uv sync --frozen --no-dev --extra postgres

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
# The runtime never installs packages. Remove the base image's unused global installer,
# including its vendored dependencies; uv has already built the application environment.
RUN python -m pip uninstall -y pip
RUN useradd --create-home --uid 10001 portco
WORKDIR /app
COPY --from=build /app /app
RUN chmod -R go-w /app
# Application code and its environment stay root-owned. Runtime writes belong in /data
# or temporary directories; remove inherited privilege-bearing file permissions.
RUN find / -xdev -type f -perm /6000 -exec chmod a-s {} +
ENV PATH="/app/.venv/bin:$PATH" PORTCO_VAR_ROOT=/data PORT=8000
RUN mkdir -p /data && chown portco:portco /data
USER portco
EXPOSE 8000
# One configurable listening port: PORT drives both the server and its health check, so overriding
# PORT alone cannot produce a server on 8000 and a probe elsewhere. The cloud entry point
# (`python -m src.serve`, see render.yaml) reads the same variable.
HEALTHCHECK --interval=30s --timeout=6s --start-period=20s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/readyz', timeout=5)"
CMD ["sh", "-c", "exec uvicorn src.mcp_server:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
