#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
# SPDX-License-Identifier: BSL-1.0

# Shared compose wrapper sourced by other scripts.
# Sets REPO_ROOT, COMPOSE_FILE, COMPOSE_PROJECT_NAME and exports compose().

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT

COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/docker/docker-compose.ci.yml}"
export COMPOSE_FILE

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-cppa-weblate-plugin}"
export COMPOSE_PROJECT_NAME

compose() {
    docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME" "$@"
}
