<!--
SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# scripts/

Reusable shell scripts for CI and CD.

- **lib/compose.sh** — Sets `COMPOSE_FILE`, `COMPOSE_PROJECT_NAME`, exports `compose()` wrapper.
- **lib/weblate-stack.sh** — Stack lifecycle functions: `stack_build`, `stack_up`, `stack_wait_healthy`, `stack_create_token`, `stack_logs`, `stack_down`.
- **plugin-smoke.sh** — CI entrypoint for P0 smoke tests (build, start, health-check, test, teardown).
- **plugin-auth.sh** — CI entrypoint for auth and rate-limit tests.
- **plugin-functional.sh** — CI entrypoint for E2E functional tests (optional GitHub repo).

## Usage

```bash
# Run smoke tests locally:
bash scripts/plugin-smoke.sh

# Source the library for custom workflows:
source scripts/lib/weblate-stack.sh
stack_build
stack_up
stack_wait_healthy 240
stack_wait_api_ready
```

CI entrypoints use `compose up -d --wait`, `HEALTH_TIMEOUT` (smoke/auth **240**, functional **300**), `stack_create_token_retry`, and `PYTEST_PLUGIN_OPTS` for pytest timeout/reruns. See [`.github/WORKFLOWS.md`](../.github/WORKFLOWS.md#plugin-integration-jobs).
