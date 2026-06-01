# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Plugin tests for Boost endpoint rate limiting."""

from __future__ import annotations

import os
import re

import pytest

from tests.plugin.lib.http import http_get_with_headers, http_json_with_headers

pytestmark = pytest.mark.plugin

_VALID_ADD_OR_UPDATE_BODY = {
    "organization": "test-org",
    "version": "test-1.0.0",
    "add_or_update": {"zh_Hans": ["test-submodule"]},
}

_RATE_PATTERN = re.compile(r"^(\d+)/(minute|hour|min|h|day|d)$")


def _parse_rate_limit(rate: str) -> int:
    match = _RATE_PATTERN.match(rate.strip())
    if not match:
        msg = f"unsupported throttle rate format: {rate!r}"
        raise ValueError(msg)
    return int(match.group(1))


_RATE_LIMIT_USER_SNIPPET = """
from weblate.auth.models import User
from rest_framework.authtoken.models import Token
from weblate.utils.token import get_token

u, _ = User.objects.get_or_create(
    username="plugin_ratelimit",
    defaults={"email": "plugin-ratelimit@test.invalid"},
)
Token.objects.filter(user=u).delete()
t = Token.objects.create(user=u, key=get_token("wlu"))
print(t.key)
"""


@pytest.fixture(scope="module")
def rate_limit_api_token() -> str:
    """Dedicated user so auth tests on admin do not consume scoped throttle budget."""
    token = os.environ.get("WEBLATE_RATE_LIMIT_API_TOKEN", "").strip()
    if token:
        return token
    from tests.plugin.lib.docker_exec import docker_exec_python

    return docker_exec_python(_RATE_LIMIT_USER_SNIPPET.strip())


class TestBoostEndpointRateLimit:
    """Live-stack rate limit enforcement for Boost endpoint routes."""

    def test_info_returns_429_when_rate_limited(
        self, rate_limit_api_token: str
    ) -> None:
        rate = os.environ.get("BOOST_ENDPOINT_THROTTLE_INFO", "3/minute")
        limit = _parse_rate_limit(rate)

        last_headers: dict[str, str] = {}
        for _ in range(limit):
            code, _body, headers = http_get_with_headers(
                "/boost-endpoint/info/", token=rate_limit_api_token
            )
            assert code == 200, f"expected 200 before limit: {code}"
            last_headers = headers

        code, _body, headers = http_get_with_headers(
            "/boost-endpoint/info/", token=rate_limit_api_token
        )
        assert code == 429, f"expected 429 after {limit} requests: {code}"
        retry_after = headers.get("Retry-After")
        assert retry_after is not None
        assert int(retry_after) > 0

        if "X-RateLimit-Limit" in last_headers:
            assert int(last_headers["X-RateLimit-Limit"]) == limit

    def test_add_or_update_returns_429_when_rate_limited(
        self, rate_limit_api_token: str
    ) -> None:
        rate = os.environ.get("BOOST_ENDPOINT_THROTTLE_ADD_OR_UPDATE", "3/hour")
        limit = _parse_rate_limit(rate)

        for _ in range(limit):
            code, _body, _headers = http_json_with_headers(
                "POST",
                "/boost-endpoint/add-or-update/",
                token=rate_limit_api_token,
                body=_VALID_ADD_OR_UPDATE_BODY,
            )
            assert code == 202, f"expected 202 before limit: {code}"

        code, _body, headers = http_json_with_headers(
            "POST",
            "/boost-endpoint/add-or-update/",
            token=rate_limit_api_token,
            body=_VALID_ADD_OR_UPDATE_BODY,
        )
        assert code == 429, f"expected 429 after {limit} requests: {code}"
        retry_after = headers.get("Retry-After")
        assert retry_after is not None
        assert int(retry_after) > 0
