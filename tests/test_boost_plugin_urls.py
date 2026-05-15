# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import sys
import types

import pytest
from django.test import RequestFactory

from boost_weblate.endpoint.views import plugin_ping


def test_register_plugin_urls_appends_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("weblate.urls")
    fake.real_patterns = []
    fake._cppa_boost_weblate_urls_registered = False
    monkeypatch.setitem(sys.modules, "weblate.urls", fake)

    from boost_weblate.endpoint.apps import register_plugin_urls

    register_plugin_urls()
    register_plugin_urls()

    assert len(fake.real_patterns) == 1


def test_plugin_ping_returns_200() -> None:
    request = RequestFactory().get("/plugin-ping/")
    response = plugin_ping(request)
    assert response.status_code == 200
    assert response.content == b"ok"
