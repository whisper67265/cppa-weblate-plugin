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
| [`workflows/ci-plugin-smoke.yml`](workflows/ci-plugin-smoke.yml) | Plugin smoke (Docker stack) |
| [`workflows/ci-plugin-functional.yml`](workflows/ci-plugin-functional.yml) | Plugin functional tests |
| [`workflows/ci-plugin-auth.yml`](workflows/ci-plugin-auth.yml) | Plugin auth tests |

Callable workflows (`ci-*`, `ci-plugin-*`) are triggered only via `workflow_call` from `ci.yml`, not directly on push.

## Other paths

| Path | Role |
|------|------|
| [`ci/apt-install`](ci/apt-install) | Apt packages for Weblate-related CI jobs |

Deploy uses environment **staging** secrets (`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`, `WEBLATE_PORT`, `WEBLATE_URL_PREFIX`) and [`docker/docker-compose.cd.yml`](../docker/docker-compose.cd.yml) on the server at `/opt/cppa-weblate-plugin`.
