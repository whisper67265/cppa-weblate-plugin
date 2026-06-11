# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

from django.apps import AppConfig

from boost_weblate.endpoint.weblate_urls_adapter import register_boost_endpoint_urls


def register_plugin_urls() -> None:
    """Register Boost endpoint routes with Weblate.

    Delegates to
    :func:`~boost_weblate.endpoint.weblate_urls_adapter.register_boost_endpoint_urls`,
    which appends a single ``path("boost-endpoint/", ...)`` entry to
    ``weblate.urls.real_patterns`` after fail-fast layout checks.

    Exposed HTTP paths (relative to ``/boost-endpoint/``): ``info/``,
    ``add-or-update/``, and ``plugin-ping/`` (see ``boost_weblate.endpoint.urls``).

    Raises :class:`~boost_weblate.endpoint.weblate_urls_adapter.WeblateUrlLayoutError`
    when Weblate's URL module layout is incompatible.
    """
    register_boost_endpoint_urls()


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
