# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""DRF serializers for the Boost documentation translation API."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers


class AddOrUpdateRequestSerializer(serializers.Serializer):
    """Serializer for add_or_update endpoint request."""

    organization = serializers.CharField(
        required=True,
        help_text="GitHub organization name (e.g., 'CppDigest')",
    )
    add_or_update = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=True,
        allow_empty=False,
        help_text=(
            "Map language code -> list of submodule names. "
            'E.g. {"zh_Hans": ["json", "unordered"], "ja": ["json"]}. '
            "Service runs for each lang_code with its submodule array."
        ),
    )
    version = serializers.CharField(
        required=True,
        help_text="Boost version (e.g., 'boost-1.90.0')",
    )
    extensions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Optional list of file extensions to include (e.g. ['.adoc', '.md']). "
            "Only Weblate-supported extensions in this list are scanned. "
            "If None or empty, all Weblate-supported extensions are used."
        ),
    )

    def validate_add_or_update(self, value: dict[str, Any]) -> dict[str, Any]:
        """Require non-empty string language keys and non-empty submodule lists."""
        errors: dict[str, str] = {}
        for lang_code, submodules in value.items():
            if not isinstance(lang_code, str) or lang_code.strip() == "":
                errors[str(lang_code)] = (
                    "add_or_update: each key must be a non-empty language code; "
                    f"got {repr(lang_code)}"
                )
                continue
            if not isinstance(submodules, list):
                errors[str(lang_code)] = (
                    "add_or_update: each value must be a non-empty list of submodule "
                    f"names; key {lang_code!r} is not a list "
                    f"(got {type(submodules).__name__})."
                )
            elif len(submodules) == 0:
                errors[str(lang_code)] = (
                    "add_or_update: each value must be a non-empty list of submodule "
                    f"names; key {lang_code!r} has an empty list."
                )
        if errors:
            raise serializers.ValidationError(errors)
        return value
