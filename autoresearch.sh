#!/usr/bin/env bash
set -euo pipefail

# autoresearch canonical benchmark harness
# Starts ankiweb on a seeded collection from ~/Downloads/Klett_Green_Line_1__2.apkg,
# runs the Playwright UX crawler across all screens, and outputs METRIC lines.

HARNESS_DIR="/tmp/ankiweb_autoresearch_$$"
COLLECTION_PATH="${HARNESS_DIR}/collection.anki2"
APKG_PATH="${HOME}/Downloads/Klett_Green_Line_1__2.apkg"
PORT=8019
AC_PORT=8769

cleanup() {
  if [ -n "${SERVER_PID:-}" ] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  rm -rf "${HARNESS_DIR}"
}
trap cleanup EXIT

mkdir -p "${HARNESS_DIR}"

# 1. Seed collection deterministically from apkg
uv run python tools/harness_seed.py "${APKG_PATH}" "${COLLECTION_PATH}" >/dev/null 2>&1

# 2. Launch ankiweb server in background
ANKIWEB_COLLECTION="${COLLECTION_PATH}" \
ANKIWEB_PORT="${PORT}" \
ANKIWEB_AC_PORT="${AC_PORT}" \
uv run python -m ankiweb >"${HARNESS_DIR}/server.log" 2>&1 &
SERVER_PID=$!

# 3. Wait for server readiness
READY=0
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.2
done

if [ "${READY}" -ne 1 ]; then
  echo "Server failed to start within timeout" >&2
  cat "${HARNESS_DIR}/server.log" >&2
  exit 1
fi

# 4. Run the Playwright crawler to audit navigation and measure UX issues
uv run python tools/harness_crawler.py "http://127.0.0.1:${PORT}"
