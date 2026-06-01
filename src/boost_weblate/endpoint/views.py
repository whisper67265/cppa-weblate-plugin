# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import importlib.metadata

from django.http import HttpResponse
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from weblate.api.throttling import UserRateThrottle, patch_throttle_request

from boost_weblate.endpoint.serializers import AddOrUpdateRequestSerializer
from boost_weblate.endpoint.tasks import boost_add_or_update_task

_INFO_CAPABILITIES = (
    "info",
    "add-or-update",
)


def _distribution_version() -> str:
    try:
        return importlib.metadata.version("cppa-weblate-plugin")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


@require_GET
def plugin_ping(_request):
    """Minimal health-style endpoint for URL registration smoke tests."""
    return HttpResponse("ok", content_type="text/plain")


class BoostEndpointInfoThrottle(ScopedRateThrottle):
    @patch_throttle_request
    def allow_request(self, request, view):
        return super().allow_request(request, view)


class AddOrUpdateThrottle(ScopedRateThrottle):
    @patch_throttle_request
    def allow_request(self, request, view):
        return super().allow_request(request, view)


class BoostEndpointInfo(APIView):
    """Boost documentation translation API info."""

    permission_classes = (IsAuthenticated,)
    throttle_scope = "info"
    throttle_classes = (UserRateThrottle, BoostEndpointInfoThrottle)

    def get(self, request, format=None):  # noqa: A002
        """Return module name, version, and supported capabilities."""
        return Response(
            {
                "module": "cppa-weblate-plugin",
                "version": _distribution_version(),
                "capabilities": list(_INFO_CAPABILITIES),
            }
        )


class AddOrUpdateView(APIView):
    """Add or update Boost documentation components."""

    permission_classes = (IsAuthenticated,)
    throttle_scope = "add-or-update"
    throttle_classes = (UserRateThrottle, AddOrUpdateThrottle)

    def post(self, request, format=None):  # noqa: A002
        """
        Create or update Boost documentation components.

        add_or_update is a map: lang_code -> [submodule names]. For each lang_code
        the service runs with that language and its submodule list (clone, scan,
        create/update project and components, add language).

        Heavy work runs in a Celery worker and returns immediately with HTTP 202 and
        task_id so clients can validate the request without waiting for completion.
        """
        serializer = AddOrUpdateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        async_result = boost_add_or_update_task.delay(
            organization=data["organization"],
            add_or_update=data["add_or_update"],
            version=data["version"],
            extensions=data.get("extensions"),
            user_id=request.user.pk,
        )

        return Response(
            {
                "status": "accepted",
                "task_id": str(async_result.id),
                "detail": (
                    "Boost add-or-update is running in the background; "
                    "check Celery logs or task result for completion."
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )
