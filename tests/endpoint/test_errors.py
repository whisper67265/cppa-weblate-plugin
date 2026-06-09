# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import pytest
from weblate.trans.exceptions import WeblateError

from boost_weblate.endpoint.errors import (
    BoostEndpointError,
    BoostEndpointErrorCode,
    append_error,
    boost_validation_errors,
    to_error_dict,
    wrap_task_error,
)


def test_boost_endpoint_error_subclasses_weblate_error() -> None:
    err = BoostEndpointError(
        "clone failed",
        code=BoostEndpointErrorCode.CLONE_FAILED,
    )
    assert isinstance(err, WeblateError)
    assert isinstance(err, BoostEndpointError)


def test_boost_endpoint_error_accepts_string_code() -> None:
    err = BoostEndpointError("msg", code="clone_failed")
    assert err.code == BoostEndpointErrorCode.CLONE_FAILED


def test_boost_endpoint_error_to_dict_shape() -> None:
    err = BoostEndpointError(
        "Failed to clone repository for json",
        code=BoostEndpointErrorCode.CLONE_FAILED,
        metadata={"submodule": "json", "organization": "boostorg"},
    )
    assert err.to_dict() == {
        "code": "clone_failed",
        "message": "Failed to clone repository for json",
        "metadata": {"submodule": "json", "organization": "boostorg"},
    }


def test_boost_endpoint_error_empty_metadata_defaults_to_dict() -> None:
    err = BoostEndpointError("msg", code=BoostEndpointErrorCode.REQUIRED_FIELD)
    assert err.metadata == {}
    assert err.to_dict()["metadata"] == {}


def test_to_error_dict_without_raising() -> None:
    payload = to_error_dict(
        BoostEndpointErrorCode.PERMISSION_DENIED,
        "Can not create project (missing project.add)",
        permission="project.add",
        project_slug="boost-json-documentation-zh_Hans",
    )
    assert payload == {
        "code": "permission_denied",
        "message": "Can not create project (missing project.add)",
        "metadata": {
            "permission": "project.add",
            "project_slug": "boost-json-documentation-zh_Hans",
        },
    }


def test_append_error_creates_errors_list() -> None:
    result: dict = {}
    append_error(
        result,
        BoostEndpointErrorCode.CLONE_FAILED,
        "Failed to clone repository for json",
        submodule="json",
    )
    assert result["errors"] == [
        {
            "code": "clone_failed",
            "message": "Failed to clone repository for json",
            "metadata": {"submodule": "json"},
        }
    ]


def test_append_error_appends_to_existing_list() -> None:
    result: dict = {
        "errors": [
            {
                "code": "invalid_submodule",
                "message": "Invalid submodule name: ../evil",
                "metadata": {"submodule": "../evil"},
            }
        ]
    }
    append_error(
        result,
        BoostEndpointErrorCode.GIT_PUSH_TIMEOUT,
        "Git commit/push timeout",
        component_name="Doc / Intro (adoc)",
        timeout_seconds=120,
    )
    assert len(result["errors"]) == 2
    assert result["errors"][1]["code"] == "git_push_timeout"
    assert result["errors"][1]["metadata"]["timeout_seconds"] == 120


def test_boost_validation_errors_builds_list() -> None:
    errors = boost_validation_errors(
        [
            (
                BoostEndpointErrorCode.INVALID_LANGUAGE_CODE,
                "add_or_update: each key must be a non-empty language code",
                {"field": "add_or_update", "language": ""},
            ),
            (
                BoostEndpointErrorCode.INVALID_SUBMODULE_LIST,
                "add_or_update: key zh_Hans has an empty list",
                {"field": "add_or_update", "language": "zh_Hans"},
            ),
        ]
    )
    assert len(errors) == 2
    assert errors[0]["code"] == "invalid_language_code"
    assert errors[1]["code"] == "invalid_submodule_list"
    assert errors[1]["metadata"]["language"] == "zh_Hans"


def test_wrap_task_error_wraps_generic_exception() -> None:
    wrapped = wrap_task_error(RuntimeError("db unavailable"))
    assert isinstance(wrapped, BoostEndpointError)
    assert wrapped.code == BoostEndpointErrorCode.TASK_INTERNAL_ERROR
    assert wrapped.metadata == {"exception_type": "RuntimeError"}
    assert str(wrapped) == "db unavailable"


def test_wrap_task_error_passthrough_boost_endpoint_error() -> None:
    original = BoostEndpointError(
        "User 99 not found",
        code=BoostEndpointErrorCode.TASK_USER_NOT_FOUND,
        metadata={"user_id": 99},
    )
    assert wrap_task_error(original) is original


def test_boost_endpoint_error_code_values_are_stable_strings() -> None:
    assert BoostEndpointErrorCode.CLONE_FAILED == "clone_failed"
    assert BoostEndpointErrorCode.TASK_INTERNAL_ERROR.value == "task_internal_error"


def test_boost_endpoint_error_can_be_raised_and_caught() -> None:
    with pytest.raises(BoostEndpointError) as exc_info:
        raise BoostEndpointError(
            "User 7 not found",
            code=BoostEndpointErrorCode.TASK_USER_NOT_FOUND,
            metadata={"user_id": 7},
        )
    assert exc_info.value.code == BoostEndpointErrorCode.TASK_USER_NOT_FOUND
    assert exc_info.value.metadata["user_id"] == 7
