# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import logging

from django.apps import AppConfig
from django.urls import include, path

logger = logging.getLogger(__name__)

_PLUGIN_URLS_ATTR = "_cppa_boost_weblate_urls_registered"


def register_plugin_urls() -> None:
    """Append this app's routes to Weblate's pattern list.

    This is the supported plugin path: at process
    startup, append a single ``path("boost-endpoint/", ...)`` entry to
    ``weblate.urls.real_patterns`` so routes stay under Weblate's ``URL_PREFIX``
    handling.

    Exposed HTTP paths (relative to ``/boost-endpoint/``): ``info/``,
    ``add-or-update/``, and ``plugin-ping/`` (see ``boost_weblate.endpoint.urls``).

    Weblate builds ``urlpatterns`` from module-level ``real_patterns`` (see
    ``weblate.urls``). Optional plugins append to ``real_patterns`` before
    the ``URL_PREFIX`` wrapper is applied, so mutating that list keeps routes
    consistent when a path prefix is configured.
    """
    try:
        import weblate.urls as wl_urls  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        logger.debug(
            "boost_weblate.endpoint: skipping URL registration (import error: %s)",
            exc,
        )
        return

    if getattr(wl_urls, _PLUGIN_URLS_ATTR, False):
        return

    if not hasattr(wl_urls, "real_patterns"):
        logger.warning(
            "boost_weblate.endpoint: weblate.urls has no real_patterns; "
            "URL registration skipped (unexpected Weblate layout)."
        )
        return

    wl_urls.real_patterns.append(
        path(
            "boost-endpoint/",
            include(("boost_weblate.endpoint.urls", "boost_endpoint")),
        ),
    )
    setattr(wl_urls, _PLUGIN_URLS_ATTR, True)


class BoostEndpointConfig(AppConfig):
    """Django app config for the Boost documentation translation HTTP API.

    On load, :meth:`ready` calls :func:`register_plugin_urls` once (idempotent) to
    mount ``/boost-endpoint/`` with ``info/``, ``add-or-update/``, and
    ``plugin-ping/`` routes (application namespace ``boost_endpoint`` for URL
    reversing).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "boost_weblate.endpoint"
    label = "boost_endpoint"
    verbose_name = "Boost documentation translation API"

    def ready(self) -> None:
        """Register plugin URL patterns with Weblate.

        Delegates to :func:`register_plugin_urls`.
        """
        register_plugin_urls()
