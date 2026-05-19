# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Tests for generated ``settings_override.py``.

Covers the formats tuple and endpoint ``INSTALLED_APPS``.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_QBK = "boost_weblate.formats.quickbook.QuickBookFormat"


def _load_generator_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts/generate_settings_override.py"
    spec = importlib.util.spec_from_file_location("_cppa_gen_settings", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load generator spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _weblate_formats_from_settings_override_source(source: str) -> list[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "WEBLATE_FORMATS":
                return _ast_tuple_of_strings(node.value)
    msg = "WEBLATE_FORMATS assignment not found in settings override source"
    raise AssertionError(msg)


def _weblate_formats_from_repo_settings_override() -> list[str]:
    path = (
        Path(__file__).resolve().parents[1] / "src/boost_weblate/settings_override.py"
    )
    return _weblate_formats_from_settings_override_source(
        path.read_text(encoding="utf-8")
    )


def _ast_tuple_of_strings(node: ast.expr) -> list[str]:
    if not isinstance(node, (ast.Tuple, ast.List)):
        msg = f"expected tuple or list, got {ast.dump(node)}"
        raise AssertionError(msg)
    out: list[str] = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
        else:
            msg = f"unexpected element {ast.dump(elt)}"
            raise AssertionError(msg)
    return out


def test_generated_includes_installed_apps_endpoint_augment() -> None:
    path = (
        Path(__file__).resolve().parents[1] / "src/boost_weblate/settings_override.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "Plugin Django app" in text
    assert "INSTALLED_APPS +=" in text
    assert "boost_weblate.endpoint.apps.BoostEndpointConfig" in text


def test_generated_weblate_formats_includes_upstream_and_quickbook() -> None:
    paths = _weblate_formats_from_repo_settings_override()
    assert len(paths) >= 40
    assert "weblate.formats.ttkit.PoFormat" in paths
    assert "weblate.formats.ttkit.TBXFormat" in paths
    assert paths.count(_QBK) == 1


def test_generator_output_includes_quickbook_once() -> None:
    mod = _load_generator_module()
    paths = _weblate_formats_from_settings_override_source(mod.generate(dry_run=True))
    assert "weblate.formats.ttkit.PoFormat" in paths
    assert paths.count(_QBK) == 1
