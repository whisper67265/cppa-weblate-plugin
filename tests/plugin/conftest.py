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
        manager.delete_repo()
