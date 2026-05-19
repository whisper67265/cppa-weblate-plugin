# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""DRF serializers for the Boost documentation translation API."""

from __future__ import annotations

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
        child=serializers.CharField(allow_blank=True),
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Optional list of file extensions to include (e.g. ['.adoc', '.md']). "
            "Only Weblate-supported extensions in this list are scanned. "
            "If None or empty, all Weblate-supported extensions are used."
        ),
    )
