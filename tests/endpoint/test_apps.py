# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import builtins
import sys
import types

import pytest

from boost_weblate.endpoint.apps import register_plugin_urls


def test_register_plugin_urls_skips_when_weblate_urls_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "weblate.urls":
            raise ModuleNotFoundError("weblate.urls")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Should not raise; no fake module to inspect.
    register_plugin_urls()


def test_register_plugin_urls_skips_without_real_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("weblate.urls")
    monkeypatch.setitem(sys.modules, "weblate.urls", fake)
    register_plugin_urls()
    assert not hasattr(fake, "real_patterns")


def test_register_plugin_urls_appends_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = []
    monkeypatch.setitem(sys.modules, "weblate.urls", fake)

    register_plugin_urls()
    register_plugin_urls()

    assert len(fake.real_patterns) == 1
