# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Execute commands inside the running Weblate Docker container."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

_COMPOSE_FILE = os.environ.get("WEBLATE_COMPOSE_FILE", "docker/docker-compose.yml")
_COMPOSE_PROJECT = os.environ.get("WEBLATE_COMPOSE_PROJECT", "cppa-weblate-plugin")
_PYTHON = "/app/venv/bin/python"


def _compose_cmd(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        _COMPOSE_FILE,
        "-p",
        _COMPOSE_PROJECT,
        *args,
    ]


def docker_exec_python(snippet: str) -> str:
    """Run a Python snippet in the weblate container; return stdout (stripped)."""
    result = subprocess.run(
        _compose_cmd("exec", "-T", "weblate", _PYTHON, "-c", snippet),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = (
            f"docker exec failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        raise RuntimeError(msg)
    return result.stdout.strip()


def docker_exec_python_json(snippet: str) -> Any:
    """Run a Python snippet and parse stdout as JSON."""
    return json.loads(docker_exec_python(snippet))


def docker_exec_read_file(path: str) -> str:
    """Read a file from the weblate container."""
    result = subprocess.run(
        _compose_cmd("exec", "-T", "weblate", "cat", path),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = (
            f"docker exec cat failed (exit {result.returncode}):\n"
            f"stderr: {result.stderr}"
        )
        raise RuntimeError(msg)
    return result.stdout.strip()
