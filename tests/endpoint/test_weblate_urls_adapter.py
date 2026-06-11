# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import builtins
import importlib.metadata
import sys
import types

import pytest
from django.conf import settings
from django.urls import URLResolver

from boost_weblate.endpoint.weblate_urls_adapter import (
    WeblateUrlLayoutError,
    _assert_weblate_url_layout,
    _boost_endpoint_route,
    _route_already_registered,
    _weblate_version,
    register_boost_endpoint_urls,
)


@pytest.fixture(autouse=True)
def _clear_url_registration_cache() -> None:
    register_boost_endpoint_urls.cache_clear()
    yield
    register_boost_endpoint_urls.cache_clear()


def test_weblate_url_layout_error_is_runtime_error() -> None:
    assert issubclass(WeblateUrlLayoutError, RuntimeError)


def test_assert_layout_raises_when_real_patterns_missing() -> None:
    fake = types.ModuleType("weblate.urls")
    with pytest.raises(WeblateUrlLayoutError, match="real_patterns"):
        _assert_weblate_url_layout(fake)


def test_assert_layout_raises_when_real_patterns_not_list() -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = ()
    with pytest.raises(WeblateUrlLayoutError, match="not a list"):
        _assert_weblate_url_layout(fake)


def test_assert_layout_raises_when_weblate_version_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = []
    monkeypatch.setattr(
        "boost_weblate.endpoint.weblate_urls_adapter._weblate_version",
        lambda: "unknown",
    )
    with pytest.raises(WeblateUrlLayoutError, match="version"):
        _assert_weblate_url_layout(fake)


def test_assert_layout_raises_when_weblate_version_too_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = []
    monkeypatch.setattr(
        "boost_weblate.endpoint.weblate_urls_adapter._weblate_version",
        lambda: "2020.1",
    )
    with pytest.raises(WeblateUrlLayoutError, match="below the minimum supported"):
        _assert_weblate_url_layout(fake)


def test_assert_layout_error_includes_weblate_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("weblate.urls")
    monkeypatch.setitem(sys.modules, "weblate.urls", fake)
    weblate_version = importlib.metadata.version("Weblate")
    with pytest.raises(WeblateUrlLayoutError) as exc_info:
        register_boost_endpoint_urls()
    message = str(exc_info.value)
    assert "real_patterns" in message
    assert weblate_version in message


def test_weblate_version_unknown_when_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_not_found(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", raise_not_found)
    assert _weblate_version() == "unknown"


def test_boost_endpoint_route_shape() -> None:
    route = _boost_endpoint_route()
    assert isinstance(route, URLResolver)
    assert str(route.pattern) == "boost-endpoint/"


def test_route_already_registered_detects_existing() -> None:
    patterns: list = [_boost_endpoint_route()]
    assert _route_already_registered(patterns) is True
    assert _route_already_registered([]) is False


def test_register_skips_when_weblate_urls_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "weblate.urls":
            raise ModuleNotFoundError("weblate.urls")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    register_boost_endpoint_urls()


def test_register_appends_boost_endpoint_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = []
    monkeypatch.setitem(sys.modules, "weblate.urls", fake)

    register_boost_endpoint_urls()

    assert len(fake.real_patterns) == 1
    assert str(fake.real_patterns[0].pattern) == "boost-endpoint/"


def test_register_is_idempotent_via_lru_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = []
    monkeypatch.setitem(sys.modules, "weblate.urls", fake)

    register_boost_endpoint_urls()
    register_boost_endpoint_urls()

    assert len(fake.real_patterns) == 1


def test_register_skips_duplicate_after_cache_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = []
    monkeypatch.setitem(sys.modules, "weblate.urls", fake)

    register_boost_endpoint_urls()
    register_boost_endpoint_urls.cache_clear()
    register_boost_endpoint_urls()

    assert len(fake.real_patterns) == 1


@pytest.mark.skipif(
    settings.ROOT_URLCONF != "weblate.urls",
    reason="requires Weblate ROOT_URLCONF (weblate.urls)",
)
def test_plugin_ping_resolves_after_registration() -> None:
    from django.urls import resolve

    register_boost_endpoint_urls()
    match = resolve("/boost-endpoint/plugin-ping/")
    assert match.url_name == "plugin-ping"
    assert match.func.__name__ == "plugin_ping"
