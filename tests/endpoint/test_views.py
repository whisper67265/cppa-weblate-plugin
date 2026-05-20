# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from boost_weblate.endpoint.views import (
    AddOrUpdateView,
    BoostEndpointInfo,
    plugin_ping,
)

User = get_user_model()


@pytest.fixture
def weblate_anonymous_user_no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Weblate's default anonymous user loads from DB; tests do not run migrations."""
    monkeypatch.setattr(
        "weblate.auth.models.get_anonymous",
        lambda: AnonymousUser(),
    )


def test_plugin_ping_returns_plain_ok() -> None:
    request = RequestFactory().get("/plugin-ping/")
    response = plugin_ping(request)
    assert response.status_code == 200
    assert response.content == b"ok"
    assert response["Content-Type"].startswith("text/plain")


def test_boost_endpoint_info_requires_authentication(
    weblate_anonymous_user_no_db: None,
) -> None:
    factory = APIRequestFactory()
    request = factory.get("/info/")
    response = BoostEndpointInfo.as_view()(request)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_boost_endpoint_info_returns_payload_when_authenticated() -> None:
    factory = APIRequestFactory()
    request = factory.get("/info/")
    user = User(username="t_user")
    force_authenticate(request, user=user)
    response = BoostEndpointInfo.as_view()(request)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["module"] == "cppa-weblate-plugin"
    assert "Boost documentation translation API" in response.data["description"]


def test_add_or_update_requires_authentication(
    weblate_anonymous_user_no_db: None,
) -> None:
    factory = APIRequestFactory()
    request = factory.post(
        "/add-or-update/",
        {
            "organization": "o",
            "version": "v",
            "add_or_update": {"ja": ["json"]},
        },
        format="json",
    )
    response = AddOrUpdateView.as_view()(request)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_add_or_update_validation_error() -> None:
    factory = APIRequestFactory()
    request = factory.post("/add-or-update/", {}, format="json")
    user = User(username="t_user2")
    force_authenticate(request, user=user)
    response = AddOrUpdateView.as_view()(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "errors" in response.data


def test_add_or_update_returns_not_implemented_until_service_exists() -> None:
    factory = APIRequestFactory()
    request = factory.post(
        "/add-or-update/",
        {
            "organization": "o",
            "version": "v",
            "add_or_update": {"ja": ["json"]},
        },
        format="json",
    )
    user = User(username="t_user3")
    force_authenticate(request, user=user)
    response = AddOrUpdateView.as_view()(request)
    assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
    assert "detail" in response.data
    assert response.data["organization"] == "o"
    assert response.data["languages"]["ja"]["status"] == "error"


def test_add_or_update_internal_error_is_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = APIRequestFactory()
    request = factory.post(
        "/add-or-update/",
        {
            "organization": "o",
            "version": "v",
            "add_or_update": {"ja": ["json"]},
        },
        format="json",
    )
    user = User(username="t_user4")
    force_authenticate(request, user=user)

    def boom(*_a, **_kw):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(
        "boost_weblate.endpoint.views.BoostComponentService",
        MagicMock(side_effect=boom),
    )
    response = AddOrUpdateView.as_view()(request)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.data["error"] == "Internal server error"
    assert response.data["organization"] == "o"
    assert response.data["languages"]["ja"]["status"] == "error"
