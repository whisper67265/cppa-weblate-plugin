# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Tests for ``boost_weblate.formats.quickbook.QuickBookFormat``.

Patterns follow Weblate upstream ``ConvertFormatTest`` / ``QuickBookFormatTest``
in ``weblate/formats/tests/test_convert.py`` (temp files, ``storage.save()``,
two-heading round-trip, ``existing_units`` merge, import-existing pair).

Django is configured in ``tests/conftest.py`` (see
``tests/django_qbk_format_settings.py``).

Run manually::

    uv run python tests/formats/test_quickbook.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from weblate.utils.state import STATE_TRANSLATED

if TYPE_CHECKING:
    from weblate.trans.models import Unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FIXTURE = _REPO_ROOT / "tests/fixtures/quickbook_fixture.qbk"

# Same content as Weblate ``weblate/trans/tests/data/cs.qbk`` / ``cs2.qbk``
# (used by upstream ``QuickBookFormatTest``).
_QUICKBOOK_CS = """[article QuickBook]

[h1 Ahoj světe!]

Orangutan has five bananas.

Try Weblate at [@https://demo.weblate.org/ weblate.org]!

Thank you for using Weblate.
"""
_QUICKBOOK_CS2 = """[article QuickBook]

[h1 Ahoj světe!]

Orangutan má pět banánů.

Zkus Weblate na [@https://demo.weblate.org/ weblate.org]!

Díky za používání Weblate.
"""
_EXPECTED_AFTER_EXISTING_UNITS = """[article QuickBook]

[h1 Ahoj světe!]

Orangutan má pět banánů.

Try Weblate at [@https://demo.weblate.org/ weblate.org]!

Thank you for using Weblate.
"""


class _MockExistingUnit:
    """Minimal stand-in for ``weblate.checks.tests.test_checks.MockUnit``."""

    def __init__(self, *, source: str, target: str, context: str = "") -> None:
        self.source = source
        self._target = target
        self.context = context

    def get_source_plurals(self) -> list[str]:
        return [self.source]

    @property
    def target(self) -> str:
        return self._target


@pytest.fixture
def qbk_fixture() -> Path:
    return _DEFAULT_FIXTURE


def _bootstrap_django() -> None:
    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.django_qbk_format_settings"
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    if str(_REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "src"))

    import django
    from django.conf import settings

    if not settings.configured:
        django.setup()


def test_format_metadata() -> None:
    from boost_weblate.formats.quickbook import QuickBookFormat

    assert QuickBookFormat.format_id == "quickbook"
    assert QuickBookFormat.extension() == "qbk"
    assert QuickBookFormat.monolingual is True
    assert "quickbook" in QuickBookFormat.mimetype().lower()


def test_template_load_builds_po_store(qbk_fixture: Path) -> None:
    from boost_weblate.formats.quickbook import QuickBookFormat

    fmt = QuickBookFormat(str(qbk_fixture), template_store=None, is_template=True)
    assert len(fmt.content_units) > 0


def test_save_content_requires_template(qbk_fixture: Path) -> None:
    from boost_weblate.formats.quickbook import QuickBookFormat

    fmt = QuickBookFormat(str(qbk_fixture), template_store=None, is_template=True)
    with pytest.raises(TypeError):
        fmt.save_content(BytesIO())


def test_convert_two_headings_roundtrip(tmp_path: Path) -> None:
    """Mirror ``QuickBookFormatTest.test_convert`` (translate-toolkit path)."""
    from boost_weblate.formats.quickbook import QuickBookFormat

    template_path = tmp_path / "template.qbk"
    translation_path = tmp_path / "translation.qbk"
    template_path.write_text(
        "[heading Hello]\n\n[heading Bye]\n",
        encoding="utf-8",
    )
    translation_path.write_text(
        "[heading Ahoj]\n\n[heading Bye]\n",
        encoding="utf-8",
    )

    storage = QuickBookFormat(
        str(translation_path),
        template_store=QuickBookFormat(
            str(template_path),
            is_template=True,
        ),
    )

    assert len(storage.content_units) == 2
    unit1, unit2 = storage.content_units
    assert unit1.source == "Hello"
    assert unit1.target == "Ahoj"
    assert unit2.source == "Bye"
    assert unit2.target == "Bye"

    unit2.set_target("Nazdar")
    unit2.set_state(STATE_TRANSLATED)
    storage.save()

    assert (
        translation_path.read_text(encoding="utf-8")
        == "[heading Ahoj]\n\n[heading Nazdar]\n"
    )


def test_import_existing_czech_pair(tmp_path: Path) -> None:
    """Mirror ``QuickBookFormatTest.test_import_existing``."""
    from boost_weblate.formats.quickbook import QuickBookFormat

    base = tmp_path / "cs.qbk"
    translated = tmp_path / "cs2.qbk"
    base.write_text(_QUICKBOOK_CS, encoding="utf-8")
    translated.write_text(_QUICKBOOK_CS2, encoding="utf-8")

    storage = QuickBookFormat(
        str(translated),
        template_store=QuickBookFormat(str(base), is_template=True),
    )
    assert storage.all_units[4].target == "Díky za používání Weblate."


def test_existing_units_merge_orangutan(tmp_path: Path) -> None:
    """Mirror ``QuickBookFormatTest.test_existing_units``."""
    from boost_weblate.formats.quickbook import QuickBookFormat

    testfile = tmp_path / "translations.qbk"
    testfile.write_text(_QUICKBOOK_CS, encoding="utf-8")

    storage = QuickBookFormat(
        str(testfile),
        template_store=QuickBookFormat(str(testfile), is_template=True),
        existing_units=cast(
            "list[Unit]",
            [
                _MockExistingUnit(
                    source="Orangutan has five bananas.",
                    target="Orangutan má pět banánů.",
                ),
            ],
        ),
    )
    storage.save()

    assert testfile.read_text(encoding="utf-8") == _EXPECTED_AFTER_EXISTING_UNITS


def main(argv: list[str]) -> int:
    _bootstrap_django()

    fixture = Path(argv[1]).resolve() if len(argv) > 1 else _DEFAULT_FIXTURE
    if not fixture.is_file():
        print(f"error: not a file: {fixture}", file=sys.stderr)
        return 1

    test_format_metadata()
    print("format metadata: OK")

    test_template_load_builds_po_store(fixture)
    print("template load (PO store): OK")

    test_save_content_requires_template(fixture)
    print("save_content TypeError without template: OK")

    with tempfile.TemporaryDirectory(prefix="qbk_fmt_") as d:
        p = Path(d)
        test_convert_two_headings_roundtrip(p)
        print("convert two headings round-trip: OK")
        test_import_existing_czech_pair(p)
        print("import existing (cs/cs2): OK")
        test_existing_units_merge_orangutan(p)
        print("existing_units merge: OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
