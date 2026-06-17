# SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Tests for :mod:`boost_weblate.formats.registry`."""

from __future__ import annotations

from typing import ClassVar

import pytest

from boost_weblate.formats.quickbook import QuickBookFormat
from boost_weblate.formats.registry import FormatRegistry, RegisteredFormat, registry

_QBK_WEBLATE_CLASS = "boost_weblate.formats.quickbook.QuickBookFormat"


@pytest.fixture
def isolated_registry() -> FormatRegistry:
    """Fresh registry with QuickBook pre-registered (mirrors production bootstrap)."""
    reg = FormatRegistry()
    reg.register(QuickBookFormat)
    return reg


class MockFormatSpec(RegisteredFormat):
    """Minimal format spec for registry tests."""

    format_id = "mockformat"
    file_patterns = ("*.mock",)
    weblate_class = "boost_weblate.formats.mock.MockFormat"


class DuplicateMockFormatSpec(RegisteredFormat):
    """Second class claiming the same format_id (should not replace the first)."""

    format_id = "mockformat"
    file_patterns = ("*.mock2",)
    weblate_class = "boost_weblate.formats.mock.MockFormat2"


def test_registry_register_decorator() -> None:
    reg = FormatRegistry()

    @reg.register
    class DecoratedSpec(RegisteredFormat):
        format_id = "decorated"
        file_patterns = ("*.dec",)
        weblate_class = "example.DecoratedFormat"

    assert reg.get_by_id("decorated") is DecoratedSpec


def test_registry_includes_quickbook(isolated_registry: FormatRegistry) -> None:
    ids = {fmt.format_id for fmt in isolated_registry.registered()}
    assert "quickbook" in ids


def test_weblate_class_paths(isolated_registry: FormatRegistry) -> None:
    paths = isolated_registry.weblate_class_paths()
    assert _QBK_WEBLATE_CLASS in paths


def test_match_filename_quickbook(isolated_registry: FormatRegistry) -> None:
    matched = isolated_registry.match_filename("docs/chapter.qbk")
    assert matched is QuickBookFormat


def test_extension_map_quickbook(isolated_registry: FormatRegistry) -> None:
    assert isolated_registry.extension_map()[".qbk"] == "quickbook"


def test_register_mock_format(isolated_registry: FormatRegistry) -> None:
    isolated_registry.register(MockFormatSpec)
    assert isolated_registry.get_by_id("mockformat") is MockFormatSpec
    assert isolated_registry.match_filename("file.mock") is MockFormatSpec
    assert isolated_registry.extension_map()[".mock"] == "mockformat"
    paths = isolated_registry.weblate_class_paths()
    assert "boost_weblate.formats.mock.MockFormat" in paths


def test_duplicate_register_is_idempotent(isolated_registry: FormatRegistry) -> None:
    isolated_registry.register(MockFormatSpec)
    isolated_registry.register(MockFormatSpec)
    assert isolated_registry.get_by_id("mockformat") is MockFormatSpec
    assert isolated_registry.registered().count(MockFormatSpec) == 1


def test_duplicate_format_id_keeps_first(isolated_registry: FormatRegistry) -> None:
    isolated_registry.register(MockFormatSpec)
    isolated_registry.register(DuplicateMockFormatSpec)
    assert isolated_registry.get_by_id("mockformat") is MockFormatSpec


def test_get_by_id_missing(isolated_registry: FormatRegistry) -> None:
    assert isolated_registry.get_by_id("nonexistent") is None


def test_register_validation_missing_format_id() -> None:
    reg = FormatRegistry()

    class BadSpec(RegisteredFormat):
        format_id: ClassVar[str] = ""
        file_patterns = ("*.x",)
        weblate_class = "example.Bad"

    with pytest.raises(ValueError, match="format_id"):
        reg.register(BadSpec)


def test_register_entry_bootstrap() -> None:
    reg = FormatRegistry()
    reg.register_entry(
        format_id="quickbook",
        file_patterns=("*.qbk",),
        weblate_class=_QBK_WEBLATE_CLASS,
    )
    assert reg.weblate_class_paths() == (_QBK_WEBLATE_CLASS,)
    assert reg.extension_map()[".qbk"] == "quickbook"


def test_register_entry_replaced_by_class() -> None:
    reg = FormatRegistry()
    reg.register_entry(
        format_id="quickbook",
        file_patterns=("*.qbk",),
        weblate_class=_QBK_WEBLATE_CLASS,
    )
    reg.register(QuickBookFormat)
    assert reg.get_by_id("quickbook") is QuickBookFormat


def test_module_registry_has_quickbook_entry() -> None:
    assert registry.get_by_id("quickbook") is not None
    assert registry.extension_map()[".qbk"] == "quickbook"
    assert _QBK_WEBLATE_CLASS in registry.weblate_class_paths()


def test_module_registry_has_quickbook_class() -> None:
    from boost_weblate.formats.quickbook import QuickBookFormat as _qb

    assert registry.get_by_id("quickbook") is _qb
