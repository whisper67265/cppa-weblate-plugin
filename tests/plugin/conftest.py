# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Shared fixtures for plugin tests (smoke + functional)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.plugin.lib.docker_exec import docker_exec_python, docker_exec_read_file
from tests.plugin.lib.gh_repo import EphemeralGitHubRepo, default_repo_name
from tests.plugin.lib.http import base_url
from tests.plugin.lib.weblate_api import WeblateAPI

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
TEST_LANG_CODE = "zh_Hans"
TEST_BRANCH = f"local-{TEST_LANG_CODE}"
TEST_VERSION = "test-1.0.0"

# E2E class must run before add-or-update Celery flow in test_functional.py.
_FUNCTIONAL_CLASS_ORDER = (
    "TestQuickBookRoundTrip",
    "TestBoostComponentServiceE2E",
    "TestAddOrUpdateCeleryFlow",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Enforce functional test class order (pytest default order is not guaranteed)."""
    order_index = {name: i for i, name in enumerate(_FUNCTIONAL_CLASS_ORDER)}

    def sort_key(item: pytest.Item) -> tuple[int, int, str]:
        cls = getattr(item, "cls", None)
        if cls is None:
            return (len(_FUNCTIONAL_CLASS_ORDER), 0, item.nodeid)
        line = item.location[1] if item.location else 0
        return (
            order_index.get(cls.__name__, len(_FUNCTIONAL_CLASS_ORDER)),
            line,
            item.nodeid,
        )

    functional = [
        item
        for item in items
        if item.nodeid.startswith("tests/plugin/test_functional.py")
    ]
    if not functional:
        return
    functional.sort(key=sort_key)
    others = [item for item in items if item not in functional]
    items[:] = others + functional


@pytest.fixture(scope="session")
def live_base_url() -> str:
    return base_url()


@pytest.fixture(scope="session")
def api_token() -> str:
    token = os.environ.get("WEBLATE_API_TOKEN", "").strip()
    if not token:
        pytest.skip("WEBLATE_API_TOKEN is not set")
    return token


@pytest.fixture(scope="session")
def exec_python() -> Callable[[str], str]:
    return docker_exec_python


@pytest.fixture(scope="session")
def weblate_api(api_token: str, live_base_url: str) -> WeblateAPI:
    return WeblateAPI(api_token, live_base_url=live_base_url)


@pytest.fixture(scope="session")
def weblate_ssh_pubkey() -> str:
    pubkey = os.environ.get("WEBLATE_SSH_PUBKEY", "").strip()
    if pubkey:
        return pubkey
    return docker_exec_read_file("/app/data/ssh/id_rsa.pub")


@pytest.fixture(scope="session")
def test_repo(weblate_ssh_pubkey: str) -> EphemeralGitHubRepo:
    """Ephemeral GitHub repo with fixture docs and Weblate deploy key."""
    token = os.environ.get("GH_TEST_REPO_TOKEN", "").strip()
    if not token:
        pytest.skip(
            "GH_TEST_REPO_TOKEN is not set in the job environment "
            "(repository Actions secret with classic PAT 'repo' scope; "
            "not available on pull_request workflows from forks)"
        )

    repo_name = default_repo_name()
    manager = EphemeralGitHubRepo(token, repo_name)
    try:
        manager.create_repo()
        manager.push_fixtures(FIXTURES_DIR, branch=TEST_BRANCH)
        manager.add_deploy_key(weblate_ssh_pubkey)
        yield manager
    finally:
        try:
            manager.delete_repo()
        except Exception as exc:
            print(
                f"WARNING: failed to delete ephemeral repo {repo_name}: {exc}",
                flush=True,
            )
            raise
