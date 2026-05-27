# docker/

Shared Docker assets for CI and CD.

- **Dockerfile.weblate-plugin** — Overlay on `weblate/weblate:latest`; installs the plugin via `uv pip install` and copies `settings-override.py`.
- **docker-compose.yml** — PostgreSQL + Redis + Weblate stack. Override defaults via `.env` or environment variables.

## Usage

```bash
# From repo root:
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```

Or use the Makefile: `make build && make up`.
