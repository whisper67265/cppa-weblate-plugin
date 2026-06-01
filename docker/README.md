<!--
SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# docker/

Shared Docker assets for CI and CD.

- **Dockerfile.weblate-plugin** — Overlay on `weblate/weblate:latest`; installs the plugin via `uv pip install` and copies `settings-override.py`.
- **docker-compose.ci.yml** — PostgreSQL + Redis + Weblate stack for plugin tests and CI.
- **docker-compose.cd.yml** — Weblate-only stack for staging/production (host Postgres, shared Redis).

## Usage

```bash
# CI / plugin tests (from repo root):
docker compose -f docker/docker-compose.ci.yml build
docker compose -f docker/docker-compose.ci.yml up -d

# CD on deploy server (copy .env.example to repo-root .env; set WEBLATE_URL_PREFIX, REDIS_DB, secrets):
cp .env.example .env
docker compose -f docker/docker-compose.cd.yml --env-file .env build
docker compose -f docker/docker-compose.cd.yml --env-file .env up -d
```

Set `WEBLATE_URL_PREFIX=/weblate` when nginx serves the app under `/weblate/`. Use `REDIS_DB=1` when sharing Redis with other stacks.
