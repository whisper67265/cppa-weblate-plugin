# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""HTTP helper for integration tests — stdlib only (no requests/httpx)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def base_url() -> str:
    return os.environ.get("WEBLATE_LIVE_BASE_URL", "http://localhost:8080").rstrip("/")


def auth_header(token: str) -> str:
    """Weblate API token auth (see Weblate 5.16 REST API docs)."""
    return f"Token {token}"


def http_json(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    """Perform an HTTP request and return ``(status_code, parsed_json_or_text)``."""
    url = f"{base_url()}{path}"
    headers: dict[str, str] = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = auth_header(token)

    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code: int = resp.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read()
        code = e.code

    if not raw:
        return code, None
    try:
        return code, json.loads(raw.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return code, raw.decode(errors="replace")


def http_get(
    path: str, *, token: str | None = None, timeout: float = 30.0
) -> tuple[int, Any]:
    return http_json("GET", path, token=token, timeout=timeout)
