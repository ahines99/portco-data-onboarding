# syntax=docker/dockerfile:1
# Multi-stage image serving the MCP server over streamable HTTP (POD-906).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
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

FROM python:3.12-slim
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
ENV PATH="/app/.venv/bin:$PATH" PORTCO_VAR_ROOT=/data
RUN mkdir -p /data && chown portco:portco /data
USER portco
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/readyz', timeout=3)"
CMD ["uvicorn", "src.mcp_server:app", "--host", "0.0.0.0", "--port", "8000"]
