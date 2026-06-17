# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Weblate translation format handlers for Boost (QuickBook and related)."""

from __future__ import annotations

from typing import Any

from boost_weblate.formats.registry import registry

registry.register_entry(
    format_id="quickbook",
    file_patterns=("*.qbk",),
    weblate_class="boost_weblate.formats.quickbook.QuickBookFormat",
)

__all__: list[str] = ["QuickBookFormat", "registry"]


def __getattr__(name: str) -> Any:
    if name == "QuickBookFormat":
        from boost_weblate.formats.quickbook import QuickBookFormat as _quickbook_format

        return _quickbook_format
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
