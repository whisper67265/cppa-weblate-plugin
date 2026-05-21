# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import importlib.metadata
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
    assert response.data["version"]
    assert "info" in response.data["capabilities"]
    assert "add-or-update" in response.data["capabilities"]


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


def test_add_or_update_accepts_and_enqueues_like_boost_weblate(
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
    user = User(username="t_user3", pk=42)
    force_authenticate(request, user=user)

    async_result = MagicMock()
    async_result.id = "task-uuid-123"

    delay_mock = MagicMock(return_value=async_result)
    monkeypatch.setattr(
        "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
        delay_mock,
    )

    response = AddOrUpdateView.as_view()(request)
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.data["status"] == "accepted"
    assert response.data["task_id"] == "task-uuid-123"
    assert "background" in response.data["detail"]

    delay_mock.assert_called_once_with(
        organization="o",
        add_or_update={"ja": ["json"]},
        version="v",
        extensions=None,
        user_id=42,
    )


def test_distribution_version_fallback_when_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boost_weblate.endpoint.views as views_mod

    def boom(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(views_mod.importlib.metadata, "version", boom)
    assert views_mod._distribution_version() == "0.0.0"


def test_boost_add_or_update_task_matches_boost_weblate_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task body mirrors boost-weblate: User + BoostComponentService per language."""
    from boost_weblate.endpoint import tasks as tasks_mod

    user = MagicMock()
    get_mock = MagicMock(return_value=user)
    monkeypatch.setattr(tasks_mod.User.objects, "get", get_mock)

    calls: list[tuple[str, list[str]]] = []

    class FakeService:
        def __init__(self, *, organization, lang_code, version, extensions):  # noqa: ANN001
            self.organization = organization
            self.lang_code = lang_code
            self.version = version
            self.extensions = extensions

        def process_all(self, submodules, *, user, request=None):  # noqa: ANN001
            calls.append((self.lang_code, list(submodules)))
            return {"organization": self.organization, "submodules": submodules}

    monkeypatch.setattr(tasks_mod, "BoostComponentService", FakeService)

    result = tasks_mod.boost_add_or_update_task.run(
        organization="org",
        add_or_update={"ja": ["json"], "zh": ["a"]},
        version="boost-1.0",
        extensions=[".md"],
        user_id=7,
    )

    get_mock.assert_called_once_with(pk=7)
    assert calls == [("ja", ["json"]), ("zh", ["a"])]
    assert result["ja"]["submodules"] == ["json"]
    assert result["zh"]["organization"] == "org"


def test_boost_add_or_update_task_propagates_service_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boost_weblate.endpoint import tasks as tasks_mod

    user = MagicMock()
    monkeypatch.setattr(tasks_mod.User.objects, "get", lambda pk: user)

    class BoomService:
        def __init__(self, **_kw):  # noqa: ANN003
            pass

        def process_all(self, _submodules, *, user, request=None):  # noqa: ANN001
            raise RuntimeError("fail")

    monkeypatch.setattr(tasks_mod, "BoostComponentService", BoomService)

    with pytest.raises(RuntimeError, match="fail"):
        tasks_mod.boost_add_or_update_task.run(
            organization="o",
            add_or_update={"en": ["x"]},
            version="v",
            extensions=None,
            user_id=1,
        )
