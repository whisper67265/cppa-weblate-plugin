# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Tests for clone URL validation (SSRF mitigation)."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from boost_weblate.endpoint.validators import (
    github_https_clone_url,
    github_ssh_repo_url,
    validate_clone_url,
    validate_repo_segment,
)

_PUBLIC_IP = "8.8.8.8"
_PRIVATE_IPS = ("10.0.0.1", "172.16.0.1", "192.168.1.1", "127.0.0.1", "169.254.169.254")


def _mock_getaddrinfo_public(*_args, **_kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (_PUBLIC_IP, 0),
        )
    ]


def _mock_getaddrinfo_ip(ip: str):
    def _getaddrinfo(*_args, **_kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (ip, 0),
            )
        ]

    return _getaddrinfo


def _mock_getaddrinfo_rebind(*_args, **_kwargs):
    calls = {"n": 0}

    def _getaddrinfo(*_a, **_kw):
        calls["n"] += 1
        ip = _PUBLIC_IP if calls["n"] == 1 else "10.0.0.1"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (ip, 0),
            )
        ]

    return _getaddrinfo


class TestValidateRepoSegment:
    @pytest.mark.parametrize(
        "name",
        ["CppDigest", "json", "my-lib", "foo.bar", "Boost_1_90"],
    )
    def test_accepts_safe_segments(self, name: str) -> None:
        assert validate_repo_segment(name, field="submodule") == name

    @pytest.mark.parametrize(
        "name",
        ["", "../evil", "foo/bar", "user@host", "foo:bar", "foo bar", "foo%bar"],
    )
    def test_rejects_unsafe_segments(self, name: str) -> None:
        with pytest.raises(ValidationError):
            validate_repo_segment(name, field="organization")


class TestValidateCloneUrlBadScheme:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/repo.git",
            "gopher://example.com/repo.git",
            "http://github.com/boostorg/json.git",
            "ssh://git@github.com/boostorg/json.git",
        ],
    )
    def test_rejects_non_https_schemes(self, url: str) -> None:
        with pytest.raises(ValidationError):
            validate_clone_url(url)


class TestValidateCloneUrlPrivateIp:
    @pytest.mark.parametrize("ip", _PRIVATE_IPS)
    def test_rejects_private_resolved_ips(self, ip: str) -> None:
        url = "https://github.com/boostorg/json.git"
        with (
            patch(
                "boost_weblate.endpoint.validators.socket.getaddrinfo",
                side_effect=_mock_getaddrinfo_ip(ip),
            ),
            pytest.raises(ValidationError),
        ):
            validate_clone_url(url)

    @pytest.mark.parametrize("ip", _PRIVATE_IPS)
    def test_rejects_literal_private_host(self, ip: str) -> None:
        url = f"https://{ip}/repo.git"
        with pytest.raises(ValidationError):
            validate_clone_url(url)


class TestValidateCloneUrlAllowlist:
    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_rejects_non_allowlisted_host(self) -> None:
        url = "https://evil.com/org/repo.git"
        with (
            patch(
                "boost_weblate.endpoint.validators.socket.getaddrinfo",
                side_effect=_mock_getaddrinfo_public,
            ),
            pytest.raises(ValidationError, match="ALLOWED_CLONE_HOSTS"),
        ):
            validate_clone_url(url)

    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_accepts_allowlisted_host(self) -> None:
        url = "https://github.com/boostorg/json.git"
        with patch(
            "boost_weblate.endpoint.validators.socket.getaddrinfo",
            side_effect=_mock_getaddrinfo_public,
        ):
            assert validate_clone_url(url) == url

    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_accepts_subdomain_of_allowlisted_host(self) -> None:
        url = "https://api.github.com/org/repo.git"
        with patch(
            "boost_weblate.endpoint.validators.socket.getaddrinfo",
            side_effect=_mock_getaddrinfo_public,
        ):
            assert validate_clone_url(url) == url

    @override_settings(ALLOWED_CLONE_HOSTS=[])
    def test_empty_allowlist_skips_host_check(self) -> None:
        url = "https://example.com/org/repo.git"
        with patch(
            "boost_weblate.endpoint.validators.socket.getaddrinfo",
            side_effect=_mock_getaddrinfo_public,
        ):
            assert validate_clone_url(url) == url


class TestValidateCloneUrlDnsRebinding:
    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_rejects_changed_addresses_between_lookups(self) -> None:
        url = "https://github.com/boostorg/json.git"
        with (
            patch(
                "boost_weblate.endpoint.validators.socket.getaddrinfo",
                side_effect=_mock_getaddrinfo_rebind(),
            ),
            pytest.raises(ValidationError, match="rebinding"),
        ):
            validate_clone_url(url)


class TestValidateCloneUrlHappyPath:
    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_https_github_url(self) -> None:
        url = "https://github.com/boostorg/json.git"
        with patch(
            "boost_weblate.endpoint.validators.socket.getaddrinfo",
            side_effect=_mock_getaddrinfo_public,
        ):
            assert validate_clone_url(url) == url

    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_scp_ssh_url_normalized(self) -> None:
        scp = "git@github.com:boostorg/json.git"
        with patch(
            "boost_weblate.endpoint.validators.socket.getaddrinfo",
            side_effect=_mock_getaddrinfo_public,
        ):
            assert validate_clone_url(scp) == "https://github.com/boostorg/json.git"


class TestGithubUrlBuilders:
    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_github_https_clone_url(self) -> None:
        with patch(
            "boost_weblate.endpoint.validators.socket.getaddrinfo",
            side_effect=_mock_getaddrinfo_public,
        ):
            url = github_https_clone_url("boostorg", "json")
        assert url == "https://github.com/boostorg/json.git"

    @override_settings(ALLOWED_CLONE_HOSTS=["github.com"])
    def test_github_ssh_repo_url(self) -> None:
        with patch(
            "boost_weblate.endpoint.validators.socket.getaddrinfo",
            side_effect=_mock_getaddrinfo_public,
        ):
            url = github_ssh_repo_url("boostorg", "json")
        assert url == "git@github.com:boostorg/json.git"

    def test_builders_reject_bad_segments(self) -> None:
        with pytest.raises(ValidationError):
            github_https_clone_url("bad/org", "json")
