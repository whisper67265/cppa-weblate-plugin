<!--
SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# `.github/`

GitHub Actions and CI/CD helpers for this repository.

## Workflows

| File | Role |
|------|------|
| [`workflows/ci.yml`](workflows/ci.yml) | Umbrella **CI** — runs on push/PR to `main` and `develop` |
| [`workflows/cd.yml`](workflows/cd.yml) | **Deploy** — after CI succeeds on `develop` (staging); no `workflow_dispatch` trigger |
| [`workflows/release.yml`](workflows/release.yml) | **Release** — manual `workflow_dispatch` only; tags `main` from `pyproject.toml` (`v<version>`) and creates a GitHub Release with Weblate compatibility metadata |
| [`workflows/ci-lint.yml`](workflows/ci-lint.yml) | Lint and format (prek) |
| [`workflows/ci-test.yml`](workflows/ci-test.yml) | Unit tests and coverage |
| [`workflows/ci-package.yml`](workflows/ci-package.yml) | Build and package checks |
| [`workflows/ci-dependencies.yml`](workflows/ci-dependencies.yml) | Dependency and license audit |
| [`workflows/ci-weblate-pin.yml`](workflows/ci-weblate-pin.yml) | PyPI vs Docker Weblate pin sync check |
| [`workflows/weblate-pin-bump.yml`](workflows/weblate-pin-bump.yml) | Scheduled Weblate pin bump (PyPI + Docker + `uv.lock`) |
| [`workflows/ci-plugin-smoke.yml`](workflows/ci-plugin-smoke.yml) | Plugin smoke (Docker stack) |
| [`workflows/ci-plugin-functional.yml`](workflows/ci-plugin-functional.yml) | Plugin functional tests |
| [`workflows/ci-plugin-auth.yml`](workflows/ci-plugin-auth.yml) | Plugin auth tests |

Callable workflows (`ci-*`, `ci-plugin-*`) are triggered only via `workflow_call` from `ci.yml`, not directly on push.

## Plugin integration jobs

Three callable workflows exercise the live Weblate Docker stack ([`docker/docker-compose.ci.yml`](../docker/docker-compose.ci.yml)). Each job builds the image, runs `compose up -d --wait`, probes `/healthz/` and the Boost ping endpoint, creates an API token (with retry), then runs pytest with `pytest-timeout` and one rerun on failure.

| Job | Workflow | Typical duration | Hard limit (`timeout-minutes`) | Notes |
|-----|----------|------------------|--------------------------------|-------|
| Plugin smoke | [`ci-plugin-smoke.yml`](workflows/ci-plugin-smoke.yml) | ~8–12 min | 15 | Stack image build dominates |
| Plugin functional | [`ci-plugin-functional.yml`](workflows/ci-plugin-functional.yml) | ~15–22 min | 25 | GitHub E2E needs repository secret |
| Plugin auth | [`ci-plugin-auth.yml`](workflows/ci-plugin-auth.yml) | ~8–12 min | 10 | Auth + rate-limit tests |

### Secrets and environment

| Variable | Where | Purpose |
|----------|-------|---------|
| `GH_TEST_REPO_TOKEN` | Repository secret (functional job only) | Classic PAT with `repo` scope for ephemeral GitHub repos in [`tests/plugin/test_functional.py`](../tests/plugin/test_functional.py). If unset, GitHub/Celery E2E tests are skipped. |
| `HEALTH_TIMEOUT` | CI workflow env / shell default | Seconds to wait for `/healthz/` after compose `--wait`. Defaults: smoke/auth **240**, functional **300**. |
| `PYTEST_PLUGIN_OPTS` | Optional override in entrypoint scripts | Default includes `--timeout`, `--timeout-method=thread`, `--reruns 1`, `--reruns-delay 5`. Smoke/auth use `--timeout=120`; functional uses `--timeout=300`. |
| `WEBLATE_PORT` | Optional | Host port for Weblate (default **8080**). |

### Local reproduction

```bash
bash scripts/plugin-smoke.sh
bash scripts/plugin-auth.sh
GH_TEST_REPO_TOKEN=<classic PAT with repo> bash scripts/plugin-functional.sh
```

Skip slow plugin tests during local iteration: add `-m "not slow"` to the pytest invocation in the script, or set `PYTEST_PLUGIN_OPTS` accordingly.

## Other paths

| Path | Role |
|------|------|
| [`ci/apt-install`](ci/apt-install) | Apt packages for Weblate-related CI jobs |

Deploy uses environment **staging** secrets (`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`, `WEBLATE_PORT`, `WEBLATE_URL_PREFIX`) and [`docker/docker-compose.cd.yml`](../docker/docker-compose.cd.yml) on the server at `/opt/cppa-weblate-plugin`.

## Weblate version pinning

Weblate is **not** bumped by Dependabot. A single logical release is pinned in two places:

| Location | Example | Format |
|----------|---------|--------|
| [`pyproject.toml`](../pyproject.toml) | `Weblate[all]==2026.5` | PyPI calver |
| [`docker/Dockerfile.weblate-plugin`](../docker/Dockerfile.weblate-plugin) | `FROM weblate/weblate:2026.5.0.0` | Docker fixed tag `YEAR.MONTH.PATCH.BUILD` |

Mapping lives in [`scripts/weblate-version-map.sh`](../scripts/weblate-version-map.sh). CI runs [`scripts/check-weblate-pin-sync.sh`](../scripts/check-weblate-pin-sync.sh) on every PR. [`weblate-pin-bump.yml`](workflows/weblate-pin-bump.yml) opens a PR weekly (Monday 09:00 UTC) when a newer PyPI release has a matching Docker fixed tag.
