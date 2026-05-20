# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

from boost_weblate.endpoint.serializers import AddOrUpdateRequestSerializer


def test_add_or_update_serializer_valid_minimal() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "CppDigest",
            "version": "boost-1.90.0",
            "add_or_update": {"zh_Hans": ["json"]},
        }
    )
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["organization"] == "CppDigest"
    assert ser.validated_data["version"] == "boost-1.90.0"
    assert ser.validated_data["add_or_update"] == {"zh_Hans": ["json"]}
    assert ser.validated_data.get("extensions") is None


def test_add_or_update_serializer_accepts_extensions() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {"ja": ["unordered"]},
            "extensions": [".adoc", ".md"],
        }
    )
    assert ser.is_valid(), ser.errors
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
    assert "add_or_update" in ser.errors


def test_add_or_update_serializer_rejects_empty_submodule_list() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {"zh_Hans": []},
        }
    )
    assert not ser.is_valid()
    assert "zh_Hans" in ser.errors["add_or_update"]


def test_add_or_update_serializer_rejects_non_list_submodules() -> None:
    ser = AddOrUpdateRequestSerializer(
        data={
            "organization": "o",
            "version": "v",
            "add_or_update": {"ja": "json"},
        }
    )
    assert not ser.is_valid()
    assert "ja" in ser.errors["add_or_update"]


def test_add_or_update_serializer_missing_required_fields() -> None:
    ser = AddOrUpdateRequestSerializer(data={})
    assert not ser.is_valid()
    for key in ("organization", "version", "add_or_update"):
        assert key in ser.errors
