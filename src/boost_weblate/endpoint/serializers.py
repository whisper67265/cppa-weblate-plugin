# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""DRF serializers for the Boost documentation translation API."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from django.core.exceptions import ValidationError
from rest_framework import serializers

from boost_weblate.endpoint.errors import (
    BoostEndpointErrorCode,
    boost_validation_errors,
    to_error_dict,
)
from boost_weblate.endpoint.validators import (
    MAX_ADD_OR_UPDATE_LANGS,
    MAX_SUBMODULES_PER_LANG,
    validate_language_code,
    validate_repo_segment,
)


class DrfValidationCode(StrEnum):
    """DRF ``ErrorDetail.code`` values mapped by this serializer."""

    REQUIRED = "required"
    NOT_A_LIST = "not_a_list"
    EMPTY = "empty"


class RequestField(StrEnum):
    """Top-level add-or-update request field names."""

    ORGANIZATION = "organization"
    ADD_OR_UPDATE = "add_or_update"
    VERSION = "version"
    EXTENSIONS = "extensions"


class AddOrUpdateRequestSerializer(serializers.Serializer):
    """Serializer for add_or_update endpoint request."""

    organization = serializers.CharField(
        required=True,
        help_text="GitHub organization name",
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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._custom_validation_errors: list[dict[str, Any]] = []
        self._custom_error_fields: set[str] = set()
        self._structured_errors: list[dict[str, Any]] = []

    @property
    def structured_errors(self) -> list[dict[str, Any]]:
        return self._structured_errors

    def is_valid(self, *, raise_exception: bool = False) -> bool:
        self._custom_validation_errors = []
        self._custom_error_fields = set()
        valid = super().is_valid(raise_exception=False)
        if not valid:
            self._structured_errors = self._to_structured_errors()
        else:
            self._structured_errors = []
        if not valid and raise_exception:
            raise serializers.ValidationError(self._structured_errors)
        return valid

    def _to_structured_errors(self) -> list[dict[str, Any]]:
        structured = list(self._custom_validation_errors)
        for field, messages in self.errors.items():
            if field in self._custom_error_fields:
                continue
            for subfield, message, drf_code in self._flatten_field_errors(messages):
                code = self._code_for_drf_error(field, drf_code, subfield=subfield)
                metadata: dict[str, Any] = {"field": field}
                if drf_code is not None:
                    metadata["drf_code"] = drf_code
                if subfield and field == RequestField.ADD_OR_UPDATE:
                    metadata["language"] = subfield
                structured.append(to_error_dict(code, message, **metadata))
        return structured

    @staticmethod
    def _message_and_drf_code(err: Any) -> tuple[str, str | None]:
        return str(err), getattr(err, "code", None)

    @staticmethod
    def _flatten_field_errors(
        messages: Any,
    ) -> list[tuple[str | None, str, str | None]]:
        """Flatten nested DRF errors into (subfield, message, drf_code) triplets."""
        results: list[tuple[str | None, str, str | None]] = []
        if isinstance(messages, dict) or hasattr(messages, "items"):
            for key, value in messages.items():
                key_str = str(key)
                if isinstance(value, (list, tuple)):
                    for msg in value:
                        if isinstance(msg, dict) or hasattr(msg, "items"):
                            nested = AddOrUpdateRequestSerializer._flatten_field_errors(
                                msg
                            )
                            results.extend(
                                (key_str if sub is None else sub, message, drf_code)
                                for sub, message, drf_code in nested
                            )
                        else:
                            message, drf_code = (
                                AddOrUpdateRequestSerializer._message_and_drf_code(msg)
                            )
                            results.append((key_str, message, drf_code))
                elif isinstance(value, dict) or hasattr(value, "items"):
                    nested = AddOrUpdateRequestSerializer._flatten_field_errors(value)
                    results.extend(
                        (key_str if sub is None else sub, message, drf_code)
                        for sub, message, drf_code in nested
                    )
                else:
                    message, drf_code = (
                        AddOrUpdateRequestSerializer._message_and_drf_code(value)
                    )
                    results.append((key_str, message, drf_code))
        else:
            for msg in messages:
                message, drf_code = AddOrUpdateRequestSerializer._message_and_drf_code(
                    msg
                )
                results.append((None, message, drf_code))
        return results

    @staticmethod
    def _code_for_drf_error(
        field: str,
        drf_code: str | None,
        *,
        subfield: str | None = None,
    ) -> BoostEndpointErrorCode:
        if drf_code == DrfValidationCode.REQUIRED:
            return BoostEndpointErrorCode.REQUIRED_FIELD
        if drf_code == DrfValidationCode.NOT_A_LIST:
            return BoostEndpointErrorCode.INVALID_SUBMODULE_LIST
        if drf_code == DrfValidationCode.EMPTY:
            if field == RequestField.ADD_OR_UPDATE and subfield:
                return BoostEndpointErrorCode.INVALID_SUBMODULE_LIST
            return BoostEndpointErrorCode.REQUIRED_FIELD
        return BoostEndpointErrorCode.REQUIRED_FIELD

    def validate_organization(self, value: str) -> str:
        """Reject organization names that would produce unsafe clone URLs."""
        try:
            return validate_repo_segment(value, field="organization")
        except ValidationError as exc:
            self._custom_error_fields.add(RequestField.ORGANIZATION)
            self._custom_validation_errors.extend(
                boost_validation_errors(
                    [
                        (
                            BoostEndpointErrorCode.INVALID_CLONE_URL,
                            str(exc),
                            {"field": RequestField.ORGANIZATION},
                        )
                    ]
                )
            )
            raise serializers.ValidationError(str(exc)) from exc

    def validate_version(self, value: str) -> str:
        """Reject version strings with unsafe characters or excessive length."""
        try:
            return validate_repo_segment(value, field="version")
        except ValidationError as exc:
            self._custom_error_fields.add(RequestField.VERSION)
            self._custom_validation_errors.extend(
                boost_validation_errors(
                    [
                        (
                            BoostEndpointErrorCode.INVALID_CLONE_URL,
                            str(exc),
                            {"field": RequestField.VERSION},
                        )
                    ]
                )
            )
            raise serializers.ValidationError(str(exc)) from exc

    def validate_extensions(self, value: list[str] | None) -> list[str] | None:
        """Strip entries and remove blanks so all-empty input does not filter files."""
        if value is None:
            return None
        cleaned: list[str] = []
        for entry in value:
            if not isinstance(entry, str):
                raise serializers.ValidationError(
                    "Each extension must be a string.",
                    code=DrfValidationCode.NOT_A_LIST,
                )
            stripped = entry.strip()
            if stripped:
                cleaned.append(stripped)
        return cleaned or None

    def validate_add_or_update(self, value: dict[str, Any]) -> dict[str, Any]:
        """Require non-empty string language keys and non-empty submodule lists."""
        items: list[tuple[BoostEndpointErrorCode, str, dict[str, Any]]] = []
        if len(value) > MAX_ADD_OR_UPDATE_LANGS:
            items.append(
                (
                    BoostEndpointErrorCode.INVALID_LANGUAGE_CODE,
                    (
                        f"add_or_update: exceeds maximum of "
                        f"{MAX_ADD_OR_UPDATE_LANGS} language keys "
                        f"(got {len(value)})."
                    ),
                    {"field": RequestField.ADD_OR_UPDATE},
                )
            )
        for lang_code, submodules in value.items():
            if not isinstance(lang_code, str) or lang_code.strip() == "":
                items.append(
                    (
                        BoostEndpointErrorCode.INVALID_LANGUAGE_CODE,
                        (
                            "add_or_update: each key must be a non-empty language "
                            f"code; got {repr(lang_code)}"
                        ),
                        {
                            "field": RequestField.ADD_OR_UPDATE,
                            "language": str(lang_code),
                        },
                    )
                )
                continue
            try:
                validate_language_code(lang_code)
            except ValidationError as exc:
                items.append(
                    (
                        BoostEndpointErrorCode.INVALID_LANGUAGE_CODE,
                        str(exc),
                        {
                            "field": RequestField.ADD_OR_UPDATE,
                            "language": lang_code,
                        },
                    )
                )
                continue
            if not isinstance(submodules, list):
                items.append(
                    (
                        BoostEndpointErrorCode.INVALID_SUBMODULE_LIST,
                        (
                            "add_or_update: each value must be a non-empty list of "
                            f"submodule names; key {lang_code!r} is not a list "
                            f"(got {type(submodules).__name__})."
                        ),
                        {"field": RequestField.ADD_OR_UPDATE, "language": lang_code},
                    )
                )
            elif len(submodules) == 0:
                items.append(
                    (
                        BoostEndpointErrorCode.INVALID_SUBMODULE_LIST,
                        (
                            "add_or_update: each value must be a non-empty list of "
                            f"submodule names; key {lang_code!r} has an empty list."
                        ),
                        {"field": RequestField.ADD_OR_UPDATE, "language": lang_code},
                    )
                )
            elif len(submodules) > MAX_SUBMODULES_PER_LANG:
                items.append(
                    (
                        BoostEndpointErrorCode.INVALID_SUBMODULE_LIST,
                        (
                            f"add_or_update: key {lang_code!r} exceeds maximum of "
                            f"{MAX_SUBMODULES_PER_LANG} submodules "
                            f"(got {len(submodules)})."
                        ),
                        {"field": RequestField.ADD_OR_UPDATE, "language": lang_code},
                    )
                )
            else:
                for submodule in submodules:
                    if not isinstance(submodule, str):
                        items.append(
                            (
                                BoostEndpointErrorCode.INVALID_SUBMODULE_LIST,
                                (
                                    "add_or_update: each submodule name must be a "
                                    f"string; key {lang_code!r} has "
                                    f"{type(submodule).__name__}."
                                ),
                                {
                                    "field": RequestField.ADD_OR_UPDATE,
                                    "language": lang_code,
                                },
                            )
                        )
                        break
                    try:
                        validate_repo_segment(submodule, field="submodule")
                    except ValidationError as exc:
                        items.append(
                            (
                                BoostEndpointErrorCode.INVALID_SUBMODULE,
                                str(exc),
                                {
                                    "field": RequestField.ADD_OR_UPDATE,
                                    "language": lang_code,
                                    "submodule": submodule,
                                },
                            )
                        )
        if items:
            self._custom_error_fields.add(RequestField.ADD_OR_UPDATE)
            self._custom_validation_errors.extend(boost_validation_errors(items))
            raise serializers.ValidationError({RequestField.ADD_OR_UPDATE: "invalid"})
        return value
