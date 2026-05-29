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

stack_ensure_github_known_hosts() {
    # Weblate git uses GIT_SSH with UserKnownHostsFile=/app/data/ssh/known_hosts
    # and StrictHostKeyChecking=yes. Celery/component sync over git@github.com fails
    # with "No ED25519 host key is known for github.com" unless this is seeded.
    echo "Ensuring github.com host keys in Weblate known_hosts..."
    compose exec -T weblate sh -c '
        set -e
        kh=/app/data/ssh/known_hosts
        touch "$kh"
        if ! grep -q "^github.com " "$kh" 2>/dev/null; then
            ssh-keyscan -t ed25519,rsa github.com >> "$kh" 2>/dev/null || true
        fi
        if ! grep -q "^github.com " "$kh"; then
            echo "ERROR: failed to add github.com to $kh" >&2
            exit 1
        fi
    '
}

stack_create_token() {
    local user="${1:-admin}"
    # Use python -c (not `weblate shell`) so stdout is only the key
    compose exec -T -e "WEBLATE_CI_USERNAME=${user}" weblate \
        /app/venv/bin/python -c \
        'import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "weblate.settings_docker")
import django
django.setup()
from weblate.auth.models import User
from rest_framework.authtoken.models import Token
from weblate.utils.token import get_token
u = User.objects.get(username=os.environ["WEBLATE_CI_USERNAME"])
Token.objects.filter(user=u).delete()
t = Token.objects.create(user=u, key=get_token("wlp" if u.is_bot else "wlu"))
print(t.key)'
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
