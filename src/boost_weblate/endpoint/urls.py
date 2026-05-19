# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""URL patterns mounted under ``/boost-endpoint/`` on the Weblate site."""

from __future__ import annotations

from django.urls import path

from boost_weblate.endpoint import views

app_name = "boost_weblate"

urlpatterns = [
    path("info/", views.BoostEndpointInfo.as_view(), name="info"),
    path(
        "add-or-update/",
        views.AddOrUpdateView.as_view(),
        name="add-or-update",
    ),
    path("plugin-ping/", views.plugin_ping, name="plugin-ping"),
]
