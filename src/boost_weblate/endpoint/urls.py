# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""URL patterns mounted under ``/boost-endpoint/`` on the Weblate site."""

from __future__ import annotations

from django.urls import path

from boost_weblate.endpoint import views

app_name = "boost_endpoint"

urlpatterns = [
    path("plugin-ping/", views.plugin_ping, name="plugin-ping"),
]
