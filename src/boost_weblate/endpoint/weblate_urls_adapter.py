# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Adapter for registering Boost endpoint routes on Weblate's URL pattern list."""

from __future__ import annotations

import importlib.metadata
import logging
from functools import lru_cache
from types import ModuleType

from django.urls import URLResolver, include, path
from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)

_MIN_WEBLATE_VERSION = Version("2026.5")
_BOOST_ENDPOINT_PREFIX = "boost-endpoint/"


class WeblateUrlLayoutError(RuntimeError):
    """Raised when ``weblate.urls`` lacks the layout this plugin expects."""


def _weblate_version() -> str:
    try:
        return importlib.metadata.version("Weblate")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _assert_weblate_url_layout(wl_urls: ModuleType) -> None:
    """Verify Weblate exposes the ``real_patterns`` list before mutation."""
    version = _weblate_version()
    if not hasattr(wl_urls, "real_patterns"):
        msg = (
            "weblate.urls.real_patterns is missing; "
            f"Weblate {version} URL layout is incompatible with cppa-weblate-plugin"
        )
        raise WeblateUrlLayoutError(msg)
    if not isinstance(wl_urls.real_patterns, list):
        msg = (
            "weblate.urls.real_patterns is not a list; "
            f"Weblate {version} URL layout is incompatible with cppa-weblate-plugin"
        )
        raise WeblateUrlLayoutError(msg)
    if version == "unknown":
        msg = (
            "Weblate package version could not be determined; "
            "cppa-weblate-plugin cannot verify minimum version compatibility"
        )
        raise WeblateUrlLayoutError(msg)
    try:
        parsed = Version(version)
    except InvalidVersion as exc:
        msg = (
            f"Weblate version string {version!r} could not be parsed; "
            "cppa-weblate-plugin cannot verify minimum version compatibility"
        )
        raise WeblateUrlLayoutError(msg) from exc
    if parsed < _MIN_WEBLATE_VERSION:
        msg = (
            f"Weblate {version} is below the minimum supported version "
            f"{_MIN_WEBLATE_VERSION}; cppa-weblate-plugin requires Weblate "
            f"{_MIN_WEBLATE_VERSION} or newer"
        )
        raise WeblateUrlLayoutError(msg)


def _boost_endpoint_route() -> URLResolver:
    return path(
        _BOOST_ENDPOINT_PREFIX,
        include(("boost_weblate.endpoint.urls", "boost_endpoint")),
    )


def _route_already_registered(real_patterns: list) -> bool:
    return any(
        str(getattr(entry, "pattern", "")) == _BOOST_ENDPOINT_PREFIX
        for entry in real_patterns
    )


@lru_cache(maxsize=1)
def register_boost_endpoint_urls() -> None:
    """Append Boost endpoint routes to ``weblate.urls.real_patterns`` once.

    Weblate builds ``urlpatterns`` from module-level ``real_patterns``. Appending
    before the ``URL_PREFIX`` wrapper keeps routes under prefix configuration.

    Idempotent via ``lru_cache``; safe to call from ``AppConfig.ready()``.

    Note: if ``weblate.urls`` is not importable at call time, the no-op result
    is still cached; retrying after the module becomes importable requires an
    explicit ``register_boost_endpoint_urls.cache_clear()`` call.
    """
    try:
        import weblate.urls as wl_urls  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        logger.debug(
            "boost_weblate.endpoint: skipping URL registration (import error: %s)",
            exc,
        )
        return

    _assert_weblate_url_layout(wl_urls)

    if _route_already_registered(wl_urls.real_patterns):
        return

    wl_urls.real_patterns.append(_boost_endpoint_route())
