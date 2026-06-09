# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Celery tasks for Boost documentation add-or-update (async HTTP handling)."""

from __future__ import annotations

from typing import Any

from weblate.auth.models import AuthenticatedHttpRequest, User
from weblate.utils.celery import app
from weblate.utils.errors import report_error

from boost_weblate.endpoint.errors import (
    BoostEndpointError,
    BoostEndpointErrorCode,
    wrap_task_error,
)
from boost_weblate.endpoint.services import BoostComponentService


@app.task(trail=False)
def boost_add_or_update_task(
    *,
    organization: str,
    add_or_update: dict[str, list[str]],
    version: str,
    extensions: list[str] | None,
    user_id: int,
) -> dict[str, Any]:
    """
    Run BoostComponentService for each language (same logic as synchronous POST).

    Fatal failures raise BoostEndpointError (WeblateError subclass) so Celery
    marks the task failed with a typed, code-bearing exception for monitoring.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist as exc:
        raise BoostEndpointError(
            f"User {user_id} not found",
            code=BoostEndpointErrorCode.TASK_USER_NOT_FOUND,
            metadata={"user_id": user_id},
        ) from exc

    request = AuthenticatedHttpRequest()
    request.user = user

    try:
        results: dict[str, Any] = {}
        for lang_code, submodules in add_or_update.items():
            service = BoostComponentService(
                organization=organization,
                lang_code=lang_code,
                version=version,
                extensions=extensions,
            )
            results[lang_code] = service.process_all(
                submodules, user=user, request=request
            )
        return results
    except BoostEndpointError:
        raise
    except Exception as exc:
        report_error(cause="Boost add-or-update task")
        raise wrap_task_error(exc) from exc
