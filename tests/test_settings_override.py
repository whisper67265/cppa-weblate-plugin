# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Tests for ``boost_weblate.settings_override`` (Docker ``exec`` fragment)."""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from boost_weblate.formats import registry

_ENDPOINT_APP_CONFIG = "boost_weblate.endpoint.apps.BoostEndpointConfig"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SETTINGS_OVERRIDE_PATH = _REPO_ROOT / "src/boost_weblate/settings_override.py"


def _exec_settings_override(namespace: dict) -> None:
    exec(
        compile(
            _SETTINGS_OVERRIDE_PATH.read_text(encoding="utf-8"),
            str(_SETTINGS_OVERRIDE_PATH),
            "exec",
        ),
        namespace,
    )


def _plugin_weblate_paths() -> tuple[str, ...]:
    return registry.weblate_class_paths()


def _load_weblate_formats_models_source() -> str:
    spec = importlib.util.find_spec("weblate")
    if spec is None or not spec.submodule_search_locations:
        msg = "Weblate is not installed"
        raise AssertionError(msg)
    path = Path(spec.submodule_search_locations[0]) / "formats" / "models.py"
    return path.read_text(encoding="utf-8")


def test_settings_override_formats_match_ast_parse_of_upstream() -> None:
    from boost_weblate.settings_override import (
        _parse_formatsconf_formats_ast,
        weblate_formats_with_plugin_formats,
    )

    stock = _parse_formatsconf_formats_ast(_load_weblate_formats_models_source())
    got = weblate_formats_with_plugin_formats()
    plugin_paths = _plugin_weblate_paths()
    assert got[: len(stock)] == tuple(stock)
    assert got[len(stock) :] == plugin_paths
    assert len(got) == len(stock) + len(plugin_paths)


def test_settings_override_module_defines_weblate_formats() -> None:
    import boost_weblate.settings_override as so

    assert isinstance(so.WEBLATE_FORMATS, tuple)
    assert so.WEBLATE_FORMATS == so.weblate_formats_with_plugin_formats()


def test_settings_override_source_has_exec_docker_hints() -> None:
    path = (
        Path(__file__).resolve().parents[1] / "src/boost_weblate/settings_override.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "_ENDPOINT_APP_CONFIG" in text
    assert "boost_weblate.endpoint.apps.BoostEndpointConfig" in text
    assert "AppRegistryNotReady" in text or "formats.models" in text


def test_weblate_formats_includes_upstream_and_plugin_formats() -> None:
    from boost_weblate.settings_override import (
        _parse_formatsconf_formats_ast,
        weblate_formats_with_plugin_formats,
    )

    stock = _parse_formatsconf_formats_ast(_load_weblate_formats_models_source())
    paths = list(weblate_formats_with_plugin_formats())
    plugin_paths = _plugin_weblate_paths()
    assert len(paths) >= len(stock)
    assert "weblate.formats.ttkit.PoFormat" in paths
    assert "weblate.formats.ttkit.TBXFormat" in paths
    for plugin_path in plugin_paths:
        assert paths.count(plugin_path) == 1


def test_merge_boost_endpoint_throttle_rates_preserves_upstream() -> None:
    from boost_weblate.settings_override import (
        BOOST_ENDPOINT_THROTTLE_RATES,
        merge_boost_endpoint_throttle_rates,
    )

    merged = merge_boost_endpoint_throttle_rates(
        {"DEFAULT_THROTTLE_RATES": {"user": "1/hour", "anon": "100/day"}}
    )
    rates = merged["DEFAULT_THROTTLE_RATES"]
    assert rates["user"] == "1/hour"
    assert rates["anon"] == "100/day"
    assert rates["info"] == BOOST_ENDPOINT_THROTTLE_RATES["info"]
    assert rates["add-or-update"] == BOOST_ENDPOINT_THROTTLE_RATES["add-or-update"]


def test_allowed_clone_hosts_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOST_ALLOWED_CLONE_HOSTS", raising=False)

    import boost_weblate.settings_override as so

    importlib.reload(so)

    assert so.allowed_clone_hosts() == ["github.com"]
    assert so.ALLOWED_CLONE_HOSTS == ["github.com"]


def test_allowed_clone_hosts_parses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from boost_weblate.settings_override import allowed_clone_hosts

    monkeypatch.setenv("BOOST_ALLOWED_CLONE_HOSTS", "GitHub.com, GitLab.com")
    assert allowed_clone_hosts() == ["github.com", "gitlab.com"]

    monkeypatch.setenv("BOOST_ALLOWED_CLONE_HOSTS", "")
    assert allowed_clone_hosts() == []


def test_boost_task_timeout_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOST_TASK_SOFT_TIME_LIMIT", raising=False)
    monkeypatch.delenv("BOOST_TASK_TIME_LIMIT", raising=False)

    import boost_weblate.settings_override as so

    importlib.reload(so)

    assert so.BOOST_TASK_SOFT_TIME_LIMIT == 1800
    assert so.BOOST_TASK_TIME_LIMIT == 2100


def test_boost_task_timeout_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from boost_weblate.settings_override import boost_task_timeout_settings

    monkeypatch.setenv("BOOST_TASK_SOFT_TIME_LIMIT", "900")
    monkeypatch.setenv("BOOST_TASK_TIME_LIMIT", "1200")
    settings = boost_task_timeout_settings()
    assert settings["soft_time_limit"] == 900
    assert settings["time_limit"] == 1200


def test_boost_task_timeout_settings_rejects_invalid_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boost_weblate.settings_override import boost_task_timeout_settings

    monkeypatch.setenv("BOOST_TASK_SOFT_TIME_LIMIT", "1200")
    monkeypatch.setenv("BOOST_TASK_TIME_LIMIT", "900")
    with pytest.raises(ValueError, match="BOOST_TASK_TIME_LIMIT"):
        boost_task_timeout_settings()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ["django.contrib.auth"],
        lambda: ("django.contrib.auth",),
    ],
    ids=["list", "tuple"],
)
def test_double_exec_does_not_duplicate_installed_apps(
    factory: Callable[[], list[str] | tuple[str, ...]],
) -> None:
    base_apps = factory()
    ns: dict[str, object] = {"INSTALLED_APPS": base_apps}
    _exec_settings_override(ns)
    _exec_settings_override(ns)
    apps = ns["INSTALLED_APPS"]
    assert apps.count(_ENDPOINT_APP_CONFIG) == 1
    assert apps[0] == "django.contrib.auth"
    if isinstance(base_apps, tuple):
        assert isinstance(apps, tuple)


def test_double_exec_does_not_double_ready_hooks() -> None:
    script = textwrap.dedent(
        f"""
        import os
        import sys
        import tempfile
        import types
        from pathlib import Path

        repo = Path({str(_REPO_ROOT)!r})
        sys.path.insert(0, str(repo))
        sys.path.insert(0, str(repo / "src"))

        import weblate.settings_example as _wl_example

        ns: dict[str, object] = {{}}
        for _key, _value in _wl_example.__dict__.items():
            if _key.isupper():
                ns[_key] = _value

        ns["INSTALLED_APPS"] = tuple(
            app
            for app in _wl_example.INSTALLED_APPS
            if app != "django.contrib.postgres"
        )

        _data = tempfile.mkdtemp(prefix="double_exec_settings_")
        ns["DATA_DIR"] = _data
        ns["CACHE_DIR"] = os.path.join(_data, "cache")
        ns["MEDIA_ROOT"] = os.path.join(_data, "media")
        ns["STATIC_ROOT"] = os.path.join(_data, "static")
        for _p in (ns["CACHE_DIR"], ns["MEDIA_ROOT"], ns["STATIC_ROOT"]):
            os.makedirs(_p, exist_ok=True)

        ns["DATABASES"] = {{
            "default": {{
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": os.path.join(_data, "test.sqlite3"),
            }}
        }}
        ns["SITE_DOMAIN"] = "test.invalid"
        ns["DEBUG"] = False
        ns["CELERY_TASK_ALWAYS_EAGER"] = True
        ns["CELERY_BROKER_URL"] = "memory://"
        ns["CELERY_TASK_EAGER_PROPAGATES"] = True
        ns["CELERY_RESULT_BACKEND"] = None
        ns["CACHES"] = {{
            "default": {{"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        }}
        ns["PASSWORD_HASHERS"] = ["django.contrib.auth.hashers.MD5PasswordHasher"]

        override_path = Path({str(_SETTINGS_OVERRIDE_PATH)!r})
        override_code = compile(
            override_path.read_text(encoding="utf-8"),
            str(override_path),
            "exec",
        )
        exec(override_code, ns)
        exec(override_code, ns)

        settings_mod = types.ModuleType("tests._double_exec_settings")
        for _key, _value in ns.items():
            if _key.isupper():
                setattr(settings_mod, _key, _value)
        sys.modules["tests._double_exec_settings"] = settings_mod
        os.environ["DJANGO_SETTINGS_MODULE"] = "tests._double_exec_settings"

        from boost_weblate.endpoint.apps import BoostEndpointConfig

        ready_calls: list[int] = []
        _original_ready = BoostEndpointConfig.ready

        def _counting_ready(self: BoostEndpointConfig) -> None:
            ready_calls.append(1)
            return _original_ready(self)

        BoostEndpointConfig.ready = _counting_ready  # type: ignore[method-assign]

        import django

        django.setup()
        print(f"ready_calls={{len(ready_calls)}}")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ready_calls=1" in result.stdout
