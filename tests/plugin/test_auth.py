# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""P2 plugin auth tests.

Verifies authentication and authorization behavior across all
Boost endpoint routes:
- Valid token grants access to protected endpoints
- Invalid/missing tokens are rejected
- Unauthenticated endpoints remain accessible without a token
"""

from __future__ import annotations

import pytest

from tests.plugin.lib.http import http_get, http_json

pytestmark = pytest.mark.plugin

_VALID_ADD_OR_UPDATE_BODY = {
    "organization": "test-org",
    "version": "test-1.0.0",
    "add_or_update": {"zh_Hans": ["test-submodule"]},
}

_FAKE_TOKEN = "wlu_this_token_does_not_exist_in_weblate"


class TestBoostEndpointAuth:
    """Authentication and authorization across all Boost endpoint routes."""

    def test_valid_token_on_info(self, api_token: str) -> None:
        code, body = http_get("/boost-endpoint/info/", token=api_token)
        assert code == 200, f"expected 200: {code} {body}"
        assert isinstance(body, dict)
        assert "module" in body

    def test_valid_token_on_add_or_update(self, api_token: str) -> None:
        code, body = http_json(
            "POST",
            "/boost-endpoint/add-or-update/",
            token=api_token,
            body=_VALID_ADD_OR_UPDATE_BODY,
        )
        assert code == 202, f"expected 202: {code} {body}"
        assert isinstance(body, dict)
        assert body.get("status") == "accepted"
        assert body.get("task_id")

    def test_invalid_token_rejected(self) -> None:
        code, _ = http_get("/boost-endpoint/info/", token=_FAKE_TOKEN)
        assert code in (401, 403), f"expected 401/403: {code}"

    def test_no_token_rejected(self) -> None:
        code, _ = http_get("/boost-endpoint/info/")
        assert code in (401, 403), f"expected 401/403: {code}"

    def test_invalid_token_on_add_or_update(self) -> None:
        code, _ = http_json(
            "POST",
            "/boost-endpoint/add-or-update/",
            token=_FAKE_TOKEN,
            body=_VALID_ADD_OR_UPDATE_BODY,
        )
        assert code in (401, 403), f"expected 401/403: {code}"

    def test_no_token_on_add_or_update(self) -> None:
        code, _ = http_json(
            "POST",
            "/boost-endpoint/add-or-update/",
            body=_VALID_ADD_OR_UPDATE_BODY,
        )
        assert code in (401, 403), f"expected 401/403: {code}"

    def test_ping_no_auth_required(self) -> None:
        code, body = http_get("/boost-endpoint/plugin-ping/")
        assert code == 200
        assert body == "ok" or body == b"ok"
