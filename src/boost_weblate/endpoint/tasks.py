# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Celery tasks for Boost documentation add-or-update (async HTTP handling)."""

from __future__ import annotations

from typing import Any

from weblate.auth.models import AuthenticatedHttpRequest, User
from weblate.utils.celery import app

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

    Exceptions propagate so Celery marks the task failed and monitoring can alert.
    """
    user = User.objects.get(pk=user_id)
    request = AuthenticatedHttpRequest()
    request.user = user

    results: dict[str, Any] = {}
    for lang_code, submodules in add_or_update.items():
        service = BoostComponentService(
            organization=organization,
            lang_code=lang_code,
            version=version,
            extensions=extensions,
        )
        results[lang_code] = service.process_all(submodules, user=user, request=request)
    return results
