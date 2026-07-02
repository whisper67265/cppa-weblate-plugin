# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import importlib.metadata
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from rest_framework import status
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.throttling import SimpleRateThrottle

from boost_weblate.endpoint.errors import (
    BoostEndpointError,
    BoostEndpointErrorCode,
)
from boost_weblate.endpoint.views import (
    AddOrUpdateView,
    BoostEndpointInfo,
    plugin_ping,
)

User = get_user_model()

_ADD_OR_UPDATE_BODY = {
    "organization": "o",
    "version": "v",
    "add_or_update": {"zh_Hans": ["json"]},
}

_TASK_KWARGS = {
    "organization": "org",
    "add_or_update": {"zh_Hans": ["a"], "ja": ["json"]},
    "version": "boost-1.0",
    "extensions": [".md"],
    "user_id": 7,
}


class _FakeLock:
    """Redis lock stub that always acquires."""

    def __init__(self) -> None:
        self.released = False

    def acquire(
        self, blocking: bool = True, blocking_timeout: float | None = None
    ) -> bool:
        return True

    def release(self) -> None:
        self.released = True


@pytest.fixture(autouse=True)
def _mock_task_lock_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: task lock always acquired unless a test overrides Lock."""

    def _fake_lock(*_args, **_kwargs) -> _FakeLock:
        return _FakeLock()

    monkeypatch.setattr("boost_weblate.utils.task_lock.Lock", _fake_lock)
    monkeypatch.setattr(
        "boost_weblate.utils.task_lock._get_redis_client",
        lambda: MagicMock(),
    )


def _throttle_rest_framework(**rate_overrides: str) -> dict:
    rf = deepcopy(settings.REST_FRAMEWORK)
    rates = dict(rf.get("DEFAULT_THROTTLE_RATES", {}))
    rates.update(rate_overrides)
    rf["DEFAULT_THROTTLE_RATES"] = rates
    return rf


@contextmanager
def _isolated_throttle_rates(rest_framework: dict):
    """Apply REST_FRAMEWORK throttle rates; restore rates and cache after use."""
    with override_settings(REST_FRAMEWORK=rest_framework):
        orig = dict(SimpleRateThrottle.THROTTLE_RATES or {})
        cache.clear()
        try:
            api_settings.reload()
            SimpleRateThrottle.THROTTLE_RATES = dict(
                api_settings.DEFAULT_THROTTLE_RATES or {}
            )
            yield
        finally:
            cache.clear()
            SimpleRateThrottle.THROTTLE_RATES = orig
            api_settings.reload()


@pytest.fixture
def scoped_low_throttle_rates():
    rest_framework = _throttle_rest_framework(
        user="10000/hour",
        info="2/minute",
        **{"add-or-update": "2/minute"},
    )
    with _isolated_throttle_rates(rest_framework):
        yield


@pytest.fixture
def user_low_throttle_rates():
    rest_framework = _throttle_rest_framework(
        user="2/minute",
        info="10000/minute",
    )
    with _isolated_throttle_rates(rest_framework):
        yield


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
            "add_or_update": {"zh_Hans": ["json"]},
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
    errors = response.data["errors"]
    assert isinstance(errors, list)
    assert all("code" in e and "message" in e and "metadata" in e for e in errors)
    assert BoostEndpointErrorCode.REQUIRED_FIELD.value in [e["code"] for e in errors]


def test_add_or_update_accepts_and_enqueues_like_boost_weblate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = APIRequestFactory()
    request = factory.post(
        "/add-or-update/",
        {
            "organization": "o",
            "version": "v",
            "add_or_update": {"zh_Hans": ["json"]},
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
        add_or_update={"zh_Hans": ["json"]},
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
        add_or_update={"zh_Hans": ["a"], "ja": ["json"]},
        version="boost-1.0",
        extensions=[".md"],
        user_id=7,
    )

    get_mock.assert_called_once_with(pk=7)
    assert calls == [("zh_Hans", ["a"]), ("ja", ["json"])]
    assert result["zh_Hans"]["organization"] == "org"
    assert result["ja"]["submodules"] == ["json"]


def test_boost_add_or_update_task_declares_celery_time_limits() -> None:
    from boost_weblate.endpoint import tasks as tasks_mod
    from boost_weblate.settings_override import (
        BOOST_TASK_SOFT_TIME_LIMIT,
        BOOST_TASK_TIME_LIMIT,
    )

    task = tasks_mod.boost_add_or_update_task
    assert task.soft_time_limit == BOOST_TASK_SOFT_TIME_LIMIT
    assert task.time_limit == BOOST_TASK_TIME_LIMIT


def test_boost_add_or_update_task_soft_time_limit_raises_task_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from celery.exceptions import SoftTimeLimitExceeded

    from boost_weblate.endpoint import tasks as tasks_mod
    from boost_weblate.settings_override import BOOST_TASK_SOFT_TIME_LIMIT

    user = MagicMock()
    monkeypatch.setattr(tasks_mod.User.objects, "get", lambda pk: user)

    class TimeoutService:
        def __init__(self, **_kw):  # noqa: ANN003
            pass

        def process_all(self, _submodules, *, user, request=None):  # noqa: ANN001
            raise SoftTimeLimitExceeded()

    monkeypatch.setattr(tasks_mod, "BoostComponentService", TimeoutService)

    with pytest.raises(BoostEndpointError) as exc_info:
        tasks_mod.boost_add_or_update_task.run(
            organization="o",
            add_or_update={"en": ["x"]},
            version="v",
            extensions=None,
            user_id=1,
        )

    assert exc_info.value.code == BoostEndpointErrorCode.TASK_TIMEOUT
    assert exc_info.value.metadata["soft_time_limit"] == BOOST_TASK_SOFT_TIME_LIMIT
    assert "time_limit" in exc_info.value.metadata


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

    with pytest.raises(BoostEndpointError) as exc_info:
        tasks_mod.boost_add_or_update_task.run(
            organization="o",
            add_or_update={"en": ["x"]},
            version="v",
            extensions=None,
            user_id=1,
        )
    assert exc_info.value.code == BoostEndpointErrorCode.TASK_INTERNAL_ERROR


def test_boost_add_or_update_task_duplicate_raises_task_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boost_weblate.endpoint import tasks as tasks_mod

    user = MagicMock()
    monkeypatch.setattr(tasks_mod.User.objects, "get", lambda pk: user)

    process_calls = 0

    class FakeService:
        def __init__(self, **_kw):  # noqa: ANN003
            pass

        def process_all(self, _submodules, *, user, request=None):  # noqa: ANN001
            nonlocal process_calls
            process_calls += 1
            return {}

    monkeypatch.setattr(tasks_mod, "BoostComponentService", FakeService)

    acquire_results = iter([True, False])

    class DuplicateFakeLock:
        def acquire(
            self, blocking: bool = True, blocking_timeout: float | None = None
        ) -> bool:
            return next(acquire_results)

        def release(self) -> None:
            pass

    monkeypatch.setattr(
        "boost_weblate.utils.task_lock.Lock",
        lambda *_a, **_k: DuplicateFakeLock(),
    )

    tasks_mod.boost_add_or_update_task.run(**_TASK_KWARGS)

    with pytest.raises(BoostEndpointError) as exc_info:
        tasks_mod.boost_add_or_update_task.run(**_TASK_KWARGS)

    assert exc_info.value.code == BoostEndpointErrorCode.TASK_DUPLICATE
    assert "lock_key" in exc_info.value.metadata
    assert process_calls == 2


def test_boost_add_or_update_task_lock_released_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boost_weblate.endpoint import tasks as tasks_mod

    user = MagicMock()
    monkeypatch.setattr(tasks_mod.User.objects, "get", lambda pk: user)

    class FakeService:
        def __init__(self, **_kw):  # noqa: ANN003
            pass

        def process_all(self, _submodules, *, user, request=None):  # noqa: ANN001
            return {}

    monkeypatch.setattr(tasks_mod, "BoostComponentService", FakeService)

    lock = _FakeLock()
    monkeypatch.setattr(
        "boost_weblate.utils.task_lock.Lock",
        lambda *_a, **_k: lock,
    )

    tasks_mod.boost_add_or_update_task.run(**_TASK_KWARGS)
    assert lock.released is True


def test_build_add_or_update_lock_key_is_stable() -> None:
    from boost_weblate.utils.task_lock import build_add_or_update_lock_key

    key_a = build_add_or_update_lock_key(
        organization="org",
        version="boost-1.0",
        extensions=[".md", ".adoc"],
        add_or_update={"ja": ["json", "asio"], "zh_Hans": ["a"]},
        user_id=1,
    )
    key_b = build_add_or_update_lock_key(
        organization="org",
        version="boost-1.0",
        extensions=[".adoc", ".md"],
        add_or_update={"zh_Hans": ["a"], "ja": ["asio", "json"]},
        user_id=99,
    )
    key_c = build_add_or_update_lock_key(
        organization="org",
        version="boost-2.0",
        extensions=[".md", ".adoc"],
        add_or_update={"ja": ["json", "asio"], "zh_Hans": ["a"]},
        user_id=1,
    )

    assert key_a == key_b
    assert key_a != key_c


def test_boost_endpoint_info_returns_429_when_scoped_throttled(
    scoped_low_throttle_rates,
) -> None:
    factory = APIRequestFactory()
    user = User(username="t_throttle_info", pk=101)
    view = BoostEndpointInfo.as_view()

    for _ in range(2):
        request = factory.get("/info/")
        force_authenticate(request, user=user)
        response = view(request)
        assert response.status_code == status.HTTP_200_OK

    request = factory.get("/info/")
    force_authenticate(request, user=user)
    response = view(request)
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Retry-After" in response
    assert int(response["Retry-After"]) > 0


def test_add_or_update_returns_429_when_scoped_throttled(
    scoped_low_throttle_rates,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delay_mock = MagicMock(return_value=MagicMock(id="task-uuid"))
    monkeypatch.setattr(
        "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
        delay_mock,
    )

    factory = APIRequestFactory()
    user = User(username="t_throttle_aou", pk=102)
    view = AddOrUpdateView.as_view()

    for _ in range(2):
        request = factory.post("/add-or-update/", _ADD_OR_UPDATE_BODY, format="json")
        force_authenticate(request, user=user)
        response = view(request)
        assert response.status_code == status.HTTP_202_ACCEPTED

    request = factory.post("/add-or-update/", _ADD_OR_UPDATE_BODY, format="json")
    force_authenticate(request, user=user)
    response = view(request)
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Retry-After" in response
    assert int(response["Retry-After"]) > 0
    assert delay_mock.call_count == 2


def test_boost_endpoint_info_user_throttle_can_429(
    user_low_throttle_rates,
) -> None:
    factory = APIRequestFactory()
    user = User(username="t_user_throttle", pk=103)
    view = BoostEndpointInfo.as_view()

    for _ in range(2):
        request = factory.get("/info/")
        force_authenticate(request, user=user)
        response = view(request)
        assert response.status_code == status.HTTP_200_OK

    request = factory.get("/info/")
    force_authenticate(request, user=user)
    response = view(request)
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Retry-After" in response


# ---------------------------------------------------------------------------
# Adversarial / trust-boundary tests
# ---------------------------------------------------------------------------

_SQL_INJECTION_PAYLOADS = (
    "'; DROP TABLE auth_user; --",
    "1 OR 1=1",
    "' UNION SELECT",
)

_PATH_TRAVERSAL_PAYLOADS = (
    "../evil",
    "org/../../etc",
)

_CONTROL_BYTE_PAYLOADS = (
    "org\x00evil",
    "bad\r\norg",
)

_VALID_ADD_OR_UPDATE_BODY = {
    "organization": "CppDigest",
    "version": "boost-1.90.0",
    "add_or_update": {"zh_Hans": ["json"]},
}


class TestPluginPingAdversarial:
    def test_post_returns_405(self) -> None:
        request = RequestFactory().post("/plugin-ping/")
        response = plugin_ping(request)
        assert response.status_code == 405

    def test_oversized_query_string_still_ok(self) -> None:
        query = "x" * 8192
        request = RequestFactory().get("/plugin-ping/", data={"q": query})
        response = plugin_ping(request)
        assert response.status_code == 200
        assert response.content == b"ok"

    def test_sql_injection_query_param_still_ok(self) -> None:
        request = RequestFactory().get("/plugin-ping/", data={"x": "'; DROP TABLE--"})
        response = plugin_ping(request)
        assert response.status_code == 200
        assert response.content == b"ok"


class TestBoostEndpointInfoAdversarial:
    def test_post_returns_405(self) -> None:
        factory = APIRequestFactory()
        request = factory.post(
            "/info/",
            {"filter": "' OR 1=1--"},
            format="json",
        )
        user = User(username="t_adv_info", pk=201)
        force_authenticate(request, user=user)
        response = BoostEndpointInfo.as_view()(request)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_anonymous_malformed_auth_token_returns_401(
        self,
        weblate_anonymous_user_no_db: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from rest_framework.authentication import TokenAuthentication
        from rest_framework.exceptions import AuthenticationFailed

        def reject_invalid_token(_self, request):  # noqa: ANN001
            auth = request.META.get("HTTP_AUTHORIZATION", "")
            if auth.startswith("Token "):
                raise AuthenticationFailed("Invalid token.")
            return None

        monkeypatch.setattr(TokenAuthentication, "authenticate", reject_invalid_token)

        factory = APIRequestFactory()
        request = factory.get(
            "/info/",
            HTTP_AUTHORIZATION="Token not-a-valid-token",
        )
        response = BoostEndpointInfo.as_view()(request)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_sql_injection_query_param_ignored(self) -> None:
        factory = APIRequestFactory()
        request = factory.get("/info/", data={"filter": "' OR 1=1--"})
        user = User(username="t_adv_info2", pk=202)
        force_authenticate(request, user=user)
        response = BoostEndpointInfo.as_view()(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["module"] == "cppa-weblate-plugin"
        assert "info" in response.data["capabilities"]


class TestAddOrUpdateAdversarial:
    @pytest.fixture(autouse=True)
    def _high_throttle_limits(self):
        rest_framework = _throttle_rest_framework(
            user="10000/hour",
            info="10000/minute",
            **{"add-or-update": "10000/hour"},
        )
        with _isolated_throttle_rates(rest_framework):
            yield

    @staticmethod
    def _authenticated_post(body, *, format="json", content_type=None, data=None):
        factory = APIRequestFactory()
        kwargs: dict = {}
        if content_type is not None:
            kwargs["content_type"] = content_type
        if data is not None:
            request = factory.post("/add-or-update/", data=data, **kwargs)
        else:
            request = factory.post("/add-or-update/", body, format=format, **kwargs)
        user = User(username="t_adv_aou", pk=301)
        force_authenticate(request, user=user)
        return request, user

    def test_non_json_body_rejected_without_enqueue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        request, _ = self._authenticated_post(
            None, content_type="application/json", data="not-json"
        )
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
        delay_mock.assert_not_called()

    def test_add_or_update_string_type_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {
            **_VALID_ADD_OR_UPDATE_BODY,
            "add_or_update": "not-a-dict",
        }
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "errors" in response.data
        delay_mock.assert_not_called()

    def test_extensions_dict_type_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {
            **_VALID_ADD_OR_UPDATE_BODY,
            "extensions": {"not": "a-list"},
        }
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "errors" in response.data
        delay_mock.assert_not_called()

    def test_oversized_organization_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {
            **_VALID_ADD_OR_UPDATE_BODY,
            "organization": "o" * 10_000,
        }
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        codes = [e["code"] for e in response.data["errors"]]
        assert BoostEndpointErrorCode.INVALID_CLONE_URL.value in codes
        delay_mock.assert_not_called()

    def test_oversized_version_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {
            **_VALID_ADD_OR_UPDATE_BODY,
            "version": "v" * 10_000,
        }
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        codes = [e["code"] for e in response.data["errors"]]
        assert BoostEndpointErrorCode.INVALID_CLONE_URL.value in codes
        delay_mock.assert_not_called()

    def test_oversized_add_or_update_lang_count_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from boost_weblate.endpoint.validators import MAX_ADD_OR_UPDATE_LANGS

        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        langs = {f"lang{i}": ["json"] for i in range(MAX_ADD_OR_UPDATE_LANGS + 1)}
        body = {**_VALID_ADD_OR_UPDATE_BODY, "add_or_update": langs}
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        codes = [e["code"] for e in response.data["errors"]]
        assert BoostEndpointErrorCode.INVALID_LANGUAGE_CODE.value in codes
        delay_mock.assert_not_called()

    @pytest.mark.parametrize("payload", _SQL_INJECTION_PAYLOADS)
    def test_sql_injection_in_organization_rejected(
        self, payload: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {**_VALID_ADD_OR_UPDATE_BODY, "organization": payload}
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        codes = [e["code"] for e in response.data["errors"]]
        assert BoostEndpointErrorCode.INVALID_CLONE_URL.value in codes
        delay_mock.assert_not_called()

    @pytest.mark.parametrize("payload", _PATH_TRAVERSAL_PAYLOADS)
    def test_path_traversal_in_organization_rejected(
        self, payload: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {**_VALID_ADD_OR_UPDATE_BODY, "organization": payload}
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        delay_mock.assert_not_called()

    @pytest.mark.parametrize("payload", _SQL_INJECTION_PAYLOADS)
    def test_sql_injection_in_version_rejected(
        self, payload: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {**_VALID_ADD_OR_UPDATE_BODY, "version": payload}
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        delay_mock.assert_not_called()

    @pytest.mark.parametrize("payload", _SQL_INJECTION_PAYLOADS)
    def test_sql_injection_in_lang_code_rejected(
        self, payload: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {
            **_VALID_ADD_OR_UPDATE_BODY,
            "add_or_update": {payload: ["json"]},
        }
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        codes = [e["code"] for e in response.data["errors"]]
        assert BoostEndpointErrorCode.INVALID_LANGUAGE_CODE.value in codes
        delay_mock.assert_not_called()

    @pytest.mark.parametrize("payload", _CONTROL_BYTE_PAYLOADS)
    def test_control_bytes_in_organization_rejected(
        self, payload: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        body = {**_VALID_ADD_OR_UPDATE_BODY, "organization": payload}
        request, _ = self._authenticated_post(body)
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        delay_mock.assert_not_called()


class TestOrmTrustBoundary:
    @pytest.fixture(autouse=True)
    def _high_throttle_limits(self):
        rest_framework = _throttle_rest_framework(
            user="10000/hour",
            info="10000/minute",
            **{"add-or-update": "10000/hour"},
        )
        with _isolated_throttle_rates(rest_framework):
            yield

    def test_rejected_injection_never_reaches_celery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock()
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/add-or-update/",
            {
                "organization": "'; DROP TABLE--",
                "version": "boost-1.0",
                "add_or_update": {"zh_Hans": ["json"]},
            },
            format="json",
        )
        force_authenticate(request, user=User(username="t_orm", pk=401))
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        delay_mock.assert_not_called()

    def test_valid_payload_passes_literal_strings_to_celery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock(return_value=MagicMock(id="task-orm"))
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/add-or-update/",
            _VALID_ADD_OR_UPDATE_BODY,
            format="json",
        )
        force_authenticate(request, user=User(username="t_orm2", pk=402))
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_202_ACCEPTED
        delay_mock.assert_called_once_with(
            organization="CppDigest",
            add_or_update={"zh_Hans": ["json"]},
            version="boost-1.90.0",
            extensions=None,
            user_id=402,
        )

    def test_user_id_from_auth_not_request_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delay_mock = MagicMock(return_value=MagicMock(id="task-uid"))
        monkeypatch.setattr(
            "boost_weblate.endpoint.views.boost_add_or_update_task.delay",
            delay_mock,
        )
        factory = APIRequestFactory()
        body = {
            **_VALID_ADD_OR_UPDATE_BODY,
            "user_id": 99999,
        }
        request = factory.post("/add-or-update/", body, format="json")
        force_authenticate(request, user=User(username="t_orm3", pk=403))
        response = AddOrUpdateView.as_view()(request)
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert delay_mock.call_args.kwargs["user_id"] == 403

    def test_language_get_receives_literal_lang_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from weblate.lang.models import Language

        from boost_weblate.endpoint import tasks as tasks_mod

        lang_code = "zh_Hans"
        user = MagicMock()
        monkeypatch.setattr(tasks_mod.User.objects, "get", lambda pk: user)

        lang_get_mock = MagicMock()
        monkeypatch.setattr(Language.objects, "get", lang_get_mock)

        class FakeService:
            def __init__(self, **kw):  # noqa: ANN003
                self.lang_code = kw["lang_code"]
                self.organization = kw["organization"]
                self.version = kw["version"]
                self.extensions = kw["extensions"]

            def process_all(self, _submodules, *, user, request=None):  # noqa: ANN001
                Language.objects.get(code=self.lang_code)
                return {}

        monkeypatch.setattr(tasks_mod, "BoostComponentService", FakeService)

        tasks_mod.boost_add_or_update_task.run(
            organization="org",
            add_or_update={lang_code: ["json"]},
            version="boost-1.0",
            extensions=None,
            user_id=1,
        )

        lang_get_mock.assert_called_once_with(code=lang_code)

    def test_get_or_create_project_uses_literal_lang_in_slug(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from boost_weblate.endpoint import services as services_mod

        lang_code = "zh_Hans"
        slug_calls: list[str] = []

        def capture_get_or_create(*, slug: str, defaults: dict):
            slug_calls.append(slug)
            project = MagicMock()
            project.post_create = MagicMock()
            return project, True

        monkeypatch.setattr(
            services_mod.Project.objects, "get_or_create", capture_get_or_create
        )

        service = services_mod.BoostComponentService(
            organization="org",
            lang_code=lang_code,
            version="boost-1.0",
            extensions=None,
        )
        service.get_or_create_project("json", user=MagicMock())

        assert slug_calls == [f"boost-json-documentation-{lang_code}"]
