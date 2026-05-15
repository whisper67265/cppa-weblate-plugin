# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

from django.http import HttpResponse
from django.views.decorators.http import require_GET


@require_GET
def plugin_ping(_request):
    """Minimal health-style endpoint for URL registration smoke tests."""
    return HttpResponse("ok", content_type="text/plain")
