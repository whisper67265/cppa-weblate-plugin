# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

from rest_framework.exceptions import ErrorDetail

from boost_weblate.endpoint.errors import BoostEndpointErrorCode
from boost_weblate.endpoint.serializers import (
    AddOrUpdateRequestSerializer,
    DrfValidationCode,
    RequestField,
)


def _error_codes(errors: list[dict]) -> list[str]:
    return [e["code"] for e in errors]


def test_add_or_update_serializer_valid_minimal() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "CppDigest",
            "version": "boost-1.90.0",
            "add_or_update": {"zh_Hans": ["json"]},
        }
    )
    assert ser.is_valid(), ser.structured_errors
    assert ser.validated_data["organization"] == "CppDigest"
    assert ser.validated_data["version"] == "boost-1.90.0"
    assert ser.validated_data["add_or_update"] == {"zh_Hans": ["json"]}
    assert ser.validated_data.get("extensions") is None


def test_add_or_update_serializer_accepts_extensions() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {"zh_Hans": ["unordered"]},
            "extensions": [".adoc", ".md"],
        }
    )
    assert ser.is_valid(), ser.structured_errors
    assert ser.validated_data["extensions"] == [".adoc", ".md"]


def test_add_or_update_serializer_rejects_empty_map() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {},
        }
    )
    assert not ser.is_valid()
    assert BoostEndpointErrorCode.REQUIRED_FIELD.value in _error_codes(
        ser.structured_errors
    )
    add_or_update_errors = [
        e for e in ser.structured_errors if e["metadata"]["field"] == "add_or_update"
    ]
    assert len(add_or_update_errors) == 1
    assert add_or_update_errors[0]["metadata"]["drf_code"] == "empty"
    assert (
        add_or_update_errors[0]["code"] == BoostEndpointErrorCode.REQUIRED_FIELD.value
    )


def test_add_or_update_serializer_rejects_empty_submodule_list() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {"zh_Hans": []},
        }
    )
    assert not ser.is_valid()
    assert BoostEndpointErrorCode.INVALID_SUBMODULE_LIST.value in _error_codes(
        ser.structured_errors
    )
    assert any(
        e.get("metadata", {}).get("language") == "zh_Hans"
        for e in ser.structured_errors
    )


def test_add_or_update_serializer_rejects_non_list_submodules() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {"zh_Hans": "json"},
        }
    )
    assert not ser.is_valid()
    assert BoostEndpointErrorCode.INVALID_SUBMODULE_LIST.value in _error_codes(
        ser.structured_errors
    )
    lang_errors = [
        e
        for e in ser.structured_errors
        if e.get("metadata", {}).get("language") == "zh_Hans"
    ]
    assert lang_errors
    assert lang_errors[0]["metadata"]["drf_code"] == "not_a_list"


def test_flatten_field_errors_propagates_error_detail_code() -> None:
    nested = {
        "zh_Hans": [
            ErrorDetail(
                'Expected a list of items but got type "str".',
                code=DrfValidationCode.NOT_A_LIST,
            )
        ]
    }
    flattened = AddOrUpdateRequestSerializer._flatten_field_errors(nested)
    assert flattened == [
        (
            "zh_Hans",
            'Expected a list of items but got type "str".',
            "not_a_list",
        )
    ]


def test_code_for_drf_error_maps_drf_codes() -> None:
    assert (
        AddOrUpdateRequestSerializer._code_for_drf_error(
            RequestField.ORGANIZATION, DrfValidationCode.REQUIRED
        )
        == BoostEndpointErrorCode.REQUIRED_FIELD
    )
    assert (
        AddOrUpdateRequestSerializer._code_for_drf_error(
            RequestField.ADD_OR_UPDATE,
            DrfValidationCode.NOT_A_LIST,
            subfield="zh_Hans",
        )
        == BoostEndpointErrorCode.INVALID_SUBMODULE_LIST
    )
    assert (
        AddOrUpdateRequestSerializer._code_for_drf_error(
            RequestField.ADD_OR_UPDATE, DrfValidationCode.EMPTY, subfield="zh_Hans"
        )
        == BoostEndpointErrorCode.INVALID_SUBMODULE_LIST
    )
    assert (
        AddOrUpdateRequestSerializer._code_for_drf_error(
            RequestField.ADD_OR_UPDATE, DrfValidationCode.EMPTY
        )
        == BoostEndpointErrorCode.REQUIRED_FIELD
    )


def test_add_or_update_serializer_missing_required_fields() -> None:
    ser = AddOrUpdateRequestSerializer(data={})
    assert not ser.is_valid()
    codes = _error_codes(ser.structured_errors)
    assert codes.count(BoostEndpointErrorCode.REQUIRED_FIELD.value) == 3
    fields = {e["metadata"]["field"] for e in ser.structured_errors}
    assert fields == {"organization", "version", "add_or_update"}
    assert all(
        e["metadata"].get("drf_code") == "required" for e in ser.structured_errors
    )


def test_add_or_update_serializer_rejects_invalid_organization() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "bad/org",
            "version": "v",
            "add_or_update": {"zh_Hans": ["json"]},
        }
    )
    assert not ser.is_valid()
    assert BoostEndpointErrorCode.INVALID_CLONE_URL.value in _error_codes(
        ser.structured_errors
    )


def test_add_or_update_serializer_rejects_invalid_submodule_segment() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {"zh_Hans": ["../evil"]},
        }
    )
    assert not ser.is_valid()
    assert BoostEndpointErrorCode.INVALID_SUBMODULE.value in _error_codes(
        ser.structured_errors
    )


def test_add_or_update_serializer_accumulates_custom_errors() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "bad/org",
            "version": "v",
            "add_or_update": {"zh_Hans": ["../evil"]},
        }
    )
    assert not ser.is_valid()
    codes = _error_codes(ser.structured_errors)
    assert BoostEndpointErrorCode.INVALID_CLONE_URL.value in codes
    assert BoostEndpointErrorCode.INVALID_SUBMODULE.value in codes
    fields = {e["metadata"]["field"] for e in ser.structured_errors}
    assert fields == {"organization", "add_or_update"}


def test_invalid_organization_still_flattens_other_drf_errors() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "bad/org",
            "add_or_update": {"zh_Hans": ["json"]},
        }
    )
    assert not ser.is_valid()
    codes = _error_codes(ser.structured_errors)
    assert BoostEndpointErrorCode.INVALID_CLONE_URL.value in codes
    assert BoostEndpointErrorCode.REQUIRED_FIELD.value in codes
    org_errors = [
        e for e in ser.structured_errors if e["metadata"]["field"] == "organization"
    ]
    version_errors = [
        e for e in ser.structured_errors if e["metadata"]["field"] == "version"
    ]
    assert len(org_errors) == 1
    assert org_errors[0]["code"] == BoostEndpointErrorCode.INVALID_CLONE_URL.value
    assert len(version_errors) == 1
    assert version_errors[0]["metadata"]["drf_code"] == "required"
