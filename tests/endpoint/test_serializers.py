# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

from boost_weblate.endpoint.errors import BoostEndpointErrorCode
from boost_weblate.endpoint.serializers import AddOrUpdateRequestSerializer


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
    assert any(
        e.get("metadata", {}).get("field") == "add_or_update"
        for e in ser.structured_errors
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
    assert any(
        e.get("metadata", {}).get("language") == "zh_Hans"
        for e in ser.structured_errors
    )


def test_add_or_update_serializer_missing_required_fields() -> None:
    ser = AddOrUpdateRequestSerializer(data={})
    assert not ser.is_valid()
    codes = _error_codes(ser.structured_errors)
    assert codes.count(BoostEndpointErrorCode.REQUIRED_FIELD.value) == 3
    fields = {e["metadata"]["field"] for e in ser.structured_errors}
    assert fields == {"organization", "version", "add_or_update"}
