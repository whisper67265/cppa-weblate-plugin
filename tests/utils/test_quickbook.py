# SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>
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

from boost_weblate.utils import quickbook as quickbook_mod  # noqa: E402
from boost_weblate.utils.quickbook import (  # noqa: E402
    QuickBookFile,
    QuickBookTranslator,
    QuickBookUnit,
    _find_bracket_end,
    _has_prose,
    _parse_bracket_keyword,
    _parse_qbk,
    _parse_table_inner,
    _Seg,
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


def test_find_bracket_end_triple_quote_and_escape() -> None:
    s = r"[keyword '''still [nested] here''' tail]"
    start = s.index("[")
    end = _find_bracket_end(s, start)
    assert end == len(s) - 1
    esc = r"[show \[literal\] brackets]"
    start_e = esc.index("[")
    assert _find_bracket_end(esc, start_e) == len(esc) - 1


def test_find_bracket_end_unclosed() -> None:
    s = "[never closes"
    assert _find_bracket_end(s, 0) == -1


def test_parse_bracket_keyword_whitespace_after_sigil() -> None:
    kw, off = _parse_bracket_keyword("[@   trailing]")
    assert kw == "@"
    assert off == 5


def test_has_prose_plain_and_macro_only() -> None:
    assert _has_prose("plain words") is True
    assert _has_prose("__only_macro__") is False
    assert _has_prose("__a__, __b__.") is False
    assert _has_prose("text __x__ more") is True


def test_has_prose_empty_after_bracket_stripping() -> None:
    """Bracket pairs collapse to spaces; bare text can become empty after strip."""
    assert _has_prose("[]") is False


def test_parse_table_inner_title_only_single_line() -> None:
    body = "Single line title"
    segs = _parse_table_inner(body, 0, len(body), 1, "table", 0)
    assert len(segs) == 1
    assert segs[0].seg_type == "table-title"


def test_parse_table_inner_skips_bare_line_and_parses_row() -> None:
    body = "T\nnot a row token\n[[a][b]]"
    segs = _parse_table_inner(body, 0, len(body), 1, "table", 0)
    titles = [s for s in segs if s.seg_type == "table-title"]
    cells = [s for s in segs if s.seg_type == "table"]
    assert titles and cells
    assert cells[0].msgid == "a"


def test_parse_table_inner_malformed_row_and_cell_brackets() -> None:
    content = "T\n[[a][b]\n[row [no close]\n[[c][d]]"
    segs = _parse_table_inner(content, 0, len(content), 1, "table", 0)
    assert any(s.msgid == "c" for s in segs)


def test_parse_qbk_section_recursion_depth_cap() -> None:
    inner = "deepest body text"
    for d in range(10, -1, -1):
        inner = f"[section:id{d} T{d}\n{inner}\n]"
    segs = _parse_qbk(inner)
    assert not any("deepest" in s.msgid for s in segs)


def test_parse_qbk_trailing_indented_spaces_without_final_newline() -> None:
    segs = _parse_qbk("alpha\n   ")
    assert any(s.msgid == "alpha" for s in segs)


def test_parse_qbk_leading_triple_quote_block() -> None:
    segs = _parse_qbk("'''raw escape'''\n[h2 heading]\n")
    assert any(s.seg_type == "heading" for s in segs)


def test_parse_qbk_unclosed_bracket_line_skipped_in_block() -> None:
    segs = _parse_qbk("[h2 ok]\n[broken\nstill junk\n")
    assert any(s.msgid == "ok" for s in segs)


def test_parse_qbk_empty_section_body_skipped() -> None:
    assert _parse_qbk("[section\n\n]") == []


def test_parse_qbk_multiline_section_title_and_nested_body() -> None:
    text = "[section:sec1 Title on first line\nBody paragraph in nested scope.\n]\n"
    segs = _parse_qbk(text)
    kinds = {s.seg_type for s in segs}
    assert "section-title" in kinds
    assert "paragraph" in kinds


def test_parse_qbk_multiline_blockquote() -> None:
    text = "[:first line\nsecond line in blockquote\n]"
    segs = _parse_qbk(text)
    assert len(segs) == 1
    assert "first line" in segs[0].msgid and "second line" in segs[0].msgid


def test_parse_qbk_paragraph_stops_at_triple_quote_line() -> None:
    segs = _parse_qbk("line one\n'''starts raw\n")
    assert len(segs) == 1
    assert segs[0].msgid == "line one"


def test_parse_qbk_paragraph_line_with_unclosed_bracket_keyword() -> None:
    text = "before [incomplete\nstill before\n[h2 after]\n"
    segs = _parse_qbk(text)
    joined = " ".join(s.msgid for s in segs if s.seg_type == "paragraph")
    assert "before" in joined and "incomplete" in joined and "still before" in joined


def test_quickbook_unit_notes_and_getid() -> None:
    u = QuickBookUnit("src-id")
    u.setdocpath("qbk:3")
    assert u.getid() == "qbk:3"
    u.setdocpath("")
    assert u.getid() == "src-id"
    u.addnote("one")
    u.addnote("two")
    assert u.getnotes() == "one\ntwo"


def test_quickbook_file_skips_empty_msgid_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = quickbook_mod._parse_qbk

    def combined(txt: str, *a, **k):
        out = list(real(txt, *a, **k))
        out.append(_Seg(0, 1, 1, "paragraph", "", False, "paragraph"))
        return out

    monkeypatch.setattr(quickbook_mod, "_parse_qbk", combined)

    class _F:
        name = "x.qbk"

        def read(self) -> bytes:
            return b"[h2 only]\n"

        def close(self) -> None:
            pass

    store = QuickBookFile(inputfile=_F())
    assert len(store.units) == 1


def test_translator_respects_should_output_store(
    monkeypatch: pytest.MonkeyPatch, path: Path
) -> None:
    monkeypatch.setattr(
        "translate.convert.convert.should_output_store", lambda *_a, **_k: False
    )
    po = pofile()
    translator = QuickBookTranslator(
        inputstore=po, includefuzzy=True, outputthreshold=0.5
    )
    out = BytesIO()

    class _F:
        name = str(path)

        def read(self) -> bytes:
            return path.read_bytes()

        def close(self) -> None:
            pass

    assert translator.translate(_F(), out) is False
    assert out.getvalue() == b""


def test_translator_lookup_untranslated_uses_source() -> None:
    qbk = "[h2 QB_UNIQUE_MSGID]\n"
    po = pofile()
    po.addsourceunit("QB_UNIQUE_MSGID")
    translator = QuickBookTranslator(
        inputstore=po, includefuzzy=True, outputthreshold=None
    )
    out = BytesIO()

    class _F:
        name = "t.qbk"

        def read(self) -> bytes:
            return qbk.encode()

        def close(self) -> None:
            pass

    assert translator.translate(_F(), out) == 1
    assert b"QB_UNIQUE_MSGID" in out.getvalue()


def test_translator_lookup_fuzzy_target_used_when_includefuzzy() -> None:
    qbk = "[h2 FUZZY_HEAD]\n"
    po = pofile()
    u = po.addsourceunit("FUZZY_HEAD")
    u.target = "Titre flou"
    u.markfuzzy(True)
    translator = QuickBookTranslator(
        inputstore=po, includefuzzy=True, outputthreshold=None
    )
    out = BytesIO()

    class _F:
        name = "t.qbk"

        def read(self) -> bytes:
            return qbk.encode()

        def close(self) -> None:
            pass

    assert translator.translate(_F(), out) == 1
    assert b"Titre flou" in out.getvalue()


def test_parse_qbk_paragraph_breaks_on_soft_wrap_space_line() -> None:
    segs = _parse_qbk("first line\n second line looks wrapped")
    assert len(segs) == 1
    assert segs[0].msgid == "first line"


def test_parse_qbk_paragraph_unclosed_bracket_then_para_break() -> None:
    text = "intro\n[note not closed here\n[h2 real]\n"
    segs = _parse_qbk(text)
    assert any(s.seg_type == "heading" and "real" in s.msgid for s in segs)


def test_quickbook_unit_getlocations_roundtrip() -> None:
    u = QuickBookUnit("src")
    assert u.getlocations() == []
    u.addlocation("fixture.qbk:12")
    assert u.getlocations() == ["fixture.qbk:12"]


def test_parse_qbk_unrecognized_bracket_command_skipped() -> None:
    segs = _parse_qbk("[zzzmacro body text]\nPlain after.\n")
    assert not any(s.msgid == "body text" for s in segs)
    assert any("Plain after" in s.msgid for s in segs)


def test_parse_table_inner_cell_bracket_extends_past_row() -> None:
    body = "T\n[[a][b [orphan]\n[[c][d]]"
    segs = _parse_table_inner(body, 0, len(body), 1, "table", 0)
    assert any(s.msgid == "c" for s in segs)


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
