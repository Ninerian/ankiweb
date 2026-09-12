# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# frontend: build the JS bootstrap bundle (ankiweb/shell/static/bootstrap.js)
# ---------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY tools/build_shell.mjs tools/build_shell.mjs
COPY shell_src/ shell_src/
RUN npm run build

# ---------------------------------------------------------------------------
# builder: install the Python package into a venv, then vendor Anki web assets
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder
WORKDIR /src
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
COPY pyproject.toml ./
COPY ankiweb/ ankiweb/
RUN pip install --no-cache-dir .

COPY tools/*.py tools/
RUN python tools/fetch_web_assets.py
RUN python tools/fetch_datastar.py

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
COPY --from=builder /src/ankiweb/web_assets /app/ankiweb/web_assets
COPY --from=builder /src/ankiweb/shell/static  /app/ankiweb/shell/static
COPY --from=frontend /src/ankiweb/shell/static /app/ankiweb/shell/static
COPY ankiweb/ /app/ankiweb/

RUN mkdir -p /data && chown -R ankiweb:ankiweb /data /app

USER ankiweb

EXPOSE 8000 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "ankiweb"]
