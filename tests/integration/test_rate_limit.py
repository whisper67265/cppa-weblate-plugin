# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Integration tests for Boost endpoint rate limiting."""

from __future__ import annotations

import os
import re

import pytest

from tests.integration.lib.http import http_get_with_headers, http_json_with_headers

pytestmark = pytest.mark.integration

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


class TestBoostEndpointRateLimit:
    """Live-stack rate limit enforcement for Boost endpoint routes."""

    def test_info_returns_429_when_rate_limited(self, api_token: str) -> None:
        rate = os.environ.get("BOOST_ENDPOINT_THROTTLE_INFO", "3/minute")
        limit = _parse_rate_limit(rate)

        last_headers: dict[str, str] = {}
        for _ in range(limit):
            code, _body, headers = http_get_with_headers(
                "/boost-endpoint/info/", token=api_token
            )
            assert code == 200, f"expected 200 before limit: {code}"
            last_headers = headers

        code, _body, headers = http_get_with_headers(
            "/boost-endpoint/info/", token=api_token
        )
        assert code == 429, f"expected 429 after {limit} requests: {code}"
        retry_after = headers.get("Retry-After")
        assert retry_after is not None
        assert int(retry_after) > 0

        if "X-RateLimit-Limit" in last_headers:
            assert int(last_headers["X-RateLimit-Limit"]) == limit

    def test_add_or_update_returns_429_when_rate_limited(self, api_token: str) -> None:
        rate = os.environ.get("BOOST_ENDPOINT_THROTTLE_ADD_OR_UPDATE", "3/hour")
        limit = _parse_rate_limit(rate)

        for _ in range(limit):
            code, _body, _headers = http_json_with_headers(
                "POST",
                "/boost-endpoint/add-or-update/",
                token=api_token,
                body=_VALID_ADD_OR_UPDATE_BODY,
            )
            assert code == 202, f"expected 202 before limit: {code}"

        code, _body, headers = http_json_with_headers(
            "POST",
            "/boost-endpoint/add-or-update/",
            token=api_token,
            body=_VALID_ADD_OR_UPDATE_BODY,
        )
        assert code == 429, f"expected 429 after {limit} requests: {code}"
        retry_after = headers.get("Retry-After")
        assert retry_after is not None
        assert int(retry_after) > 0
