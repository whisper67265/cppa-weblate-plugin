# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Service layer for the Boost documentation translation API."""

from __future__ import annotations

from typing import Any


class BoostComponentService:
    """Service for managing Boost documentation components (internal Django usage).

    Full ORM-backed implementation is planned; callers receive
    :class:`NotImplementedError` from :meth:`process_all` until that work lands.
    """

    def __init__(
        self,
        *,
        organization: str,
        lang_code: str,
        version: str,
        extensions: list[str] | None = None,
    ) -> None:
        self.organization = organization
        self.lang_code = lang_code
        self.version = version
        self.extensions = extensions

    def process_all(
        self,
        submodules: list[str],
        *,
        user: Any,
        request: Any = None,
    ) -> dict[str, Any]:
        """Clone, scan, and create/update Weblate projects and components."""
        raise NotImplementedError(
            "BoostComponentService.process_all is not implemented in this plugin "
            "release; it will be added in a follow-up change."
        )
