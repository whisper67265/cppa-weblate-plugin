# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Exercise ``boost_weblate.utils.quickbook`` against bundled fixtures.

Run from the repository root::

    uv run python tests/utils/test_quickbook.py

Or with an explicit QuickBook path::

    uv run python tests/utils/test_quickbook.py path/to/file.qbk
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from translate.storage.pypo import pofile  # noqa: E402

from boost_weblate.utils.quickbook import (  # noqa: E402
    QuickBookFile,
    QuickBookTranslator,
    _parse_qbk,
)

DEFAULT_FIXTURE = _REPO_ROOT / "tests/fixtures/quickbook_fixture.qbk"


@pytest.fixture
def path() -> Path:
    return DEFAULT_FIXTURE


def _load_bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_parse_fixture_has_expected_kinds(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    segs = _parse_qbk(text)
    kinds = {s.seg_type for s in segs}
    for expected in (
        "section-title",
        "paragraph",
        "list",
        "heading",
        "blockquote",
        "admonition",
        "table",
        "table-title",
        "variablelist",
        "variablelist-title",
    ):
        assert expected in kinds, (
            f"missing segment kind {expected!r}; got {sorted(kinds)}"
        )


def test_quickbook_file_identity_roundtrip(path: Path) -> None:
    raw = _load_bytes(path)

    class NamedBytes:
        name = str(path)

        def read(self) -> bytes:
            return raw

        def close(self) -> None:
            pass

    store = QuickBookFile(inputfile=NamedBytes())
    assert store.filesrc == raw.decode("utf-8")


def test_quickbook_translator_substitution(path: Path) -> None:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    marker = "Nested section title here"
    assert marker in text

    po = pofile()
    u = po.addsourceunit(marker)
    u.target = "TITRE IMBRIQUE"

    class NamedBytes:
        name = str(path)

        def read(self) -> bytes:
            return raw

        def close(self) -> None:
            pass

    translator = QuickBookTranslator(
        inputstore=po, includefuzzy=True, outputthreshold=None
    )
    out = BytesIO()
    assert translator.translate(NamedBytes(), out) == 1
    result = out.getvalue().decode("utf-8")
    assert "TITRE IMBRIQUE" in result
    assert marker not in result


def main(argv: list[str]) -> int:
    path = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_FIXTURE
    if not path.is_file():
        print(f"error: not a file: {path}", file=sys.stderr)
        return 1

    test_parse_fixture_has_expected_kinds(path)
    print(f"parse kinds: OK ({path.name})")

    test_quickbook_file_identity_roundtrip(path)
    print("QuickBookFile identity round-trip: OK")

    test_quickbook_translator_substitution(path)
    print("QuickBookTranslator substitution: OK")

    class _F:
        name = str(path)

        def read(self) -> bytes:
            return path.read_bytes()

        def close(self) -> None:
            pass

    store = QuickBookFile(inputfile=_F())
    n = len(store.units)
    print(f"extracted units: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
