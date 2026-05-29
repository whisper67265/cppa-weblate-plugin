<!--
SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# scripts/

Reusable shell scripts for CI and CD.

- **lib/compose.sh** — Sets `COMPOSE_FILE`, `COMPOSE_PROJECT_NAME`, exports `compose()` wrapper.
- **lib/weblate-stack.sh** — Stack lifecycle functions: `stack_build`, `stack_up`, `stack_wait_healthy`, `stack_create_token`, `stack_logs`, `stack_down`.
- **integration-smoke.sh** — CI entrypoint for P0 smoke tests (build, start, health-check, test, teardown).

## Usage

```bash
# Run smoke tests locally:
bash scripts/integration-smoke.sh

# Source the library for custom workflows:
source scripts/lib/weblate-stack.sh
stack_build
stack_up
stack_wait_healthy 120
```
