# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Helper to execute Python snippets inside the running Weblate container."""

from __future__ import annotations

import json
import os
import subprocess


def _compose_cmd() -> list[str]:
    compose_file = os.environ.get(
        "WEBLATE_COMPOSE_FILE",
        "docker/docker-compose.yml",
    )
    project = os.environ.get("WEBLATE_COMPOSE_PROJECT", "cppa-weblate-plugin")
    return ["docker", "compose", "-f", compose_file, "-p", project]


def _weblate_django_preamble() -> str:
    """Weblate format modules need a configured Django app registry."""
    return (
        "import os; "
        'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "weblate.settings_docker"); '
        "import django; "
        "django.setup(); "
    )


def docker_exec_python(snippet: str, *, timeout: float = 30.0) -> str:
    """Run a Python snippet inside the weblate container and return stdout."""
    code = _weblate_django_preamble() + snippet
    cmd = [
        *_compose_cmd(),
        "exec",
        "-T",
        "weblate",
        "/app/venv/bin/python",
        "-c",
        code,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker exec failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result.stdout.strip()


def docker_exec_python_json(snippet: str, *, timeout: float = 30.0) -> object:
    """Run a Python snippet that prints JSON and return the parsed result."""
    raw = docker_exec_python(snippet, timeout=timeout)
    return json.loads(raw)
