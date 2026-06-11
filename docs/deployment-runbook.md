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
| Redis | 7+; shared via external Docker network (`REDIS_EXTERNAL_NETWORK` in `.env`, required at `compose up`) |
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

Copy `.env.example` to the repo root as `.env` and fill in every value marked `replace-*` (including SMTP and GitHub credentials), and replace all `example.com` placeholders with your real hostname:

```bash
cp .env.example .env
```

Before the first deploy or any production upgrade, complete the [Pre-Deploy Checklist](#pre-deploy-checklist).

### Required secrets

| Variable | Purpose |
|----------|---------|
| `POSTGRES_PASSWORD` | Host Postgres password for `weblate_app` |
| `WEBLATE_ADMIN_PASSWORD` | Initial admin account password |

Compose refuses to start if either is unset (enforced by `${VAR:?set in .env}` in `docker-compose.cd.yml` `environment:`).

### Production integration (`.env` only; fill before go-live)

Weblate does not fail `compose up` if these are missing, but production needs them for real use:

| Variable | Purpose |
|----------|---------|
| `WEBLATE_EMAIL_HOST`, `WEBLATE_EMAIL_HOST_USER`, `WEBLATE_EMAIL_HOST_PASSWORD` | Outbound mail (notifications, password reset). Use dummy `WEBLATE_EMAIL_BACKEND` only on staging without SMTP |
| `WEBLATE_GITHUB_USERNAME`, `WEBLATE_GITHUB_TOKEN` | GitHub API and git operations; **required** for `POST /boost-endpoint/add-or-update/` Celery tasks (clone/push) |

Rotate `WEBLATE_EMAIL_HOST_PASSWORD` and `WEBLATE_GITHUB_TOKEN` per the [Pre-Deploy Checklist](#pre-deploy-checklist).

### Compose vs `.env`

Docker Compose loads operator config from `env_file: ../.env`. The `environment:` block in `docker-compose.cd.yml` only sets:

| Source | Variables | Purpose |
|--------|-----------|---------|
| **`environment:` fail-fast** | `POSTGRES_PASSWORD`, `WEBLATE_ADMIN_PASSWORD` | Refuse `compose up` if secrets are missing |
| **`environment:` pins** | `POSTGRES_HOST`, `POSTGRES_PORT`, `REDIS_HOST`, `REDIS_PORT` | CD topology; overrides `.env` for these keys |
| **`env_file` only** | All other keys in `.env.example` | Weblate, mail, GitHub, plugin throttles, `CELERY_SINGLE_PROCESS`, etc. |
| **Compose-only (`.env`, not in container)** | `REDIS_EXTERNAL_NETWORK` | External network name Weblate joins (`:?` at compose up; must match `docker network ls` after BDC starts) |

Do not duplicate pass-through vars in `environment:`; configure them once in `.env`. Set `REDIS_EXTERNAL_NETWORK` to the network that hosts Redis; only `REDIS_DB` tunes Redis logic inside the shared instance.

### Plugin-specific settings

Build-time wiring (no env vars):

1. **`settings_override.py`** is copied to `/app/data/settings-override.py` by the Dockerfile. Weblate's Docker entrypoint `exec()`s this file during settings load.
2. **`WEBLATE_FORMATS`** — the override reads upstream `FormatsConf.FORMATS` via AST parse of `models.py`, appends `boost_weblate.formats.quickbook.QuickBookFormat`, and writes the result back to `WEBLATE_FORMATS`. No env var needed.
3. **`INSTALLED_APPS`** — the override appends `boost_weblate.endpoint.apps.BoostEndpointConfig`. The app's `ready()` hook then registers `/boost-endpoint/` routes on `weblate.urls.real_patterns`.

Runtime plugin env vars (set in `.env`, read by `settings_override.py` at boot):

| Variable | Production default | Notes |
|----------|-------------------|-------|
| `BOOST_ENDPOINT_THROTTLE_INFO` | `60/minute` | Scoped rate for `GET /boost-endpoint/info/` |
| `BOOST_ENDPOINT_THROTTLE_ADD_OR_UPDATE` | `10/hour` | Scoped rate for `POST /boost-endpoint/add-or-update/` |

### Weblate environment variables

Key variables (full reference in `.env.example`):

| Variable | Default | Set via | Notes |
|----------|---------|---------|-------|
| `WEBLATE_PORT` | `8080` | `.env` (compose interpolation) | Host port bound to `127.0.0.1`; nginx proxies to this |
| `REDIS_EXTERNAL_NETWORK` | — | `.env` (compose `:?`) | **Required.** External Docker network for shared Redis (set to your BDC network name) |
| `WEBLATE_SITE_DOMAIN` | — | `.env` | **Required.** Public hostname (no scheme); must match `WEBLATE_ALLOWED_HOSTS` |
| `WEBLATE_URL_PREFIX` | `/weblate` | `.env` | Subpath when behind nginx at `https://<host>/weblate/` |
| `WEBLATE_DEBUG` | `0` | `.env` | Set `1` only for troubleshooting |
| `WEBLATE_ENABLE_HTTPS` | `1` | `.env` | Required when TLS terminates at nginx |
| `WEBLATE_IP_PROXY_HEADER` | `HTTP_X_FORWARDED_FOR` | `.env` | Proxy header for real client IP |
| `POSTGRES_HOST` | `host.docker.internal` | **Compose pin** | Not operator-configurable in CD |
| `POSTGRES_PORT` | `5432` | **Compose pin** (`:-5432`) | Override in `.env` only if host Postgres uses a non-default port |
| `POSTGRES_USER` | `weblate_app` | `.env` | Must match the SQL `CREATE USER` above |
| `POSTGRES_DATABASE` | `weblate_db` | `.env` | Must match `CREATE DATABASE` above |
| `REDIS_HOST` | `redis` | **Compose pin** | Service name on external `bdc_redis` network |
| `REDIS_PORT` | `6379` | **Compose pin** (`:-6379`) | Not operator-configurable in CD unless compose default changed |
| `REDIS_DB` | `1` | `.env` | Logical DB to avoid clashing with other apps on shared Redis |
| `CELERY_SINGLE_PROCESS` | `1` | `.env` | Weblate Celery worker process count; increase when tasks queue |
| `BOOST_ENDPOINT_THROTTLE_INFO` | `60/minute` | `.env` | Plugin rate limit (see above) |
| `BOOST_ENDPOINT_THROTTLE_ADD_OR_UPDATE` | `10/hour` | `.env` | Plugin rate limit (see above) |
| `WEBLATE_EMAIL_HOST` | `smtp.example.com` | `.env` | SMTP server; set user/password for production |
| `WEBLATE_GITHUB_USERNAME` | — | `.env` | GitHub account for VCS; required with token for add-or-update |
| `WEBLATE_GITHUB_TOKEN` | — | `.env` | GitHub PAT (`repo` scope); rotate via pre-deploy checklist |

## Pre-Deploy Checklist

Run before every production deploy or major upgrade. Copy into a change ticket if your process requires it.

### Shared Redis network

- [ ] Docker network from `REDIS_EXTERNAL_NETWORK` exists (`docker network inspect "$REDIS_EXTERNAL_NETWORK"` after sourcing `.env`)
- [ ] Redis is reachable on that network (boost-data-collector stack running, or equivalent `redis` service attached to the same network name)
- [ ] `REDIS_DB=1` in `.env` (default in `.env.example`) so Weblate does not clash with other apps on shared Redis

### Secret rotation

Review on a schedule or before upgrades:

- [ ] `POSTGRES_PASSWORD` — rotate in Postgres (`ALTER USER weblate_app WITH PASSWORD '…'`) **and** in `.env`; restart stack. Updating `.env` alone is not enough.
- [ ] `WEBLATE_ADMIN_PASSWORD` — update `.env` only for initial admin provisioning; existing admins change password in the Weblate UI
- [ ] `WEBLATE_GITHUB_TOKEN` — rotate PAT in GitHub; update `.env`; restart so Celery clone/push tasks pick it up
- [ ] `WEBLATE_EMAIL_HOST_PASSWORD` — rotate SMTP credential; update `.env`; restart
- [ ] Weblate API tokens — rotate per-user tokens in the Weblate admin UI (not stored in `.env`)

### Backup verification

CD uses **host PostgreSQL** (`weblate_db`); there is no Postgres volume in `docker-compose.cd.yml`.

- [ ] Confirm a recent `pg_dump` (or org backup job) of `weblate_db` exists and is restorable
- [ ] Optional spot-check: verify backup artifact timestamp/size, or `pg_dump -h localhost -U weblate_app weblate_db` succeeds
- [ ] Note: container `/app/data` (SSH keys, `known_hosts`) is not bind-mounted in CD — if Git operations fail after rollback, see [GitHub SSH host key errors](#github-ssh-host-key-errors)

### Rollback readiness

- [ ] Record current SHA before deploy: `git rev-parse HEAD` (or note last known-good release tag `v<version>` from [`release.yml`](../.github/workflows/release.yml))
- [ ] Know the rollback command (also in [Rollback (production or staging)](#rollback-production-or-staging)):
  ```bash
  cd /opt/cppa-weblate-plugin
  git fetch origin
  git checkout <previous-tag-or-sha>
  docker compose -f docker/docker-compose.cd.yml --env-file .env build
  docker compose -f docker/docker-compose.cd.yml --env-file .env up -d
  ```
- [ ] Plan to re-run [Post-Deploy Validation](#post-deploy-validation) after rollback
- [ ] GitHub Release tags do **not** auto-deploy; rollback is server-side git + compose only

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

Deploy is handled by [`cd.yml`](../.github/workflows/cd.yml) after a successful **CI** run on a **push** to `develop` or `main`. The GitHub environment (`staging` or `production`) and git branch on the server follow the CI branch.

| Branch | Trigger | GitHub environment | Server branch |
|--------|---------|-------------------|---------------|
| `develop` | Push to `develop` → CI → `cd.yml` | `staging` | `develop` |
| `main` | Promote (below) → CI on `main` → `cd.yml` | `production` | `main` |

Each deploy job:

1. SSH to the deploy server (`/opt/cppa-weblate-plugin`)
2. `git fetch` / `checkout` / `pull` the CI branch
3. `docker compose -f docker/docker-compose.cd.yml --env-file .env build && up -d`
4. Poll `${WEBLATE_URL_PREFIX}/healthz/` on `WEBLATE_PORT` for up to 180 s
5. On failure: dump the last 40 lines of container logs and exit non-zero

Concurrency is locked per branch (`cancel-in-progress: false`) so staging and production deploys do not overlap on the same branch group.

### Staging (`develop`)

Merge or push to `develop`. When CI succeeds, `cd.yml` deploys using **staging** environment secrets.

### Production (`main`)

1. Validate on staging (`develop` CI + deploy).
2. Ensure `main` can fast-forward to `develop` (`main` is an ancestor of `develop`, or equal).
3. Run **Actions → Promote develop to main** ([`promote-main.yml`](../.github/workflows/promote-main.yml)).
4. The workflow ff-only merges `origin/develop` into `main` and pushes with **`PROMOTE_PAT`** (repository secret).
5. That push runs CI on `main`; when CI succeeds, `cd.yml` deploys using **production** environment secrets.

#### Why `PROMOTE_PAT` is required

`promote-main.yml` is started with `workflow_dispatch`, but the push to `main` must use a **PAT**, not the default `GITHUB_TOKEN`. GitHub does not run `push`-triggered workflows (including CI and `cd.yml`’s `workflow_run`) for commits pushed with `GITHUB_TOKEN`.

Configure a classic or fine-grained PAT with **Contents: write** on this repository and store it as the **`PROMOTE_PAT`** repository secret.

#### Fast-forward failure

If `main` has diverged from `develop`, `git merge --ff-only` fails. Resolve locally (rebase or reset `main` to match your release policy), then re-run the promote workflow.

### GitHub environments and secrets

| Environment | Used when | Secrets (same names per environment) |
|-------------|-----------|-------------------------------------|
| `staging` | CI on `develop` | `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`, `WEBLATE_PORT`, `WEBLATE_URL_PREFIX`; optional `SSH_PORT` |
| `production` | CI on `main` | Same names; production host values |

Optional: enable required reviewers on the `production` environment.

### Rollback (production or staging)

On the deploy server:

```bash
cd /opt/cppa-weblate-plugin
git fetch origin
git checkout <previous-tag-or-sha>
docker compose -f docker/docker-compose.cd.yml --env-file .env build
docker compose -f docker/docker-compose.cd.yml --env-file .env up -d
# Re-run health poll from "External health poll" above
```

Reverting the server does not automatically move `main` or `develop` on GitHub; fix branch tips separately if needed.

### CD failure modes

| Failure | Likely cause |
|---------|----------------|
| Deploy skipped after promote | `PROMOTE_PAT` missing or push used `GITHUB_TOKEN`; CI on `main` never ran |
| FF-only merge failed | `main` diverged from `develop` |
| Health check timeout | Weblate boot/migrations, Postgres, Redis, or URL prefix mismatch |
| Wrong environment deployed | CI ran on unexpected branch; check workflow run `head_branch` |

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
| `AppRegistryNotReady` | Upstream Weblate restructured `FormatsConf.FORMATS` | Update the AST helpers in `settings_override.py` |
| `connection refused` on Postgres | `pg_hba.conf` or firewall blocking Docker bridge | Allow `172.17.0.0/16` in `pg_hba.conf`; reload Postgres |
| `WEBLATE_ADMIN_PASSWORD … set in .env` | `.env` missing or variable unset | Ensure `.env` exists at repo root with both required secrets |
| `${WEBLATE_URL_PREFIX}/healthz/` 404 | `WEBLATE_URL_PREFIX` mismatch | Ensure `.env` has `WEBLATE_URL_PREFIX` matching nginx config |
| Redis connection error | External network missing | Start the BDC stack, or `docker network create "$REDIS_EXTERNAL_NETWORK"` (value from `.env`) |

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
