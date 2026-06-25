# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Tests for ``boost_weblate.settings_override`` (Docker ``exec`` fragment)."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

from boost_weblate.formats import registry


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
