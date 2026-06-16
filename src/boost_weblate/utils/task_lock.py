# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Redis distributed lock decorator for Celery task deduplication."""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from django_redis import get_redis_connection
from redis.exceptions import LockError
from redis.lock import Lock

from boost_weblate.endpoint.errors import BoostEndpointError, BoostEndpointErrorCode
from boost_weblate.settings_override import (
    BOOST_TASK_LOCK_ON_CONFLICT,
    BOOST_TASK_LOCK_TIMEOUT,
    BOOST_TASK_LOCK_WAIT_TIMEOUT,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_ADD_OR_UPDATE_TASK_NAME = "boost_add_or_update_task"


def _get_redis_client():
    return get_redis_connection("default")


def build_add_or_update_lock_key(**task_kwargs: Any) -> str:
    """Build a stable Redis lock key from add-or-update task kwargs."""
    add_or_update = task_kwargs["add_or_update"]
    canonical_add_or_update = {
        lang: sorted(submodules) for lang, submodules in sorted(add_or_update.items())
    }
    extensions = task_kwargs.get("extensions")
    if extensions is not None:
        extensions = sorted(extensions)
    payload = {
        "organization": task_kwargs["organization"],
        "version": task_kwargs["version"],
        "extensions": extensions,
        "add_or_update": canonical_add_or_update,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[
        :32
    ]
    return f"boost_weblate:task_lock:{_ADD_OR_UPDATE_TASK_NAME}:{digest}"


def redis_task_lock(
    key_builder: Callable[..., str],
    *,
    timeout: int | None = None,
    on_conflict: str | None = None,
    wait_timeout: int | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Acquire a Redis lock before running a Celery task body."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = key_builder(**kwargs)
            client = _get_redis_client()
            lock_ttl = timeout if timeout is not None else BOOST_TASK_LOCK_TIMEOUT
            conflict_mode = (
                on_conflict if on_conflict is not None else BOOST_TASK_LOCK_ON_CONFLICT
            )
            wait_limit = (
                wait_timeout
                if wait_timeout is not None
                else BOOST_TASK_LOCK_WAIT_TIMEOUT
            )

            lock = Lock(client, name=key, timeout=lock_ttl, thread_local=False)

            if conflict_mode == "wait":
                acquired = lock.acquire(blocking=True, blocking_timeout=wait_limit)
            else:
                acquired = lock.acquire(blocking=False)

            if not acquired:
                logger.info(
                    "Duplicate task rejected (lock held): lock_key=%s",
                    key,
                )
                raise BoostEndpointError(
                    "Duplicate add-or-update task already running",
                    code=BoostEndpointErrorCode.TASK_DUPLICATE,
                    metadata={"lock_key": key},
                )

            try:
                return func(*args, **kwargs)
            finally:
                try:
                    lock.release()
                except LockError:
                    pass

        return wrapper

    return decorator
