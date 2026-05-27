# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Shared fixtures for integration tests."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest

from tests.integration.lib.docker_exec import (
    docker_exec_python,
    docker_exec_python_json,
)
from tests.integration.lib.http import base_url as _base_url
from tests.integration.lib.http import http_get


@pytest.fixture(scope="session")
def api_token() -> str:
    token = os.environ.get("WEBLATE_API_TOKEN")
    if not token:
        pytest.skip("WEBLATE_API_TOKEN not set")
    return token


@pytest.fixture(scope="session")
def live_base_url() -> str:
    return _base_url()


@pytest.fixture(scope="session")
def authed_get(api_token: str) -> Callable[..., tuple[int, Any]]:  # noqa: E501
    """GET helper pre-bound with the API token."""
    token = api_token

    def _get(path: str, **kwargs: Any) -> tuple[int, Any]:
        return http_get(path, token=token, **kwargs)

    return _get


@pytest.fixture(scope="session")
def exec_python() -> Callable[[str], str]:
    """Execute a Python snippet inside the Weblate container."""
    return docker_exec_python


@pytest.fixture(scope="session")
def exec_python_json() -> Callable[[str], object]:
    """Execute a Python snippet inside the container and parse JSON output."""
    return docker_exec_python_json
