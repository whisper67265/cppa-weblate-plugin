# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import builtins

import pytest

from boost_weblate.endpoint import apps
from boost_weblate.endpoint.weblate_urls_adapter import register_boost_endpoint_urls


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    register_boost_endpoint_urls.cache_clear()
    yield
    register_boost_endpoint_urls.cache_clear()


def test_register_plugin_urls_delegates_to_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_register() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        apps,
        "register_boost_endpoint_urls",
        fake_register,
    )
    apps.register_plugin_urls()
    assert called is True


def test_register_plugin_urls_skips_when_weblate_urls_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "weblate.urls":
            raise ModuleNotFoundError("weblate.urls")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    apps.register_plugin_urls()
