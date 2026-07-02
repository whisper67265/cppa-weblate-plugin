# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""URL validation for git clone operations (SSRF mitigation)."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError

MAX_SEGMENT_LEN = 256
MAX_ADD_OR_UPDATE_LANGS = 50
MAX_SUBMODULES_PER_LANG = 100

_REPO_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_LANGUAGE_CODE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# SCP-style SSH: git@host:path/to/repo.git
_SCP_SSH_RE = re.compile(r"^git@([^:/]+):(.+)$")


def _check_segment_length(name: str, *, field: str) -> None:
    if len(name) > MAX_SEGMENT_LEN:
        raise ValidationError(
            f"{field}: exceeds maximum length of {MAX_SEGMENT_LEN} characters"
        )


def validate_repo_segment(name: str, *, field: str) -> str:
    """Restrict organization/submodule to safe GitHub path segments."""
    if not name or not name.strip():
        raise ValidationError(f"{field}: must be a non-empty string")
    _check_segment_length(name, field=field)
    if not _REPO_SEGMENT_RE.fullmatch(name):
        raise ValidationError(
            f"{field}: invalid characters in {name!r}; "
            "allowed: letters, digits, '.', '_', '-'"
        )
    return name


def validate_language_code(code: str) -> str:
    """Restrict language codes to safe Weblate-style identifiers."""
    if not code or not code.strip():
        raise ValidationError("language: must be a non-empty string")
    _check_segment_length(code, field="language")
    if not _LANGUAGE_CODE_RE.fullmatch(code):
        raise ValidationError(
            f"language: invalid characters in {code!r}; "
            "allowed: letters, digits, '_', '-'"
        )
    return code


def _normalize_clone_url(url: str) -> str:
    """Convert SCP-style SSH URLs to HTTPS for validation; reject other forms."""
    url = url.strip()
    if not url:
        raise ValidationError("Clone URL must not be empty")

    scp_match = _SCP_SSH_RE.match(url)
    if scp_match:
        host, path = scp_match.groups()
        path = path.lstrip("/")
        return f"https://{host}/{path}"

    parsed = urlparse(url)
    if parsed.scheme in ("", "file") or url.startswith("/"):
        raise ValidationError(
            f"Unsupported clone URL scheme: {parsed.scheme or 'local path'!r}"
        )
    if parsed.scheme == "ssh":
        raise ValidationError("Unsupported clone URL scheme: 'ssh'")
    if parsed.scheme not in ("https",):
        raise ValidationError(f"Unsupported clone URL scheme: {parsed.scheme!r}")

    return url


def _hostname_allowed(hostname: str, allowed_hosts: list[str]) -> bool:
    hostname = hostname.rstrip(".").lower()
    for allowed in allowed_hosts:
        allowed = allowed.rstrip(".").lower()
        if hostname == allowed or hostname.endswith(f".{allowed}"):
            return True
    return False


def _resolve_addresses(
    hostname: str,
) -> frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(
            hostname, None, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise ValidationError(
            f"Could not resolve clone URL host {hostname!r}: {exc}"
        ) from exc

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        try:
            addresses.add(ipaddress.ip_address(ip_str))
        except ValueError:
            continue

    if not addresses:
        raise ValidationError(f"Could not resolve clone URL host {hostname!r}")

    return frozenset(addresses)


def _reject_unsafe_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if addr.is_unspecified:
        raise ValidationError(f"Clone URL resolves to unspecified IP address: {addr}")
    if addr.is_private:
        raise ValidationError(f"Clone URL resolves to private IP address: {addr}")
    if addr.is_loopback:
        raise ValidationError(f"Clone URL resolves to loopback IP address: {addr}")
    if addr.is_link_local:
        raise ValidationError(f"Clone URL resolves to link-local IP address: {addr}")
    if addr.is_reserved:
        raise ValidationError(f"Clone URL resolves to reserved IP address: {addr}")
    if addr.is_multicast:
        raise ValidationError(f"Clone URL resolves to multicast IP address: {addr}")


def _check_literal_host_ip(hostname: str) -> None:
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return
    _reject_unsafe_ip(addr)


def validate_clone_url(url: str) -> str:
    """Validate a git clone URL before any subprocess or VCS operation.

    Resolves the hostname twice and rejects if the address set changes (DNS
    rebinding mitigation). Git still performs its own resolution; this narrows
    the rebind window without cloning to a raw IP (which would break TLS/SNI).
    """
    normalized = _normalize_clone_url(url)
    parsed = urlparse(normalized)

    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("Clone URL must include a hostname")

    _check_literal_host_ip(hostname)

    allowed_hosts: list[str] = getattr(settings, "ALLOWED_CLONE_HOSTS", [])
    if allowed_hosts and not _hostname_allowed(hostname, allowed_hosts):
        raise ValidationError(
            f"Clone URL host {hostname!r} is not in ALLOWED_CLONE_HOSTS"
        )

    first_addresses = _resolve_addresses(hostname)
    for addr in first_addresses:
        _reject_unsafe_ip(addr)

    second_addresses = _resolve_addresses(hostname)
    if second_addresses != first_addresses:
        raise ValidationError(
            "Clone URL host address changed between DNS lookups (possible rebinding)"
        )

    return normalized


def github_https_clone_url(organization: str, submodule: str) -> str:
    """Build and validate an HTTPS GitHub clone URL."""
    org = validate_repo_segment(organization, field="organization")
    repo = validate_repo_segment(submodule, field="submodule")
    url = f"https://github.com/{org}/{repo}.git"
    return validate_clone_url(url)


def github_ssh_repo_url(organization: str, submodule: str) -> str:
    """Build and validate an SCP-style GitHub SSH repo URL."""
    org = validate_repo_segment(organization, field="organization")
    repo = validate_repo_segment(submodule, field="submodule")
    url = f"git@github.com:{org}/{repo}.git"
    validate_clone_url(url)
    return url
