#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
# SPDX-License-Identifier: BSL-1.0

# Integration functional test entrypoint (P1).
# Builds the stack, waits for health, creates API token, extracts SSH pubkey,
# runs functional tests against a live Weblate instance.

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
stack_wait_healthy "${HEALTH_TIMEOUT:-180}"

echo "=== Creating API token ==="
WEBLATE_API_TOKEN="$(stack_create_token admin)"
export WEBLATE_API_TOKEN
export WEBLATE_LIVE_BASE_URL="${WEBLATE_LIVE_BASE_URL:-http://localhost:${WEBLATE_PORT:-8080}}"
export WEBLATE_COMPOSE_FILE="${COMPOSE_FILE}"
export WEBLATE_COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME}"

echo "=== Extracting Weblate SSH public key ==="
TMP_WEBLATE_SSH_PUBKEY="$(compose exec -T weblate cat /app/data/ssh/id_rsa.pub)"
if [[ -z "${TMP_WEBLATE_SSH_PUBKEY}" ]]; then
    echo "ERROR: Failed to read Weblate SSH public key from container." >&2
    exit 1
fi
export WEBLATE_SSH_PUBKEY="${TMP_WEBLATE_SSH_PUBKEY}"
unset TMP_WEBLATE_SSH_PUBKEY

if [[ -n "${GH_TEST_REPO_TOKEN:-}" ]]; then
    export GH_TEST_REPO_TOKEN
    echo "=== GH_TEST_REPO_TOKEN is set (${#GH_TEST_REPO_TOKEN} chars); GitHub E2E tests enabled ==="
else
    echo "=== GH_TEST_REPO_TOKEN is not set; GitHub E2E/Celery tests will be skipped ==="
fi

echo "=== Running functional tests ==="
uv pip install --quiet --group integration
python -m pytest --confcutdir=tests/integration --override-ini addopts= \
    tests/integration/test_functional.py -v --timeout=300
