#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
# SPDX-License-Identifier: BSL-1.0

# Reusable functions for managing the Weblate Docker Compose stack.
# Source this file from CI/CD scripts.

set -euo pipefail

SCRIPT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose.sh
source "${SCRIPT_LIB_DIR}/compose.sh"

stack_build() {
    compose build "$@"
}

stack_up() {
    compose up -d "$@"
}

stack_wait_healthy() {
    local timeout="${1:-120}"
    local port="${WEBLATE_PORT:-8080}"
    local url="http://localhost:${port}/healthz/"
    local interval=5
    local elapsed=0

    echo "Waiting for Weblate at ${url} (timeout: ${timeout}s)..."
    while [ "$elapsed" -lt "$timeout" ]; do
        if curl -sf "$url" > /dev/null 2>&1; then
            echo "Weblate is healthy (after ${elapsed}s)."
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    echo "ERROR: Weblate did not become healthy in ${timeout}s."
    echo "--- weblate container logs ---"
    compose logs weblate | tail -80
    return 1
}

stack_create_token() {
    local user="${1:-admin}"
    compose exec -T weblate weblate createtoken "$user" | tail -1
}

stack_logs() {
    local file="${1:-}"
    if [ -n "$file" ]; then
        compose logs > "$file" 2>&1 || true
    else
        compose logs
    fi
}

stack_down() {
    compose down -v --remove-orphans 2>/dev/null || true
}
