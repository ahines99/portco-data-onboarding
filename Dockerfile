# syntax=docker/dockerfile:1
# Multi-stage image serving the MCP server over streamable HTTP (POD-906).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra postgres --no-install-project
COPY src ./src
COPY ontology ./ontology
COPY templates ./templates
COPY migrations ./migrations
COPY alembic.ini ./
COPY fixtures ./fixtures
RUN uv sync --frozen --no-dev --extra postgres

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 portco
WORKDIR /app
COPY --from=build --chown=portco:portco /app /app
ENV PATH="/app/.venv/bin:$PATH" PORTCO_VAR_ROOT=/data
RUN mkdir -p /data && chown portco:portco /data
USER portco
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/mcp', timeout=3)" || exit 0
CMD ["uvicorn", "src.mcp_server:app", "--host", "0.0.0.0", "--port", "8000"]
