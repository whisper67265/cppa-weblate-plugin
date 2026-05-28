#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
# SPDX-License-Identifier: BSL-1.0

# Integration auth test entrypoint.
# Builds the stack, waits for health, creates a token, runs auth tests.
# On exit (success or failure): collects logs and tears down the stack.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/weblate-stack.sh
source "${SCRIPT_DIR}/lib/weblate-stack.sh"

cleanup() {
    local exit_code=$?
    set +e
    echo "--- Collecting logs ---"
    stack_logs /tmp/compose-logs.txt
    echo "--- Tearing down stack ---"
    stack_down
    exit "$exit_code"
}
trap cleanup EXIT

echo "=== Building stack ==="
stack_build

echo "=== Starting stack ==="
stack_up

echo "=== Waiting for Weblate ==="
stack_wait_healthy "${HEALTH_TIMEOUT:-120}"

echo "=== Creating API token ==="
WEBLATE_API_TOKEN="$(stack_create_token admin)"
export WEBLATE_API_TOKEN
export WEBLATE_LIVE_BASE_URL="${WEBLATE_LIVE_BASE_URL:-http://localhost:${WEBLATE_PORT:-8080}}"
export WEBLATE_COMPOSE_FILE="${COMPOSE_FILE}"
export WEBLATE_COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME}"

echo "=== Running auth tests ==="
pip install --quiet pytest
python -m pytest --confcutdir=tests/integration --override-ini addopts= \
    tests/integration/test_auth.py -v
