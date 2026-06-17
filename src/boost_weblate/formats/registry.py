# SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Declarative registry for plugin translation format handlers."""

from __future__ import annotations

import fnmatch
from abc import ABC
from typing import ClassVar


class RegisteredFormat(ABC):
    """Plugin format metadata registered in :class:`FormatRegistry`.

    Subclasses declare ``format_id``, ``file_patterns``, and ``weblate_class``.
    Parsing and serialization live in the Weblate ``ConvertFormat`` adapter
    (``convertfile`` / ``save_content``).
    """

    format_id: ClassVar[str]
    file_patterns: ClassVar[tuple[str, ...]]
    weblate_class: ClassVar[str]


class FormatRegistry:
    """Collects :class:`RegisteredFormat` specs for discovery and dispatch."""

    def __init__(self) -> None:
        self._formats: dict[str, type[RegisteredFormat]] = {}

    def register(self, fmt: type[RegisteredFormat]) -> type[RegisteredFormat]:
        """Register a format class; usable as a class decorator."""
        self._validate(fmt)
        existing = self._formats.get(fmt.format_id)
        if existing is fmt:
            return fmt
        if existing is not None and not self._is_metadata_entry(existing):
            return existing
        self._formats[fmt.format_id] = fmt
        return fmt

    def register_entry(
        self,
        *,
        format_id: str,
        file_patterns: tuple[str, ...],
        weblate_class: str,
    ) -> None:
        """Register format metadata without importing the Weblate adapter class."""
        if not format_id:
            msg = "format_id is required"
            raise ValueError(msg)
        self._validate_file_patterns(file_patterns)
        if not weblate_class:
            msg = "weblate_class is required"
            raise ValueError(msg)
        existing = self._formats.get(format_id)
        if existing is not None and not self._is_metadata_entry(existing):
            return
        entry = type(
            f"_{format_id.title()}FormatEntry",
            (RegisteredFormat,),
            {
                "format_id": format_id,
                "file_patterns": file_patterns,
                "weblate_class": weblate_class,
            },
        )
        self._formats[format_id] = entry

    def registered(self) -> tuple[type[RegisteredFormat], ...]:
        """Return registered format specs in registration order."""
        return tuple(self._formats.values())

    def weblate_class_paths(self) -> tuple[str, ...]:
        """Dotted import paths for Weblate ``WEBLATE_FORMATS`` registration."""
        return tuple(fmt.weblate_class for fmt in self._formats.values())

    def get_by_id(self, format_id: str) -> type[RegisteredFormat] | None:
        """Return the spec for *format_id*, or ``None`` if not registered."""
        return self._formats.get(format_id)

    def match_filename(self, filename: str) -> type[RegisteredFormat] | None:
        """Return the first spec whose :attr:`~RegisteredFormat.file_patterns` matches.

        Matching is against the basename of *filename*.
        """
        basename = filename.rsplit("/", maxsplit=1)[-1]
        for fmt in self._formats.values():
            if any(fnmatch.fnmatch(basename, pattern) for pattern in fmt.file_patterns):
                return fmt
        return None

    def extension_map(self) -> dict[str, str]:
        """Map extensions (e.g. ``\".qbk\"``) to :attr:`~RegisteredFormat.format_id`."""
        result: dict[str, str] = {}
        for fmt in self._formats.values():
            for pattern in fmt.file_patterns:
                if pattern.startswith("*.") and len(pattern) > 2:
                    ext = "." + pattern[2:].lower()
                    result[ext] = fmt.format_id
        return result

    def clear(self) -> None:
        """Remove all registrations (intended for tests)."""
        self._formats.clear()

    @staticmethod
    def _is_metadata_entry(fmt: type[RegisteredFormat]) -> bool:
        return fmt.__name__.endswith("FormatEntry")

    @staticmethod
    def _validate_file_patterns(
        patterns: object,
        *,
        name: str = "file_patterns",
    ) -> None:
        if isinstance(patterns, str) or not isinstance(patterns, (list, tuple)):
            kind = type(patterns).__name__
            msg = f"{name} must be a list or tuple of glob patterns, not {kind}"
            raise ValueError(msg)
        if not patterns:
            msg = f"{name} must be non-empty"
            raise ValueError(msg)

    @staticmethod
    def _validate(fmt: type[RegisteredFormat]) -> None:
        if not getattr(fmt, "format_id", ""):
            msg = f"{fmt.__name__}: format_id is required"
            raise ValueError(msg)
        patterns = getattr(fmt, "file_patterns", ())
        FormatRegistry._validate_file_patterns(
            patterns, name=f"{fmt.__name__}: file_patterns"
        )
        if not getattr(fmt, "weblate_class", ""):
            msg = f"{fmt.__name__}: weblate_class is required"
            raise ValueError(msg)


registry = FormatRegistry()
