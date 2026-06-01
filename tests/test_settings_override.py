# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Tests for ``boost_weblate.settings_override`` (Docker ``exec`` fragment)."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_QBK = "boost_weblate.formats.quickbook.QuickBookFormat"


def _load_weblate_formats_models_source() -> str:
    spec = importlib.util.find_spec("weblate")
    if spec is None or not spec.submodule_search_locations:
        msg = "Weblate is not installed"
        raise AssertionError(msg)
    path = Path(spec.submodule_search_locations[0]) / "formats" / "models.py"
    return path.read_text(encoding="utf-8")


def _parse_formatsconf_formats_ast(models_text: str) -> list[str]:
    tree = ast.parse(models_text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FormatsConf":
            return _formats_assignment_to_strings(node.body)
    msg = "Class FormatsConf not found in weblate formats models source"
    raise AssertionError(msg)


def _formats_assignment_to_strings(class_body: list[ast.stmt]) -> list[str]:
    for node in class_body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "FORMATS":
                return _string_tuple_or_list(node.value)
    msg = "FORMATS assignment not found on FormatsConf"
    raise AssertionError(msg)


def _string_tuple_or_list(node: ast.expr) -> list[str]:
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            else:
                msg = f"Unexpected literal in FormatsConf.FORMATS: {ast.dump(elt)}"
                raise AssertionError(msg)
        return out
    msg = f"Unexpected FormatsConf.FORMATS value: {ast.dump(node)}"
    raise AssertionError(msg)


def test_settings_override_formats_match_ast_parse_of_upstream() -> None:
    from boost_weblate.settings_override import weblate_formats_with_quickbook

    stock = _parse_formatsconf_formats_ast(_load_weblate_formats_models_source())
    got = weblate_formats_with_quickbook()
    assert got[: len(stock)] == tuple(stock)
    assert got[len(stock)] == _QBK
    assert len(got) == len(stock) + 1


def test_settings_override_module_defines_weblate_formats() -> None:
    import boost_weblate.settings_override as so

    assert isinstance(so.WEBLATE_FORMATS, tuple)
    assert so.WEBLATE_FORMATS == so.weblate_formats_with_quickbook()


def test_settings_override_source_has_exec_docker_hints() -> None:
    path = (
        Path(__file__).resolve().parents[1] / "src/boost_weblate/settings_override.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "_ENDPOINT_APP_CONFIG" in text
    assert "boost_weblate.endpoint.apps.BoostEndpointConfig" in text
    assert "AppRegistryNotReady" in text or "formats.models" in text


def test_weblate_formats_includes_upstream_and_quickbook() -> None:
    from boost_weblate.settings_override import weblate_formats_with_quickbook

    paths = list(weblate_formats_with_quickbook())
    assert len(paths) >= 40
    assert "weblate.formats.ttkit.PoFormat" in paths
    assert "weblate.formats.ttkit.TBXFormat" in paths
    assert paths.count(_QBK) == 1


def test_merge_boost_endpoint_throttle_rates_preserves_upstream() -> None:
    from boost_weblate.settings_override import (
        BOOST_ENDPOINT_THROTTLE_RATES,
        merge_boost_endpoint_throttle_rates,
    )

    merged = merge_boost_endpoint_throttle_rates(
        {"DEFAULT_THROTTLE_RATES": {"user": "1/hour", "anon": "100/day"}}
    )
    rates = merged["DEFAULT_THROTTLE_RATES"]
    assert rates["user"] == "1/hour"
    assert rates["anon"] == "100/day"
    assert rates["info"] == BOOST_ENDPOINT_THROTTLE_RATES["info"]
    assert rates["add-or-update"] == BOOST_ENDPOINT_THROTTLE_RATES["add-or-update"]
