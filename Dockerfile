# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# frontend: build the shell JS bundle and the Tailwind/daisyUI stylesheet (ankiweb/shell/static/)
# ---------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --fetch-retries=5 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000 --fetch-timeout=600000
COPY tools/build_shell.mjs tools/build_shell.mjs
COPY shell_src/ shell_src/
# Tailwind scans the templates and route modules for class names
COPY ankiweb/ ankiweb/
RUN npm run build

# ---------------------------------------------------------------------------
# builder: install the Python package into a venv, then vendor Anki web assets
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder
WORKDIR /src
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_HTTP_TIMEOUT=300 UV_HTTP_RETRIES=5
COPY pyproject.toml uv.lock ./
COPY ankiweb/ ankiweb/
RUN uv sync --frozen --no-dev --no-editable

COPY tools/*.py tools/
RUN uv run python tools/fetch_web_assets.py
RUN uv run python tools/fetch_datastar.py

# ---------------------------------------------------------------------------
# runtime: minimal image with the venv, vendored assets, and app source
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

RUN groupadd --gid 1000 ankiweb \
  && useradd --uid 1000 --gid ankiweb --no-create-home --shell /usr/sbin/nologin ankiweb

WORKDIR /app

ENV PATH=/opt/venv/bin:$PATH \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  ANKIWEB_HOST=0.0.0.0 \
  ANKIWEB_PORT=8000 \
  ANKIWEB_AC_HOST=0.0.0.0 \
  ANKIWEB_AC_PORT=8765 \
  ANKIWEB_COLLECTION=/data/collection.anki2

COPY --from=builder /opt/venv /opt/venv
COPY ankiweb/ /app/ankiweb/
COPY --from=builder /src/ankiweb/web_assets /app/ankiweb/web_assets
COPY --from=builder /src/ankiweb/shell/static  /app/ankiweb/shell/static
COPY --from=frontend /src/ankiweb/shell/static /app/ankiweb/shell/static
RUN mkdir -p /data && chown -R ankiweb:ankiweb /data /app

USER ankiweb

EXPOSE 8000 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "ankiweb"]
