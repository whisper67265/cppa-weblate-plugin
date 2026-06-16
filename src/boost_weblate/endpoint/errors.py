# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Structured error taxonomy for the Boost documentation translation API."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from weblate.trans.exceptions import WeblateError


class BoostEndpointErrorCode(StrEnum):
    """Stable machine-readable error codes for Boost endpoint failures."""

    INVALID_SUBMODULE = "invalid_submodule"
    INVALID_CLONE_URL = "invalid_clone_url"
    CLONE_FAILED = "clone_failed"
    NO_DOCUMENTATION_FILES = "no_documentation_files"
    PERMISSION_DENIED = "permission_denied"
    PROJECT_CREATE_FAILED = "project_create_failed"
    COMPONENT_DELETE_FAILED = "component_delete_failed"
    FILE_REMOVE_FAILED = "file_remove_failed"
    GIT_PUSH_FAILED = "git_push_failed"
    GIT_PUSH_TIMEOUT = "git_push_timeout"
    ALL_COMPONENTS_FAILED = "all_components_failed"
    INVALID_LANGUAGE_CODE = "invalid_language_code"
    INVALID_SUBMODULE_LIST = "invalid_submodule_list"
    REQUIRED_FIELD = "required_field"
    TASK_USER_NOT_FOUND = "task_user_not_found"
    TASK_INTERNAL_ERROR = "task_internal_error"


class BoostEndpointError(WeblateError):
    """Structured Boost endpoint error (subclass of Weblate's base error type)."""

    def __init__(
        self,
        message: str,
        *,
        code: BoostEndpointErrorCode | str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = BoostEndpointErrorCode(code)
        self.metadata = dict(metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": str(self.args[0]),
            "metadata": self.metadata,
        }


def to_error_dict(
    code: BoostEndpointErrorCode | str,
    message: str,
    **metadata: Any,
) -> dict[str, Any]:
    """Build a JSON-serializable error dict without raising."""
    return BoostEndpointError(message, code=code, metadata=metadata).to_dict()


def append_error(
    result: dict[str, Any],
    code: BoostEndpointErrorCode | str,
    message: str,
    **metadata: Any,
) -> None:
    """Append a structured error to a service result's ``errors`` list."""
    result.setdefault("errors", []).append(to_error_dict(code, message, **metadata))


def boost_validation_errors(
    items: list[tuple[BoostEndpointErrorCode | str, str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Build a unified error list from validation failure tuples."""
    return [
        to_error_dict(code, message, **metadata) for code, message, metadata in items
    ]


def wrap_task_error(exc: BaseException) -> BoostEndpointError:
    """Wrap an unexpected task exception as a structured BoostEndpointError."""
    if isinstance(exc, BoostEndpointError):
        return exc
    return BoostEndpointError(
        str(exc),
        code=BoostEndpointErrorCode.TASK_INTERNAL_ERROR,
        metadata={"exception_type": type(exc).__name__},
    )
