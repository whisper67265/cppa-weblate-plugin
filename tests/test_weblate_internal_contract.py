# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Verify undocumented Weblate internal APIs the plugin depends on (pin-bump gate)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from django.urls import URLResolver

from boost_weblate.endpoint.weblate_urls_adapter import (
    _assert_weblate_url_layout,
    _boost_endpoint_route,
)
from boost_weblate.settings_override import (
    _parse_formatsconf_formats_ast,
    weblate_formats_with_plugin_formats,
)

_CONTRACT_PREFIX_FORMATSCONF = "Weblate contract broken [FormatsConf.FORMATS AST]:"
_CONTRACT_PREFIX_WEBLATE_FORMATS = "Weblate contract broken [WEBLATE_FORMATS]:"
_CONTRACT_PREFIX_REAL_PATTERNS = "Weblate contract broken [weblate.urls.real_patterns]:"


def _load_weblate_formats_models_source() -> str:
    spec = importlib.util.find_spec("weblate")
    if spec is None or not spec.submodule_search_locations:
        msg = f"{_CONTRACT_PREFIX_FORMATSCONF} Weblate is not installed"
        raise AssertionError(msg)
    path = Path(spec.submodule_search_locations[0]) / "formats" / "models.py"
    return path.read_text(encoding="utf-8")


@pytest.mark.weblate_contract
def test_weblate_contract_formatsconf_ast() -> None:
    try:
        parsed = _parse_formatsconf_formats_ast(_load_weblate_formats_models_source())
    except RuntimeError as exc:
        msg = f"{_CONTRACT_PREFIX_FORMATSCONF} {exc}"
        raise AssertionError(msg) from exc
    if not parsed:
        msg = (
            f"{_CONTRACT_PREFIX_FORMATSCONF} "
            "FormatsConf.FORMATS parsed to an empty sequence"
        )
        raise AssertionError(msg)


@pytest.mark.weblate_contract
def test_weblate_contract_weblate_formats_non_empty() -> None:
    try:
        formats = weblate_formats_with_plugin_formats()
    except RuntimeError as exc:
        msg = f"{_CONTRACT_PREFIX_WEBLATE_FORMATS} {exc}"
        raise AssertionError(msg) from exc
    if not formats:
        msg = (
            f"{_CONTRACT_PREFIX_WEBLATE_FORMATS} "
            "weblate_formats_with_plugin_formats() returned an empty tuple"
        )
        raise AssertionError(msg)
    if not isinstance(formats, tuple):
        msg = (
            f"{_CONTRACT_PREFIX_WEBLATE_FORMATS} "
            f"expected tuple, got {type(formats).__name__}"
        )
        raise AssertionError(msg)


@pytest.mark.weblate_contract
def test_weblate_contract_real_patterns_accepts_resolver() -> None:
    try:
        import weblate.urls as wl_urls
    except ModuleNotFoundError as exc:
        msg = f"{_CONTRACT_PREFIX_REAL_PATTERNS} weblate.urls is not importable: {exc}"
        raise AssertionError(msg) from exc

    try:
        _assert_weblate_url_layout(wl_urls)
    except Exception as exc:
        msg = f"{_CONTRACT_PREFIX_REAL_PATTERNS} {exc}"
        raise AssertionError(msg) from exc

    real_patterns = wl_urls.real_patterns
    if not isinstance(real_patterns, list):
        msg = (
            f"{_CONTRACT_PREFIX_REAL_PATTERNS} "
            f"real_patterns is not a list (got {type(real_patterns).__name__})"
        )
        raise AssertionError(msg)

    route = _boost_endpoint_route()
    if not isinstance(route, URLResolver):
        msg = (
            f"{_CONTRACT_PREFIX_REAL_PATTERNS} "
            f"expected URLResolver from _boost_endpoint_route(), "
            f"got {type(route).__name__}"
        )
        raise AssertionError(msg)

    before_len = len(real_patterns)
    real_patterns.append(route)
    try:
        if len(real_patterns) != before_len + 1:
            msg = (
                f"{_CONTRACT_PREFIX_REAL_PATTERNS} "
                "real_patterns did not accept appended URLResolver"
            )
            raise AssertionError(msg)
        if real_patterns[-1] is not route:
            msg = (
                f"{_CONTRACT_PREFIX_REAL_PATTERNS} "
                "appended URLResolver was not retained at list tail"
            )
            raise AssertionError(msg)
    finally:
        real_patterns.pop()
