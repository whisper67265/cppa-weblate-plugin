<!--
SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# Deployment Runbook

Step-by-step guide for deploying `cppa-weblate-plugin` to a staging or production server using the CD Docker Compose stack (`docker/docker-compose.cd.yml`).

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Docker Engine | 24 + with Compose v2 (`docker compose`) |
| Host PostgreSQL | 16 recommended; a dedicated user and database (see [Database setup](#database-setup)) |
| Redis | 7+; shared via the `boost-data-collector_default` external Docker network |
| Reverse proxy | nginx (or equivalent) terminating TLS and proxying to `127.0.0.1:8080` |
| Git checkout | Repository cloned to `/opt/cppa-weblate-plugin` on the deploy server |

## Database Setup

Run once on the host PostgreSQL instance as a superuser:

```sql
CREATE USER weblate_app WITH PASSWORD '<strong-password>';
CREATE DATABASE weblate_db OWNER weblate_app;
```

Ensure `pg_hba.conf` allows connections from the Docker bridge network (`172.17.0.0/16` or your custom subnet) for that user.

## Environment File

Copy `.env.example` to the repo root as `.env` and fill in every value marked `replace-*`:

```bash
cp .env.example .env
```

### Required secrets

| Variable | Purpose |
|----------|---------|
| `POSTGRES_PASSWORD` | Host Postgres password for `weblate_app` |
| `WEBLATE_ADMIN_PASSWORD` | Initial admin account password |

Compose refuses to start if either is unset (enforced by `${VAR:?set in .env}` syntax in `docker-compose.cd.yml`).

### Plugin-specific settings

The plugin itself has **no dedicated env vars**. All wiring happens inside the Docker image at build time:

1. **`settings_override.py`** is copied to `/app/data/settings-override.py` by the Dockerfile. Weblate's Docker entrypoint `exec()`s this file during settings load.
2. **`WEBLATE_FORMATS`** — the override reads upstream `FormatsConf.FORMATS` via regex, appends `boost_weblate.formats.quickbook.QuickBookFormat`, and writes the result back to `WEBLATE_FORMATS`. No env var needed.
3. **`INSTALLED_APPS`** — the override appends `boost_weblate.endpoint.apps.BoostEndpointConfig`. The app's `ready()` hook then registers `/boost-endpoint/` routes on `weblate.urls.real_patterns`.

### Weblate environment variables

Key variables set in the Compose file or `.env` (full reference in `.env.example`):

| Variable | Default | Notes |
|----------|---------|-------|
| `WEBLATE_PORT` | `8080` | Host port bound to `127.0.0.1`; nginx proxies to this |
| `WEBLATE_SITE_DOMAIN` | `weblate.example.com` | Public hostname (no scheme) |
| `WEBLATE_URL_PREFIX` | `/weblate` | Subpath when behind nginx at `https://<host>/weblate/` |
| `WEBLATE_DEBUG` | `0` | Set `1` only for troubleshooting |
| `WEBLATE_ENABLE_HTTPS` | `1` | Required when TLS terminates at nginx |
| `WEBLATE_IP_PROXY_HEADER` | `HTTP_X_FORWARDED_FOR` | Proxy header for real client IP |
| `POSTGRES_HOST` | `host.docker.internal` | Reaches host Postgres via Docker gateway |
| `POSTGRES_USER` | `weblate_app` | Must match the SQL `CREATE USER` above |
| `POSTGRES_DATABASE` | `weblate_db` | Must match `CREATE DATABASE` above |
| `REDIS_HOST` | `redis` | Resolved via the external `bdc_redis` network |
| `REDIS_DB` | `1` | Logical DB to avoid clashing with other apps on shared Redis |
| `CELERY_SINGLE_PROCESS` | `1` | Single Celery worker process; increase for heavier workloads |

## Build and Start

From the repo root on the deploy server:

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env build
docker compose -f docker/docker-compose.cd.yml --env-file .env up -d
```

The Dockerfile builds an overlay image on a **pinned** `weblate/weblate` tag aligned with the PyPI pin in `pyproject.toml`:

| File | Example |
|------|---------|
| `pyproject.toml` | `Weblate[all]==2026.5` |
| `docker/Dockerfile.weblate-plugin` | `FROM weblate/weblate:2026.5.0.0` |

PyPI uses calver (`2026.5`, `2026.6.1`, …). Docker fixed production tags add patch and build components (`2026.5.0.0`, `2026.6.1.0`). CI enforces the mapping via `scripts/check-weblate-pin-sync.sh`. Bumps are proposed by the `Weblate pin bump` GitHub Actions workflow when both registries have the release.

Build steps:

1. Copies `settings_override.py` → `/app/data/settings-override.py`
2. Installs the plugin into `/app/venv` via `uv pip install`

## Health Checks

### Docker-level healthcheck

Defined in `docker-compose.cd.yml`:

```yaml
healthcheck:
  test: [CMD, curl, -sf, "http://localhost:8080${WEBLATE_URL_PREFIX:-}/healthz/"]
  interval: 10s
  timeout: 5s
  retries: 12
  start_period: 60s
```

The `start_period` gives Weblate 60 s to run migrations and boot before Docker begins counting failures. Total grace before marked unhealthy: **60 s + 12 × 10 s = 180 s**.

Check container health:

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env ps
```

### External health poll (CD pipeline)

The `cd.yml` GitHub Actions workflow polls after deploy (reads `WEBLATE_PORT` and `WEBLATE_URL_PREFIX` from `.env`):

```bash
set -a && [ -f .env ] && . ./.env && set +a
WEBLATE_PORT="${WEBLATE_PORT:-8080}"
WEBLATE_URL_PREFIX="${WEBLATE_URL_PREFIX:-}"
for i in $(seq 1 36); do
    curl -sf "http://127.0.0.1:${WEBLATE_PORT}${WEBLATE_URL_PREFIX}/healthz/" && exit 0
    sleep 5
done
```

This gives **180 s** (36 × 5 s) before failing the deploy.

### Plugin-specific ping

The plugin exposes an unauthenticated ping endpoint:

```bash
set -a && [ -f .env ] && . ./.env && set +a
WEBLATE_PORT="${WEBLATE_PORT:-8080}"
WEBLATE_URL_PREFIX="${WEBLATE_URL_PREFIX:-}"
curl -sf "http://127.0.0.1:${WEBLATE_PORT}${WEBLATE_URL_PREFIX}/boost-endpoint/plugin-ping/"
# Expected: 200 ok (text/plain)
```

A `200 ok` response confirms:

- The Weblate container is running
- `BoostEndpointConfig` loaded in `INSTALLED_APPS`
- Plugin URL routes registered on `weblate.urls.real_patterns`

## Post-Deploy Validation

Run these checks after every deploy (automated in CD; manual for first-time setup). Load deploy vars from `.env` first:

```bash
set -a && [ -f .env ] && . ./.env && set +a
WEBLATE_PORT="${WEBLATE_PORT:-8080}"
WEBLATE_URL_PREFIX="${WEBLATE_URL_PREFIX:-}"
```

### 1. Weblate core health

```bash
curl -sf "http://127.0.0.1:${WEBLATE_PORT}${WEBLATE_URL_PREFIX}/healthz/"
```

### 2. Plugin ping

```bash
curl -sf "http://127.0.0.1:${WEBLATE_PORT}${WEBLATE_URL_PREFIX}/boost-endpoint/plugin-ping/"
```

### 3. Plugin info (authenticated)

```bash
curl -sf -H "Authorization: Token <API_TOKEN>" \
  "http://127.0.0.1:${WEBLATE_PORT}${WEBLATE_URL_PREFIX}/boost-endpoint/info/"
```

Expected JSON:

```json
{
  "module": "cppa-weblate-plugin",
  "version": "0.1.0",
  "capabilities": ["info", "add-or-update"]
}
```

### 4. QuickBook format registered

Verify inside the container:

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env \
  exec -T weblate /app/venv/bin/python -c \
  "from django.conf import settings; assert 'boost_weblate.formats.quickbook.QuickBookFormat' in settings.WEBLATE_FORMATS, 'QuickBook not in WEBLATE_FORMATS'"
```

### 5. Celery worker running

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env \
  exec -T weblate /app/venv/bin/celery -A weblate.utils.celery inspect ping
```

## Automated CD Flow

The full pipeline (`cd.yml`) triggers on a successful CI run against `develop`:

1. SSH to the deploy server
2. `git pull origin develop`
3. `docker compose … build && up -d`
4. Poll `${WEBLATE_URL_PREFIX}/healthz/` on `WEBLATE_PORT` for up to 180 s
5. On failure: dump the last 40 lines of container logs and exit non-zero

Concurrency is locked per branch (`cancel-in-progress: false`) so deploys never overlap.

## Release tagging

Standalone GitHub Actions workflow ([`release.yml`](../.github/workflows/release.yml)). Run it only when you want to publish a version tag and GitHub Release.

### When to run

Use **Actions → Release → Run workflow** whenever the current `main` commit should be tagged. Typical cases:

- After you are satisfied with what is on `main` (deploy or not)
- When `pyproject.toml` on `main` already has the intended `version` and Weblate pin

The workflow does not check deploy status or server health.

### What it does

1. Checks out `main` and reads [`pyproject.toml`](../pyproject.toml):
   - Plugin version: `[project].version` (e.g. `1.0.0`)
   - Weblate pin: `Weblate[all]==…` (e.g. `2026.5`)
2. Fails if tag `v<plugin-version>` already exists on `origin` (prevents duplicate releases)
3. Creates annotated tag `v<plugin-version>` on current `main` HEAD and pushes it
4. Creates a GitHub Release with auto-generated notes, title `v<version> (Weblate <pin>)`, and body noting Weblate compatibility

Use the release title and body to verify which Weblate version the tagged tree was built against.

### Prerequisites

- `version` in `pyproject.toml` on `main` must be the release you intend (bump on `develop` and promote, or commit on `main`, before running)
- Tag `v<version>` must not already exist

### Failure modes

| Failure | Likely cause |
|---------|----------------|
| Tag already exists | Re-ran without bumping `version` in `pyproject.toml` |
| Wrong release contents | `main` HEAD did not include the expected `pyproject.toml` |
| `gh release create` failed | Permissions or network; check whether the tag was pushed and finish the release manually on GitHub |

### Important

- Tagging and GitHub Releases **do not deploy** or change servers
- Deleting a GitHub Release **does not roll back** a deploy; reverting production is a separate server/git operation (see deploy sections above)

## Troubleshooting

### Container stays unhealthy

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env logs weblate | tail -80
```

Common causes:

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `AppRegistryNotReady` | Upstream Weblate reformatted `FormatsConf.FORMATS` | Update the `_FORMATS_BLOCK` regex in `settings_override.py` |
| `connection refused` on Postgres | `pg_hba.conf` or firewall blocking Docker bridge | Allow `172.17.0.0/16` in `pg_hba.conf`; reload Postgres |
| `WEBLATE_ADMIN_PASSWORD … set in .env` | `.env` missing or variable unset | Ensure `.env` exists at repo root with both required secrets |
| `${WEBLATE_URL_PREFIX}/healthz/` 404 | `WEBLATE_URL_PREFIX` mismatch | Ensure `.env` has `WEBLATE_URL_PREFIX` matching nginx config |
| Redis connection error | External network missing | Run `docker network create boost-data-collector_default` or start the BDC stack first |

### GitHub SSH host key errors

If Celery tasks fail with "No ED25519 host key is known for github.com":

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env \
  exec -T weblate sh -c \
  'ssh-keyscan -t ed25519,rsa github.com >> /app/data/ssh/known_hosts 2>/dev/null'
```

### Restart without rebuilding

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env restart weblate
```

### Full teardown

```bash
docker compose -f docker/docker-compose.cd.yml --env-file .env down -v --remove-orphans
```
