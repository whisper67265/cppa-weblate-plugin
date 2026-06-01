# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""P0 integration smoke tests.

Verifies:
- Container boots with plugin installed (no import errors, no AppRegistryNotReady)
- WEBLATE_FORMATS contains QuickBookFormat
- INSTALLED_APPS contains boost_weblate.endpoint
- QuickBook format attributes (format_id, monolingual, autoload)
- Boost endpoint URL registration (plugin-ping, info with/without auth)
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.plugin.lib.http import http_get

pytestmark = pytest.mark.plugin

# ---------------------------------------------------------------------------
# P0: Container boot + plugin load
# ---------------------------------------------------------------------------


class TestContainerBoot:
    """Weblate container starts with plugin installed — no import errors."""

    def test_weblate_healthz(self) -> None:
        code, _ = http_get("/healthz/")
        assert code == 200

    def test_import_boost_weblate(self, exec_python: Callable[[str], str]) -> None:
        output = exec_python("import boost_weblate; print('ok')")
        assert output == "ok"

    def test_weblate_formats_contains_quickbook(
        self, exec_python: Callable[[str], str]
    ) -> None:
        snippet = (
            "from django.conf import settings; "
            "assert 'boost_weblate.formats.quickbook.QuickBookFormat' "
            "in settings.WEBLATE_FORMATS, settings.WEBLATE_FORMATS"
        )
        exec_python(snippet)

    def test_installed_apps_contains_endpoint(
        self, exec_python: Callable[[str], str]
    ) -> None:
        snippet = (
            "from django.conf import settings; "
            "apps = settings.INSTALLED_APPS; "
            "assert any('boost_weblate.endpoint' in a for a in apps), apps"
        )
        exec_python(snippet)


# ---------------------------------------------------------------------------
# P0: QuickBook format registration
# ---------------------------------------------------------------------------


class TestQuickBookFormat:
    """QuickBook format registered with correct attributes."""

    def test_quickbook_format_id(self, exec_python: Callable[[str], str]) -> None:
        snippet = (
            "from boost_weblate.formats.quickbook import QuickBookFormat; "
            "assert QuickBookFormat.format_id == 'quickbook', QuickBookFormat.format_id"
        )
        exec_python(snippet)

    def test_quickbook_format_monolingual(
        self, exec_python: Callable[[str], str]
    ) -> None:
        snippet = (
            "from boost_weblate.formats.quickbook import QuickBookFormat; "
            "assert QuickBookFormat.monolingual is True, QuickBookFormat.monolingual"
        )
        exec_python(snippet)

    def test_quickbook_format_autoload(self, exec_python: Callable[[str], str]) -> None:
        snippet = (
            "from boost_weblate.formats.quickbook import QuickBookFormat; "
            "assert QuickBookFormat.autoload == ('*.qbk',), QuickBookFormat.autoload"
        )
        exec_python(snippet)


# ---------------------------------------------------------------------------
# P0: Boost endpoint URL registration
# ---------------------------------------------------------------------------


class TestBoostEndpointURLs:
    """Boost endpoint routes are accessible via HTTP."""

    def test_plugin_ping_no_auth(self) -> None:
        code, body = http_get("/boost-endpoint/plugin-ping/")
        assert code == 200
        assert body == "ok" or body == b"ok"

    def test_info_with_token(self, api_token: str) -> None:
        code, body = http_get("/boost-endpoint/info/", token=api_token)
        assert code == 200, f"unexpected {code}: {body}"
        assert isinstance(body, dict)
        assert body["module"] == "cppa-weblate-plugin"
        assert "version" in body
        assert "capabilities" in body
        assert isinstance(body["capabilities"], list)

    def test_info_without_auth(self) -> None:
        code, _ = http_get("/boost-endpoint/info/")
        assert code in (401, 403)
