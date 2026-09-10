# Docker

Run ankiweb in a container. This covers the Docker-specific setup; see
[README.md](README.md) for everything about the app itself.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (Engine 20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2 plugin, `docker compose`)

## Quickstart

```bash
docker compose up --build -d
```

Then open <http://127.0.0.1:8000>. The AnkiConnect API is on <http://127.0.0.1:8765>
(both bound to `127.0.0.1` only by default — see **LAN access** below to widen that).

## Configuration via `.env`

Copy the example file and edit it:

```bash
cp .env.example .env
```

`.env` is read by `docker-compose.yml` (via `env_file:`, optional — it's fine to skip
this if you don't need to change anything). It supports the same environment variables
as running ankiweb directly (see README.md's [Configuration](README.md#configuration)
table), restricted here to the ones that make sense to change per-deployment without
also editing `docker-compose.yml`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ANKIWEB_PASSWORD` | *(empty → no password)* | If set, the web UI requires this password (a `/login` page sets a session cookie). |
| `ANKIWEB_AC_KEY` | *(none)* | AnkiConnect `apiKey` — required by AnkiConnect clients if set. |
| `ANKIWEB_ALLOWED_HOSTS` | *(empty)* | Comma-separated extra `Host` header values accepted past the DNS-rebinding guard. `*` disables the check (only on a trusted network). |
| `ANKIWEB_LANG` | *(empty → English)* | UI language, an Anki locale code (e.g. `zh-CN`, `ja`, `de`, `fr`). |
| `ANKIWEB_SOURCE_URL` | *(empty)* | AGPL §13 Corresponding-Source location for this deployment — see **License obligations** below. |

`ANKIWEB_HOST`, `ANKIWEB_PORT`, `ANKIWEB_AC_HOST`, `ANKIWEB_AC_PORT`, and
`ANKIWEB_COLLECTION` are **not** listed in `.env.example` on purpose: they're
container-internal. The image already sets sensible defaults for them
(`0.0.0.0` binds and `/data/collection.anki2`) that are tied to the `ports:` mapping
and volume mount in `docker-compose.yml` — changing them via `.env` alone, without
also updating `docker-compose.yml`, would break the container's networking or lose
your collection. To change published ports, edit `docker-compose.yml` directly (see
**LAN access** below).

## Data persistence

Everything ankiweb needs to keep is written under `/data` inside the container, which
is backed by the named Docker volume `ankiweb_data`:

- `collection.anki2` — your actual Anki collection (cards, notes, scheduling state).
- `ankiconnect.json` — optional AnkiConnect config overrides, if you've saved any.
- `notify.json` — [deck push notification](README.md#deck-push-notifications-extras)
  settings, if configured.
- `import-tmp/` — transient staging for uploads during an import; safe to lose.

Nothing else needs to persist. Because it's a named volume (not a bind mount or
container-layer write), it survives `docker compose down` and image rebuilds, and is
managed by Docker separately from your working directory.

**Back up** the volume to a tarball:

```bash
docker run --rm -v ankiweb_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/ankiweb-data.tar.gz -C /data .
```

**Restore** from that tarball into a (fresh or existing) volume:

```bash
docker run --rm -v ankiweb_data:/data -v "$PWD":/backup alpine \
  tar xzf /backup/ankiweb-data.tar.gz -C /data
```

Stop the `ankiweb` container before restoring so nothing is writing to the collection
mid-extract.

## Exposing beyond localhost / LAN access

By default `docker-compose.yml` publishes both ports bound to `127.0.0.1` only
(`"127.0.0.1:8000:8000"` and `"127.0.0.1:8765:8765"`), so the container is reachable
only from the host it runs on. To reach it from another device on your LAN:

1. Edit the `ports:` entries in `docker-compose.yml` — drop the `127.0.0.1:` prefix
   (e.g. `"8000:8000"`) to publish on all of the host's interfaces, or bind to a
   specific LAN interface address instead.
2. Set `ANKIWEB_ALLOWED_HOSTS` in `.env` to the host/IP clients will use, since the web
   app's DNS-rebinding guard only accepts `localhost` by default — this is exactly the
   same setting described in README.md's
   [LAN access](README.md#lan-access) section; that section also covers the equivalent
   non-Docker (`ANKIWEB_HOST=0.0.0.0`) invocation, which the container already does
   internally.

The container itself always binds `ANKIWEB_HOST=0.0.0.0` / `ANKIWEB_AC_HOST=0.0.0.0`
internally (it has to, to be reachable from the host at all) — the `ports:` binding and
`ANKIWEB_ALLOWED_HOSTS` are what actually control who can reach it.

## License obligations (AGPL-3.0-or-later)

ankiweb is licensed under AGPL-3.0-or-later. If you deploy this container somewhere
other users on a network can reach it — not just localhost on your own machine — AGPL
§13 requires you to offer those users the Corresponding Source for the exact version
you're running. The app already has a place for this: the `/about` page shows a
"Source" link driven by `ANKIWEB_SOURCE_URL`. Set it to wherever you're hosting your
source (e.g. a fork's GitHub URL) in `.env`:

```
ANKIWEB_SOURCE_URL=https://github.com/yourname/your-ankiweb-fork
```

Leaving it unset is fine for pure single-user, localhost-only use.

## Production best practices applied

This Dockerfile/compose setup already does the following, so you don't have to think
about it:

- **Multi-stage build** — the Node.js toolchain (frontend build) and Python build
  toolchain never end up in the final image; only the compiled bundle, the installed
  package, and the vendored static assets are copied into the runtime stage.
- **Pinned, non-`latest` base images** — `node:20-bookworm-slim` and
  `python:3.12-slim-bookworm`, not floating `latest` tags.
- **Non-root user** — the process runs as an unprivileged `ankiweb` user (uid/gid 1000),
  not root.
- **Minimal Linux capabilities** — `cap_drop: ["ALL"]` and
  `security_opt: ["no-new-privileges:true"]` in `docker-compose.yml`; the app is a plain
  network server and needs no elevated capabilities.
- **Container `HEALTHCHECK`** — polls `GET /healthz` so `docker compose ps` and
  orchestrators can see whether the app is actually serving, not just that the process
  started.
- **Persistent named volume, not container-layer writes** — collection data lives in
  the `ankiweb_data` volume mounted at `/data`, not scattered in the container's
  writable layer where a `docker compose down` (without `-v`) could still lose track of
  it or an image rebuild could shadow it.
- **Config/secrets via env file, not baked into the image** — `ANKIWEB_PASSWORD`,
  `ANKIWEB_AC_KEY`, etc. are supplied at runtime through `.env` / `env_file:`, never
  written into the image itself, so the image is shareable without leaking secrets and
  configuration changes don't require a rebuild.

## Troubleshooting

- **Check logs:**

  ```bash
  docker compose logs -f ankiweb
  ```

- **Check health status:**

  ```bash
  docker compose ps
  ```

  A healthy container shows `healthy` in the `STATUS` column (backed by the
  `HEALTHCHECK` polling `/healthz`); `starting` right after boot is normal, `unhealthy`
  means the web server on port 8000 isn't responding — check the logs.

- **First run creates an empty collection.** If `ANKIWEB_COLLECTION`
  (`/data/collection.anki2` inside the container) doesn't exist yet, ankiweb creates a
  fresh, empty collection automatically on first startup — this is expected the very
  first time you start the container with a new `ankiweb_data` volume. If you expected
  your existing collection to show up and it didn't, double-check you restored it into
  the volume (see **Data persistence** above) *before* the first `docker compose up`,
  or copy it in and restart the container.
