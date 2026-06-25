<!--
SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# CI/CD workflows

GitHub Actions and CI/CD helpers for this repository (see [`.github/`](../.github/) for workflow YAML).

## Workflows

| File | Role |
|------|------|
| [`workflows/ci.yml`](workflows/ci.yml) | Umbrella **CI** — runs on push/PR to `main` and `develop` |
| [`workflows/cd.yml`](workflows/cd.yml) | **Deploy** — after CI succeeds on push to `develop` (`staging`) or `main` (`production`); inline SSH script parameterized by branch |
| [`workflows/promote-main.yml`](workflows/promote-main.yml) | **Promote to production** — manual `workflow_dispatch`; ff-only `develop` → `main` via `PROMOTE_PAT` so CI and `cd.yml` run on `main` |
| [`workflows/release.yml`](workflows/release.yml) | **Release** — manual `workflow_dispatch` only; tags `main` from `pyproject.toml` (`v<version>`) and creates a GitHub Release with Weblate compatibility metadata |
| [`workflows/ci-lint.yml`](workflows/ci-lint.yml) | Lint and format (prek) |
| [`workflows/ci-test.yml`](workflows/ci-test.yml) | Unit tests and coverage (Python **3.12**, **3.13**, **3.14** matrix; `fail-fast: false`) |
| [`workflows/ci-benchmark.yml`](workflows/ci-benchmark.yml) | QuickBook parser benchmarks (`pytest-benchmark`; JSON artifact; regression gate vs `.benchmarks/`) |
| [`workflows/ci-package.yml`](workflows/ci-package.yml) | Build and package checks |
| [`workflows/ci-dependencies.yml`](workflows/ci-dependencies.yml) | Dependency and license audit |
| [`workflows/ci-weblate-pin.yml`](workflows/ci-weblate-pin.yml) | **Weblate version sync** — callable from CI; runs [`scripts/check-weblate-pin-sync.sh`](../scripts/check-weblate-pin-sync.sh) so `pyproject.toml` and `Dockerfile.weblate-plugin` pins match |
| [`workflows/weblate-pin-bump.yml`](workflows/weblate-pin-bump.yml) | Scheduled Weblate pin bump (PyPI + Docker + `uv.lock`); runs **upstream contract check** ([`scripts/check-weblate-internal-contract.sh`](../scripts/check-weblate-internal-contract.sh) `--latest`) before bump/PR |
| [`workflows/ci-plugin-smoke.yml`](workflows/ci-plugin-smoke.yml) | Plugin smoke (Docker stack) |
| [`workflows/ci-plugin-functional.yml`](workflows/ci-plugin-functional.yml) | Plugin functional tests |
| [`workflows/ci-plugin-auth.yml`](workflows/ci-plugin-auth.yml) | Plugin auth tests |

Callable workflows (`ci-*`, `ci-plugin-*`) are triggered only via `workflow_call` from `ci.yml`, not directly on push.

## Unit test Python matrix

[`ci-test.yml`](workflows/ci-test.yml) runs pytest and the 90% coverage gate on **`ubuntu-latest`** for each supported CPython release declared in [`pyproject.toml`](../pyproject.toml) classifiers: **3.12**, **3.13**, and **3.14**. `fail-fast: false` keeps other matrix legs running when one version fails. Coverage artifacts are uploaded per matrix leg as `coverage-py<version>-<pr-or-run-id>`.

Lint ([`ci-lint.yml`](workflows/ci-lint.yml)), package ([`ci-package.yml`](workflows/ci-package.yml)), dependencies ([`ci-dependencies.yml`](workflows/ci-dependencies.yml)), and QuickBook benchmarks ([`ci-benchmark.yml`](workflows/ci-benchmark.yml)) still run on a single Python version (currently **3.14**). Plugin Docker jobs ([`ci-plugin-*`](workflows/ci-plugin-smoke.yml)) use **3.12** inside the Weblate image build context.

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

## QuickBook parser benchmarks

[`ci-benchmark.yml`](workflows/ci-benchmark.yml) runs `pytest-benchmark` against synthetic `.qbk` documents (100 KB, 500 KB, 1 MB) in [`tests/utils/test_quickbook.py`](../tests/utils/test_quickbook.py). Results are written to `benchmark-results.json` and uploaded as a workflow artifact. By default the job compares against the committed baseline at [`.benchmarks/Linux-CPython-3.14-64bit/0001_baseline.json`](../.benchmarks/Linux-CPython-3.14-64bit/0001_baseline.json) and fails when mean time regresses beyond the configured threshold.

| Variable | Where | Purpose |
|----------|-------|---------|
| `BENCHMARK_COMPARE_FAIL` | Repository variable / workflow env (default `mean:30%`) | Passed to `pytest --benchmark-compare-fail` |
| `BENCHMARK_COMPARE_ENABLED` | Repository variable / workflow env (default `true`) | Set to `false` to skip comparison (record-only mode) |

**Refresh baseline** after an intentional parser performance change. Capture on **`ubuntu-latest` (GitHub Actions)** — the committed baseline must match CI hardware (local VMs/desktops are often ~2× faster and will cause false regressions). Download the `benchmark-*` artifact from a green run, or on a GitHub-hosted runner:

```bash
uv run --group dev pytest -m benchmark --benchmark-only \
  -k "not peak_memory" \
  --benchmark-save=baseline tests/utils/test_quickbook.py
git add .benchmarks/Linux-CPython-3.14-64bit/0001_baseline.json
```

Peak-memory bounds are checked separately (`test_parse_1mb_peak_memory`); they are not part of the timing baseline compare.

If CI Python version changes, the `.benchmarks/Linux-CPython-*` directory name changes — regenerate and commit the new baseline path (update `.gitignore` exceptions if needed).

## Other paths

| Path | Role |
|------|------|
| [`ci/apt-install`](ci/apt-install) | Apt packages for Weblate-related CI jobs |

### Deploy environments and secrets

[`cd.yml`](workflows/cd.yml) selects the GitHub environment from the CI branch (`workflow_run.head_branch`):

| Environment | CI branch | When deploy runs |
|-------------|-----------|------------------|
| **staging** | `develop` | After a successful CI run on a push to `develop` |
| **production** | `main` | After a successful CI run on a push to `main` (typically following [`promote-main.yml`](workflows/promote-main.yml)) |

Both environments use the **same secret names** (configure different values per host):

| Secret | Purpose |
|--------|---------|
| `SSH_HOST` | Deploy server hostname |
| `SSH_USER` | SSH user |
| `SSH_PRIVATE_KEY` | Private key for deploy |
| `WEBLATE_PORT` | Host port for post-deploy `/healthz/` poll |
| `WEBLATE_URL_PREFIX` | URL prefix for health check (e.g. `/weblate`) |
| `SSH_PORT` | Optional SSH port (default `22`) |

Server path: `/opt/cppa-weblate-plugin` with [`docker/docker-compose.cd.yml`](../docker/docker-compose.cd.yml). Full procedure: [`docs/deployment-runbook.md`](../docs/deployment-runbook.md).

### Production promotion (repository secret)

[`promote-main.yml`](workflows/promote-main.yml) is separate from deploy: it ff-only merges `develop` into `main` and pushes with **`PROMOTE_PAT`** (classic or fine-grained PAT, **Contents: write**). Without a PAT, GitHub does not trigger CI or `cd.yml` on that push. Optional: required reviewers on the **production** environment only.

## Weblate version pinning

Weblate is **not** bumped by Dependabot. A single logical release is pinned in two places:

| Location | Example | Format |
|----------|---------|--------|
| [`pyproject.toml`](../pyproject.toml) | `Weblate[postgres]==2026.5` | PyPI calver |
| [`docker/Dockerfile.weblate-plugin`](../docker/Dockerfile.weblate-plugin) | `FROM weblate/weblate:2026.5.0.0` | Docker fixed tag `YEAR.MONTH.PATCH.BUILD` |

Mapping lives in [`scripts/weblate-version-map.sh`](../scripts/weblate-version-map.sh). CI runs [`scripts/check-weblate-pin-sync.sh`](../scripts/check-weblate-pin-sync.sh) on every PR. [`weblate-pin-bump.yml`](workflows/weblate-pin-bump.yml) opens a PR weekly (Monday 09:00 UTC) when a newer PyPI release has a matching Docker fixed tag.

### Bump PR branch reconciliation

When the bump step changes pins, the **Open pull request** job uses branch `weblate-pin/<pypi-version>` and compares `pyproject.toml`, `docker/Dockerfile.weblate-plugin`, and `uv.lock` against the remote:

| Outcome | Condition | Action |
|---------|-----------|--------|
| Open PR exists | An open PR already targets the bump branch | No-op (exit) |
| Remote branch matches bump files | Remote branch exists and those three files match the local bump | Open PR only (no commit or push) |
| Remote branch stale | Remote branch missing or bump files differ | Commit bump, push (force-with-lease if remote exists), then open PR |
