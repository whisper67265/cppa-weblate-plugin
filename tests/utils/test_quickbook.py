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

import functools
import os
import sys
import tracemalloc
from io import BytesIO
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Needed for standalone execution (python tests/utils/test_quickbook.py);
# pytest picks this up via conftest.pytest_configure instead.
sys.path.insert(0, str(_REPO_ROOT / "src"))

from translate.storage.pypo import pofile  # noqa: E402

from boost_weblate.utils import quickbook as quickbook_mod  # noqa: E402
from boost_weblate.utils.quickbook import (  # noqa: E402
    _ADMONITION_KEYWORDS,
    _HEADING_KEYWORDS,
    QuickBookFile,
    QuickBookTranslator,
    QuickBookUnit,
    _apply_translations,
    _clean_cell_text,
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


def test_parse_qbk_inline_url_followed_by_prose_on_same_line() -> None:
    segs = _parse_qbk("[@https://example.com/page HEAD 请求] 方法表示客户端。\n")
    assert len(segs) == 1
    assert segs[0].seg_type == "paragraph"
    assert segs[0].msgid == "[@https://example.com/page HEAD 请求] 方法表示客户端。"

    segs = _parse_qbk("[@https://example.com x] prose.\n")
    assert len(segs) == 1
    assert segs[0].msgid == "[@https://example.com x] prose."

    assert _parse_qbk("[@https://example.com x]\n") == []


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


# ---------------------------------------------------------------------------
# Hypothesis fuzz strategies and property tests
# ---------------------------------------------------------------------------

_UNICODE_EDGE_CHARS = (
    "\u200f\u202b\u202c"  # RTL marks
    "\u200d\u200c"  # ZWJ / ZWNJ
    "\u0301"  # combining acute
    "\U0001f600"  # emoji
)

_qbk_safe_line = st.text(
    alphabet=st.characters(codec="utf-8", blacklist_categories=("Cs",)),
    min_size=0,
    max_size=40,
)

qbk_arbitrary = st.text(min_size=0, max_size=1024)

qbk_unicode_edge = st.text(
    alphabet=st.characters(codec="utf-8", blacklist_categories=("Cs",))
    | st.sampled_from(list(_UNICODE_EDGE_CHARS)),
    min_size=0,
    max_size=512,
)


@st.composite
def _qbk_structured_leaf(draw: st.DrawFn) -> str:
    text = draw(_qbk_safe_line)
    kind = draw(
        st.sampled_from(
            ["plain", "heading", "template", "raw", "code", "list", "table"]
        )
    )
    if kind == "plain":
        return (text or "prose") + "\n"
    if kind == "heading":
        kw = draw(st.sampled_from(sorted(_HEADING_KEYWORDS)))
        return f"[{kw} {text or 'Title'}]\n"
    if kind == "template":
        return f"[template {text or 'a'} {text or 'b'}]\n"
    if kind == "raw":
        return f"'''{text or 'raw'}'''\n"
    if kind == "code":
        return "    " + (text or "code") + "\n"
    if kind == "list":
        marker = draw(st.sampled_from(["*", "#"]))
        return f"{marker} {text or 'item'}\n"
    return f"[table\n{(text or 'Title')}\n[[a][{text or 'cell'}]]]\n"


qbk_structured = st.recursive(
    _qbk_structured_leaf(),
    lambda children: st.one_of(
        st.builds(
            lambda body, title: f"[section {title}\n{body}]\n",
            children,
            _qbk_safe_line,
        ),
        st.builds(
            lambda body, kw: f"[{kw} {body}]\n",
            children,
            st.sampled_from(sorted(_ADMONITION_KEYWORDS)),
        ),
        st.builds(lambda a, b: a + b, children, children),
    ),
    max_leaves=20,
)

_qbk_fuzz_inputs = qbk_arbitrary | qbk_structured | qbk_unicode_edge


def _assert_segment_offsets(data: str, segs: list[_Seg]) -> None:
    for seg in segs:
        assert 0 <= seg.text_start <= seg.text_end <= len(data)
        if seg.msgid:
            raw = data[seg.text_start : seg.text_end]
            assert raw.strip(), "non-empty msgid must map to non-whitespace span"
            if seg.no_wrap:
                if seg.seg_type in {"table", "variablelist"}:
                    assert _clean_cell_text(raw) == seg.msgid
                else:
                    assert seg.msgid == raw.strip()
            elif seg.msgid:
                # msgid normalises soft-wrapped lines; at minimum every word in msgid
                # must appear in the raw span.
                assert all(word in raw for word in seg.msgid.split()), (
                    f"paragraph msgid word not found in span: {seg.msgid!r} vs {raw!r}"
                )


@pytest.mark.fuzz
@given(data=_qbk_fuzz_inputs)
def test_parse_qbk_fuzz_properties(data: str) -> None:
    """Parser safety, offset invariants, identity round-trip, and bounded output."""
    segs = _parse_qbk(data)
    if data.startswith("["):
        _find_bracket_end(data, 0)

    assert len(segs) <= len(data)
    _assert_segment_offsets(data, segs)

    result = _apply_translations(data, lambda s: s)
    assert result == data

    store = QuickBookFile()
    store.parse(data)
    assert store.filesrc == data


@pytest.mark.fuzz
def test_fuzz_corpus_empty_input() -> None:
    assert _parse_qbk("") == []
    assert _apply_translations("", lambda s: s) == ""


@pytest.mark.fuzz
def test_fuzz_corpus_unclosed_brackets() -> None:
    data = "[" * 5000
    _parse_qbk(data)
    assert _apply_translations(data, lambda s: s) == data


@pytest.mark.fuzz
def test_fuzz_corpus_section_depth_beyond_cap() -> None:
    data = "[section " + "[nested\n" * 15 + "body\n" * 15
    _parse_qbk(data)
    assert _apply_translations(data, lambda s: s) == data


@pytest.mark.fuzz
def test_fuzz_corpus_rtl_wrapped_heading() -> None:
    data = "\u200f[h2 Title\u200f]\n"
    segs = _parse_qbk(data)
    assert segs
    assert _apply_translations(data, lambda s: s) == data


@pytest.mark.fuzz
def test_fuzz_corpus_invalid_utf8_raises_decode_error() -> None:
    store = QuickBookFile()
    with pytest.raises(UnicodeDecodeError):
        store.parse(b"\xff\xfe")


@pytest.mark.fuzz
def test_fuzz_corpus_long_line() -> None:
    data = "x" * 16384 + "\n"
    assert _apply_translations(data, lambda s: s) == data


@pytest.mark.fuzz
def test_fuzz_corpus_large_input() -> None:
    data = "[section title\n" + "paragraph line.\n" * 4000 + "]\n"
    _parse_qbk(data)
    assert _apply_translations(data, lambda s: s) == data


# --- Benchmarks ---

_SIZE_TOLERANCE = 0.02
# Set after first CI measurement (2x observed peak on ubuntu-latest / Python 3.14).
_PEAK_MEMORY_LIMIT_BYTES = int(
    os.environ.get("QBK_PEAK_MEMORY_LIMIT_BYTES", 12 * 1024 * 1024)
)


def _synthetic_block(n: int) -> str:
    return f"""[template api_{n} [link beast.ref.boost__beast__http__message `message`]]

[section:sec_{n} Section title {n}]

Opening paragraph with [@https://example.com/doc/rfc{n} RFC-style link] and
[link beast.ref.boost__beast__http__request `request`] in prose.

[h2 Section headings and lists]

* First bullet names [link beast.ref.boost__beast__http__response `response`].
* Second bullet continues with plain prose.

[#anchor_{n}]

[heading:custom_{n} Custom heading with id]

[:This is a single-line blockquote for translation.]

[note
Multi-line admonition body for section {n}.
A second paragraph inside the same note uses
[@https://tools.ietf.org/html/rfc6455 WebSocket] markup.
]

[section:nested_{n} Nested section title here]

Inner section prose explains that `template` parameters accept any
[link beast.ref.boost__beast__http__fields `fields`] type meeting requirements.

    // Indented code block (non-translatable).
    // template<class Body, class Fields>
    // class message;

After the code block, prose resumes with a dollar image that is skipped:
[$beast/images/message.png [width 100px] [height 50px]]

[funcref boost::beast::http::message Reference to message type]

[endsect]

[table Message patterns {n}
[[Name][Description]]
[[
    __message__
][
    ```
    /// Class template overview
    template<class Body, class Fields>
    class message;
    ```
]]
[[
    [link beast.ref.boost__beast__http__request `request`]
][
    ```
    /// HTTP request alias
    template<class Body, class Fields = fields>
    using request = message<true, Body, Fields>;
    ```
]]
[[Plain prose cell][
    This cell has human-readable text only, without a code fence.
]]
]

[variablelist FAQ-style entries {n}
[[
    "Does section {n} include a variablelist?"
][
    Yes. This pair mimics patterns from the FAQ chapter.

    Second paragraph in the same answer cell.
]]
]

[warning This is a one-line warning about edge cases in section {n}.]

[endsect]
"""


@functools.lru_cache(maxsize=8)
def generate_synthetic_qbk(target_bytes: int) -> str:
    if target_bytes <= 0:
        raise ValueError("target_bytes must be positive")
    low = int(target_bytes * (1 - _SIZE_TOLERANCE))
    high = int(target_bytes * (1 + _SIZE_TOLERANCE))
    header = "[quickbook 1.7]\n\n"
    header_len = len(header.encode("utf-8"))
    block_size = len(_synthetic_block(0).encode("utf-8"))
    num_blocks = max(1, (target_bytes - header_len) // block_size)
    filler = "[/ sizing filler]\n"
    filler_size = len(filler.encode("utf-8"))

    while num_blocks >= 1:
        parts = [header]
        for i in range(num_blocks):
            parts.append(_synthetic_block(i))
        actual = len("".join(parts).encode("utf-8"))
        while actual < low:
            parts.append(filler)
            actual += filler_size
        text = "".join(parts)
        actual = len(text.encode("utf-8"))
        if actual <= high:
            return text
        num_blocks -= 1

    raise RuntimeError(
        f"could not generate synthetic qbk within "
        f"±{_SIZE_TOLERANCE:.0%} of {target_bytes}"
    )


def _assert_synthetic_qbk_valid(text: str, target_bytes: int) -> list[_Seg]:
    actual = len(text.encode("utf-8"))
    low = int(target_bytes * (1 - _SIZE_TOLERANCE))
    high = int(target_bytes * (1 + _SIZE_TOLERANCE))
    assert low <= actual <= high, f"size {actual} not within [{low}, {high}]"
    segs = _parse_qbk(text)
    assert segs, "synthetic qbk must yield translatable segments"
    return segs


@pytest.mark.benchmark
@pytest.mark.parametrize("target_kb", [100, 500, 1000])
def test_benchmark_parse_qbk(benchmark, target_kb: int) -> None:
    target_bytes = target_kb * 1024
    text = generate_synthetic_qbk(target_bytes)
    segs = _assert_synthetic_qbk_valid(text, target_bytes)
    benchmark.extra_info["target_kb"] = target_kb
    benchmark.extra_info["byte_len"] = len(text.encode("utf-8"))
    benchmark.extra_info["segment_count"] = len(segs)
    result = benchmark(_parse_qbk, text)
    assert result


@pytest.mark.benchmark
def test_benchmark_quickbook_file_parse(benchmark) -> None:
    target_bytes = 1024 * 1024
    text = generate_synthetic_qbk(target_bytes)
    segs = _assert_synthetic_qbk_valid(text, target_bytes)

    def _run() -> int:
        store = QuickBookFile()
        store.parse(text)
        return len(store.units)

    benchmark.extra_info["target_kb"] = 1024
    benchmark.extra_info["byte_len"] = len(text.encode("utf-8"))
    benchmark.extra_info["segment_count"] = len(segs)
    unit_count = benchmark(_run)
    assert unit_count > 0


@pytest.mark.benchmark
def test_parse_1mb_peak_memory() -> None:
    target_bytes = 1024 * 1024
    text = generate_synthetic_qbk(target_bytes)
    _assert_synthetic_qbk_valid(text, target_bytes)
    tracemalloc.start()
    try:
        _parse_qbk(text)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < _PEAK_MEMORY_LIMIT_BYTES, (
        f"peak={peak} ({peak / (1024 * 1024):.2f} MiB)"
    )


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
