# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""
QuickBook (.qbk) parsing and translate-toolkit storage.

Implements an in-process parser that extracts translatable segments from
QuickBook documentation markup and a :class:`~translate.storage.base.TranslationStore`
subclass that exposes them as toolkit units.  There is no third-party
converter (like po4a) for QuickBook, so the full extraction and
reconstruction logic lives here.

Translatable constructs extracted:
    paragraphs (including those containing inline [@url], [link ...], etc.),
    ordered/unordered list blocks, headings [h1..h6] and generic [heading ...],
    section titles [section], admonitions ([note], [warning], [tip],
    [caution], [important], [blurb]), block-quotes [:...], table titles and
    prose cells [table], and variable list items [variablelist].

Non-translatable constructs (copied verbatim):
    code blocks (lines indented with space/tab), [pre ...], [/ comments],
    [include ...], [import ...], [def ...], [template ...], [quickbook ...],
    anchors [#...], images [$...], source-mode switches ([c++] etc.),
    conditional generation [? ...], [endsect], table cells containing only
    code fences (``` ... ```) or bare bracket references.

Inline markup ([*bold], ['italic], [@url text], [funcref ...], etc.) is
preserved verbatim inside unit source so translators see it and keep it.
Inline elements that wrap onto their own line (e.g. a bare [@url ...] line
inside a paragraph) are treated as part of the surrounding paragraph.

Sections whose body contains further translatable blocks are parsed
recursively (depth-limited to 10) so nested paragraphs and headings are also
extracted. Beyond that depth, nested translatable content is silently skipped
rather than raising an error.

Reconstruction:
    :func:`_apply_translations` replaces each translatable span in the
    original template with the result of a callback, copying everything else
    (bracket wrappers, code blocks, blank lines) character-for-character.
    The :class:`QuickBookTranslator` wires that callback to a PO store
    lookup, mirroring ``translate.convert.po2asciidoc.AsciiDocTranslator``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from translate.storage import base

# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

_QBK_MACRO_ONLY_RE = re.compile(r"^(?:__\w+__[\s,;.]*)+$")


# ---------------------------------------------------------------------------
# Grammar constants
# ---------------------------------------------------------------------------

_SKIP_KEYWORDS: frozenset[str] = frozenset(
    {
        "/",  # [/ comment]
        "include",  # [include file.qbk]
        "import",  # [import file.qbk]
        "def",  # [def macro_name value]
        "template",  # [template ...]
        "quickbook",  # [quickbook 1.x] version declaration
        "br",  # [br] deprecated line-break
        "pre",  # [pre preformatted / code-like block]
        "endsect",  # [endsect]
        "xinclude",  # [xinclude ...]
        "if",  # [if symbol]
        "elif",  # [elif symbol]
        "else",  # [else]
        "endif",  # [endif]
        "c++",
        "python",
        "ruby",
        "teletype",
        "xml",
        "javascript",
        "funcref",
        "classref",
        "memberref",
        "enumref",
        "macroref",
        "conceptref",
        "headerref",
        "globalref",
        "link",
    }
)

_SKIP_SINGLE_CHARS: frozenset[str] = frozenset({"/", "#", "$", "@", "?"})

_HEADING_KEYWORDS: frozenset[str] = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "heading"}
)

_ADMONITION_KEYWORDS: frozenset[str] = frozenset(
    {"note", "warning", "tip", "caution", "important", "blurb"}
)

_PARA_BREAK_KEYWORDS: frozenset[str] = frozenset(
    {
        "section",
        "endsect",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "heading",
        "note",
        "warning",
        "tip",
        "caution",
        "important",
        "blurb",
        "table",
        "variablelist",
        "pre",
        "include",
        "import",
        "def",
        "template",
        "quickbook",
        "xinclude",
        "if",
        "elif",
        "else",
        "endif",
        "c++",
        "python",
        "ruby",
        "teletype",
        "xml",
        "javascript",
        "/",
    }
)

_PARA_BREAK_SINGLE_CHARS: frozenset[str] = frozenset({"/", "#", "$", "?", ":"})


# ---------------------------------------------------------------------------
# Bracket utilities
# ---------------------------------------------------------------------------


def _find_bracket_end(text: str, start: int) -> int:
    r"""
    Return the index of the ``]`` that closes the ``[`` at *text[start]*.

    Handles nested brackets, triple-quote raw escapes (``'''...'''``),
    and single backslash escapes (``\[``, ``\]``).
    Returns ``-1`` if no matching bracket is found.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        if text[i : i + 3] == "'''":
            i += 3
            while i < n and text[i : i + 3] != "'''":
                i += 1
            i += 3
            continue
        if text[i] == "\\":
            i += min(2, n - i)
            continue
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_bracket_keyword(text: str) -> tuple[str, int]:
    """
    Parse keyword and content-start offset from a bracket block string.

    *text* spans the full bracket including the surrounding ``[`` and ``]``.
    Returns ``(keyword, content_offset)``.
    """
    i = 1  # skip opening '['
    n = len(text)

    if i < n and text[i] in {"/", "#", "$", "@", "?", ":"}:
        kw = text[i]
        i += 1
        while i < n and text[i] in {" ", "\t"}:
            i += 1
        return kw, i

    kw_start = i
    while i < n and text[i] not in {" ", "\t", "\n", "]", ":"}:
        i += 1
    kw = text[kw_start:i].lower()

    if i < n and text[i] == ":":
        i += 1
        while i < n and text[i] not in {" ", "\t", "\n", "]"}:
            i += 1

    while i < n and text[i] in {" ", "\t"}:
        i += 1
    if i < n and text[i] == "\n":
        i += 1

    return kw, i


# ---------------------------------------------------------------------------
# Segment data model
# ---------------------------------------------------------------------------


@dataclass
class _Seg:
    """One translatable span within a QuickBook document."""

    text_start: int
    text_end: int
    line: int
    seg_type: str
    msgid: str
    no_wrap: bool
    context: str = ""


# ---------------------------------------------------------------------------
# Cell-prose helpers (used by table / variablelist parser)
# ---------------------------------------------------------------------------


def _has_prose(text: str) -> bool:
    """Return True if *text* contains translatable prose outside bracket markup."""
    bare_chars: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "[":
            end = _find_bracket_end(text, i)
            if end != -1:
                bare_chars.append(" ")
                i = end + 1
                continue
        bare_chars.append(text[i])
        i += 1
    bare = "".join(bare_chars).strip()
    if not bare:
        return False
    return not _QBK_MACRO_ONLY_RE.match(bare)


def _clean_cell_text(text: str) -> str:
    r"""
    Prepare raw cell content as a translatable string.

    Strips backtick code fences, joins soft-wrapped lines per paragraph,
    preserves blank-line paragraph breaks.
    """
    lines = text.split("\n")
    paragraphs: list[str] = []
    current_para: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped == "```":
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped:
            current_para.append(stripped)
        elif current_para:
            paragraphs.append(" ".join(current_para))
            current_para = []
    if current_para:
        paragraphs.append(" ".join(current_para))
    return "\n\n".join(p for p in paragraphs if p)


def _extract_fence_content_segs(
    content: str,
    cell_body_start: int,
    cell_body_end: int,
    bracket_line: int,
    kw: str,
) -> list[_Seg]:
    """Extract translatable content from backtick code fences inside a table cell."""
    segs: list[_Seg] = []
    in_fence = False
    fence_content_start: int | None = None

    i = cell_body_start
    while i <= cell_body_end:
        eol = i
        while eol < cell_body_end and content[eol] != "\n":
            eol += 1

        line_stripped = content[i:eol].strip()

        if line_stripped == "```":
            if not in_fence:
                in_fence = True
                fence_content_start = eol + 1 if eol < cell_body_end else eol
            else:
                in_fence = False
                fence_content_end = i
                if (
                    fence_content_start is not None
                    and fence_content_end > fence_content_start
                ):
                    raw_code = content[fence_content_start:fence_content_end]
                    code_lines = [
                        ln.strip() for ln in raw_code.split("\n") if ln.strip()
                    ]
                    cleaned_code = "\n".join(code_lines)
                    if cleaned_code:
                        segs.append(
                            _Seg(
                                fence_content_start,
                                fence_content_end,
                                bracket_line,
                                kw,
                                cleaned_code,
                                no_wrap=True,
                                context=f"{kw} code",
                            )
                        )
                fence_content_start = None

        i = eol + 1 if eol < cell_body_end else cell_body_end + 1

    return segs


def _parse_table_inner(
    content: str,
    inner_abs_start: int,
    inner_abs_end: int,
    bracket_line: int,
    kw: str,
    _depth: int,
) -> list[_Seg]:
    """Parse a ``[table ...]`` or ``[variablelist ...]`` body into segments."""
    inner = content[inner_abs_start:inner_abs_end]
    segs: list[_Seg] = []

    nl = inner.find("\n")
    title_raw = inner[:nl] if nl != -1 else inner
    title = title_raw.strip()
    if title and not title.startswith("["):
        lead = inner.index(title)
        segs.append(
            _Seg(
                inner_abs_start + lead,
                inner_abs_start + lead + len(title),
                bracket_line,
                f"{kw}-title",
                title,
                no_wrap=True,
                context=f"{kw} title",
            )
        )
    if nl == -1:
        return segs

    i = inner_abs_start + nl + 1
    while i < inner_abs_end:
        ch = content[i]
        if ch in {" ", "\t", "\n"}:
            i += 1
            continue
        if ch != "[":
            i += 1
            continue

        row_end = _find_bracket_end(content, i)
        if row_end == -1 or row_end > inner_abs_end:
            i += 1
            continue

        ci = i + 1
        while ci < row_end:
            cc = content[ci]
            if cc in {" ", "\t", "\n"}:
                ci += 1
                continue
            if cc != "[":
                ci += 1
                continue

            cell_end = _find_bracket_end(content, ci)
            if cell_end == -1 or cell_end > row_end:
                ci += 1
                continue

            cell_body_start = ci + 1
            cell_body_end = cell_end
            raw_cell = content[cell_body_start:cell_body_end]
            cleaned = _clean_cell_text(raw_cell)
            if cleaned:
                segs.append(
                    _Seg(
                        cell_body_start,
                        cell_body_end,
                        bracket_line,
                        kw,
                        cleaned,
                        no_wrap=True,
                        context=f"{kw} cell",
                    )
                )
            else:
                segs.extend(
                    _extract_fence_content_segs(
                        content, cell_body_start, cell_body_end, bracket_line, kw
                    )
                )
            ci = cell_end + 1

        i = row_end + 1

    return segs


# ---------------------------------------------------------------------------
# Parser: QBK string -> list[_Seg]
# ---------------------------------------------------------------------------


def _parse_qbk(
    content: str,
    start: int = 0,
    stop: int | None = None,
    _depth: int = 0,
) -> list[_Seg]:
    """
    Parse *content[start:stop]* and return all translatable segments.

    Calls itself recursively (depth-capped at 10) for block elements whose
    bodies may contain further translatable blocks.  All returned offsets are
    absolute positions within *content*.
    """
    if stop is None:
        stop = len(content)
    if _depth > 10:
        return []

    segments: list[_Seg] = []
    i = start
    line = content[:start].count("\n") + 1

    while i < stop:
        ch = content[i]

        if ch == "\n":
            line += 1
            i += 1
            continue

        if ch in {" ", "\t"} and (i == 0 or content[i - 1] == "\n"):
            while i < stop:
                while i < stop and content[i] != "\n":
                    i += 1
                if i >= stop:
                    break
                i += 1
                line += 1
                if i < stop and content[i] not in {" ", "\t", "\n"}:
                    break
            continue

        if content[i : i + 3] == "'''":
            i += 3
            while i < stop and content[i : i + 3] != "'''":
                if content[i] == "\n":
                    line += 1
                i += 1
            i += 3
            continue

        if ch == "[":
            bracket_start = i
            bracket_line = line
            end = _find_bracket_end(content, i)
            if end == -1 or end >= stop:
                while i < stop and content[i] != "\n":
                    i += 1
                continue

            block_text = content[bracket_start : end + 1]
            kw, content_off = _parse_bracket_keyword(block_text)
            line += block_text.count("\n")
            i = end + 1

            if kw in _SKIP_KEYWORDS or kw in _SKIP_SINGLE_CHARS:
                continue

            raw_inner = block_text[content_off:-1]
            lstrip_n = len(raw_inner) - len(raw_inner.lstrip())
            rstrip_n = len(raw_inner) - len(raw_inner.rstrip())
            inner = raw_inner.strip()
            if not inner:
                continue

            inner_abs_start = bracket_start + content_off + lstrip_n
            inner_abs_end = bracket_start + len(block_text) - 1 - rstrip_n
            inner_multiline = "\n" in inner

            if kw in _HEADING_KEYWORDS:
                ctx = f"heading {kw[1]}" if kw != "heading" else "heading"
                segments.append(
                    _Seg(
                        inner_abs_start,
                        inner_abs_end,
                        bracket_line,
                        "heading",
                        inner,
                        no_wrap=True,
                        context=ctx,
                    )
                )
                continue

            if kw == "section":
                if inner_multiline:
                    nl_pos = inner.index("\n")
                    raw_title_line = inner[:nl_pos]
                    title = raw_title_line.strip()
                    if title:
                        title_lead = raw_title_line.index(title)
                        title_abs_start = inner_abs_start + title_lead
                        title_abs_end = title_abs_start + len(title)
                        segments.append(
                            _Seg(
                                title_abs_start,
                                title_abs_end,
                                bracket_line,
                                "section-title",
                                title,
                                no_wrap=True,
                                context="section title",
                            )
                        )
                    body_abs_start = inner_abs_start + nl_pos + 1
                    if body_abs_start < inner_abs_end:
                        segments.extend(
                            _parse_qbk(
                                content, body_abs_start, inner_abs_end, _depth + 1
                            )
                        )
                else:
                    segments.append(
                        _Seg(
                            inner_abs_start,
                            inner_abs_end,
                            bracket_line,
                            "section-title",
                            inner,
                            no_wrap=True,
                            context="section title",
                        )
                    )
                continue

            if kw in _ADMONITION_KEYWORDS:
                if inner_multiline:
                    segments.extend(
                        _parse_qbk(content, inner_abs_start, inner_abs_end, _depth + 1)
                    )
                else:
                    segments.append(
                        _Seg(
                            inner_abs_start,
                            inner_abs_end,
                            bracket_line,
                            "admonition",
                            inner,
                            no_wrap=False,
                            context=kw,
                        )
                    )
                continue

            if kw == ":":
                if inner_multiline:
                    segments.extend(
                        _parse_qbk(content, inner_abs_start, inner_abs_end, _depth + 1)
                    )
                else:
                    segments.append(
                        _Seg(
                            inner_abs_start,
                            inner_abs_end,
                            bracket_line,
                            "blockquote",
                            inner,
                            no_wrap=False,
                            context="blockquote",
                        )
                    )
                continue

            if kw in {"table", "variablelist"}:
                segments.extend(
                    _parse_table_inner(
                        content,
                        inner_abs_start,
                        inner_abs_end,
                        bracket_line,
                        kw,
                        _depth,
                    )
                )
                continue

            continue

        para_start = i
        para_line = line

        while i < stop:
            eol = i
            while eol < stop and content[eol] != "\n":
                eol += 1
            line_text = content[i:eol]

            if not line_text.strip():
                break
            if line_text and line_text[0] in {" ", "\t"}:
                break
            if line_text.startswith("'''"):
                break
            if line_text.startswith("["):
                bracket_end = _find_bracket_end(line_text, 0)
                if bracket_end != -1:
                    para_kw, _ = _parse_bracket_keyword(line_text[: bracket_end + 1])
                else:
                    para_kw, _ = _parse_bracket_keyword(line_text + "]")
                if (
                    para_kw in _PARA_BREAK_KEYWORDS
                    or para_kw in _PARA_BREAK_SINGLE_CHARS
                ):
                    break

            i = eol
            if i < stop:
                i += 1
                line += 1

        stripped = content[para_start:i].rstrip()
        if stripped and _has_prose(stripped):
            first_non_ws = stripped.lstrip()[0]
            is_list = first_non_ws in {"*", "#"}
            if is_list:
                msgid = stripped
            else:
                msgid = " ".join(
                    ln.strip() for ln in stripped.split("\n") if ln.strip()
                )
            segments.append(
                _Seg(
                    para_start,
                    para_start + len(stripped),
                    para_line,
                    "list" if is_list else "paragraph",
                    msgid,
                    no_wrap=False,
                    context="list" if is_list else "paragraph",
                )
            )

    return segments


# ---------------------------------------------------------------------------
# Reconstruction helper
# ---------------------------------------------------------------------------


def _apply_translations(template_text: str, callback) -> str:
    """
    Replace each translatable span with ``callback(source_text)``.

    Preserves all non-translatable content character-for-character.
    Keeps trailing newlines on spans that originally ended with one.
    """
    segments = sorted(_parse_qbk(template_text), key=lambda s: s.text_start)
    parts: list[str] = []
    pos = 0
    for seg in segments:
        if seg.text_start > pos:
            parts.append(template_text[pos : seg.text_start])
        translation = callback(seg.msgid)
        original_span = template_text[seg.text_start : seg.text_end]
        # Paragraph/list msgids join wrapped lines; the file span may still
        # contain newlines. When the callback leaves the normalized msgid
        # unchanged, keep the original slice (matches legacy ``po_to_qbk``).
        if translation == seg.msgid:
            text_to_use = original_span
        else:
            text_to_use = translation
        if seg.text_end > 0 and template_text[seg.text_end - 1] == "\n":
            text_to_use = text_to_use.rstrip("\n") + "\n"
        parts.append(text_to_use)
        pos = seg.text_end
    parts.append(template_text[pos:])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Translate-toolkit storage: QuickBookUnit + QuickBookFile
# ---------------------------------------------------------------------------


class QuickBookUnit(base.TranslationUnit):
    """A unit of translatable QuickBook content."""

    def __init__(self, source=None):
        super().__init__(source)
        self.locations: list[str] = []
        self._notes: str = ""

    def addlocation(self, location: str) -> None:
        self.locations.append(location)

    def getlocations(self) -> list[str]:
        return self.locations

    def getnotes(self, origin=None) -> str:
        return self._notes

    def addnote(self, text: str, origin=None, position="append") -> None:
        if self._notes:
            self._notes += "\n" + text
        else:
            self._notes = text

    def getid(self) -> str:
        docpath = self.getdocpath()
        if docpath:
            return docpath
        return self.source or ""


class QuickBookFile(base.TranslationStore):
    """QuickBook (.qbk) file as a translate-toolkit TranslationStore."""

    UnitClass = QuickBookUnit

    def __init__(self, inputfile=None, callback=None):
        super().__init__()
        self.filename: str = getattr(inputfile, "name", "") or ""
        self.callback = callback or self._identity
        self._source_text: str = ""
        if inputfile is not None:
            data = inputfile.read()
            inputfile.close()
            self.parse(data)

    def parse(self, data):
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        self._source_text = text
        segments = _parse_qbk(text)
        basename = Path(self.filename).name if self.filename else ""
        for idx, seg in enumerate(segments):
            if not seg.msgid:
                continue
            unit = self.addsourceunit(seg.msgid)
            unit.addlocation(f"{basename}:{seg.line}" if basename else str(seg.line))
            unit.setdocpath(f"qbk:{idx}")
            if seg.context:
                unit.addnote(f"type: {seg.context}", "developer")

    @property
    def filesrc(self) -> str:
        """Reconstructed file with translations applied via callback."""
        return _apply_translations(self._source_text, self.callback)

    @staticmethod
    def _identity(text: str) -> str:
        return text


# ---------------------------------------------------------------------------
# Translator (mirrors translate.convert.po2asciidoc.AsciiDocTranslator)
# ---------------------------------------------------------------------------


class QuickBookTranslator:
    """Apply PO translations to a QuickBook template file."""

    def __init__(self, inputstore, includefuzzy=True, outputthreshold=None):
        self.inputstore = inputstore
        self.inputstore.require_index()
        self.includefuzzy = includefuzzy
        self.outputthreshold = outputthreshold

    def translate(self, templatefile, outputfile):
        from translate.convert import convert

        if not convert.should_output_store(self.inputstore, self.outputthreshold):
            return False
        outputstore = QuickBookFile(
            inputfile=templatefile,
            callback=self._lookup,
        )
        outputfile.write(outputstore.filesrc.encode("utf-8"))
        return 1

    def _lookup(self, string: str) -> str:
        units = self.inputstore.sourceindex.get(string, None)
        if units is None:
            return string
        unit = units[0]
        if unit.istranslated():
            return unit.target
        if self.includefuzzy and unit.isfuzzy():
            return unit.target
        return unit.source
