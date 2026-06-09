# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""P1 plugin functional tests.

Requires a live Weblate stack (Docker Compose) and optional GH_TEST_REPO_TOKEN
for add-or-update / BoostComponentService tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from tests.plugin.conftest import (
    FIXTURES_DIR,
    TEST_BRANCH,
    TEST_LANG_CODE,
    TEST_VERSION,
)
from tests.plugin.lib.gh_repo import EphemeralGitHubRepo
from tests.plugin.lib.http import http_json
from tests.plugin.lib.weblate_api import WeblateAPI

pytestmark = pytest.mark.plugin

QBK_FIXTURE = FIXTURES_DIR / "quickbook_fixture.qbk"
KNOWN_SOURCE_STRING = "Complex QuickBook test fixture"
ZH_HANS_TRANSLATION = "复杂 QuickBook 测试夹具"


def _assert_process_all_ok(
    process_all: dict, *, require_component_changes: bool = False
) -> None:
    """Assert BoostComponentService.process_all() succeeded for every submodule."""
    assert process_all.get("failed", 0) == 0, process_all
    results = process_all.get("submodule_results", [])
    assert results, process_all
    for entry in results:
        assert entry.get("success") is True, entry
        if require_component_changes:
            created = entry.get("components_created", 0)
            updated = entry.get("components_updated", 0)
            assert created + updated > 0, entry


@dataclass(frozen=True)
class CreatedProjectComponent:
    project_slug: str
    component_slug: str


@pytest.fixture(scope="class")
def created_project_component(weblate_api: WeblateAPI) -> CreatedProjectComponent:
    """Project + QuickBook component for round-trip tests."""
    project_slug = WeblateAPI.unique_slug("func-qbk")
    component_slug = "qbk-fixture"
    weblate_api.create_project(f"Functional QBK {project_slug}", project_slug)
    # Docfile multipart upload (no empty local VCS template paths).
    created = weblate_api.create_component_from_docfile(
        project_slug,
        name="QBK Fixture",
        slug=component_slug,
        file_format="quickbook",
        docfile_path=QBK_FIXTURE,
        filemask="doc/*.qbk",
        language_regex=f"^{TEST_LANG_CODE}$",
    )
    component_slug = str(created.get("slug", component_slug))
    weblate_api.ensure_translation(project_slug, component_slug, TEST_LANG_CODE)
    return CreatedProjectComponent(
        project_slug=project_slug,
        component_slug=component_slug,
    )


# ---------------------------------------------------------------------------
# P1: QuickBook round-trip via Weblate REST API
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestQuickBookRoundTrip:
    """Upload QBK, translate a unit, download translated file."""

    @pytest.mark.timeout(120)
    def test_units_extracted(
        self,
        weblate_api: WeblateAPI,
        created_project_component: CreatedProjectComponent,
    ) -> None:
        units = weblate_api.list_units(
            created_project_component.project_slug,
            created_project_component.component_slug,
            TEST_LANG_CODE,
        )
        assert len(units) > 0
        sources = [
            u.get("source", [""])[0] if isinstance(u.get("source"), list) else ""
            for u in units
        ]
        assert any(KNOWN_SOURCE_STRING in s for s in sources), sources[:5]

    @pytest.mark.timeout(120)
    def test_submit_translation(
        self,
        weblate_api: WeblateAPI,
        created_project_component: CreatedProjectComponent,
    ) -> None:
        units = weblate_api.list_units(
            created_project_component.project_slug,
            created_project_component.component_slug,
            TEST_LANG_CODE,
        )
        match = next(
            (u for u in units if KNOWN_SOURCE_STRING in str(u.get("source", ""))),
            None,
        )
        assert match is not None
        unit_url = WeblateAPI.unit_api_url(match)
        weblate_api.submit_translation(unit_url, ZH_HANS_TRANSLATION)

    @pytest.mark.timeout(120)
    def test_download_translated_qbk(
        self,
        weblate_api: WeblateAPI,
        created_project_component: CreatedProjectComponent,
    ) -> None:
        raw = weblate_api.download_file(
            created_project_component.project_slug,
            created_project_component.component_slug,
            TEST_LANG_CODE,
        )
        text = raw.decode("utf-8", errors="replace")
        assert ZH_HANS_TRANSLATION in text, "translated QBK content was not found"


# ---------------------------------------------------------------------------
# P1: BoostComponentService E2E (in-container, uses test repo)
# Run before TestAddOrUpdateCeleryFlow so process_all sees an empty DB.
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestBoostComponentServiceE2E:
    """Exercise BoostComponentService inside the Weblate container."""

    @staticmethod
    def _service_snippet(
        test_repo: EphemeralGitHubRepo,
        *,
        run_process_all: bool = False,
        run_twice: bool = False,
    ) -> str:
        owner = test_repo.resolve_owner()
        repo_name = test_repo.repo_name
        return f"""
import json
import os
import tempfile

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "weblate.settings_docker")
import django
django.setup()

from weblate.auth.models import User
from weblate.trans.models import Component, Project
from boost_weblate.endpoint.services import BoostComponentService

organization = {owner!r}
submodule = {repo_name!r}
lang_code = {TEST_LANG_CODE!r}
version = {TEST_VERSION!r}
branch = {TEST_BRANCH!r}

user = User.objects.get(username="admin")
service = BoostComponentService(
    organization=organization,
    lang_code=lang_code,
    version=version,
    extensions=None,
)

out = {{"clone_ok": False, "configs": [], "project_slug": None, "component_count": 0}}

tmpdir = tempfile.mkdtemp()
try:
    ok = service.clone_repository(submodule, tmpdir, branch)
    out["clone_ok"] = bool(ok)
    if ok:
        configs = service.scan_documentation_files(tmpdir)
        out["configs"] = [
            {{"name": c.get("component_name"), "format": c.get("file_format")}}
            for c in configs
        ]
finally:
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

if {run_process_all!r}:
    from boost_weblate.endpoint.services import _submodule_slug
    slug = f"boost-{{_submodule_slug(submodule)}}-documentation-{{lang_code}}"
    out["project_slug"] = slug
    out["component_count_before"] = Component.objects.filter(project__slug=slug).count()
    request = type("R", (), {{"user": user}})()
    results = service.process_all([submodule], user=user, request=request)
    out["process_all"] = results
    out["component_count"] = Component.objects.filter(project__slug=slug).count()

    if {run_twice!r}:
        count1 = out["component_count"]
        service.process_all([submodule], user=user, request=request)
        count2 = Component.objects.filter(project__slug=slug).count()
        out["component_count_after_second"] = count2
        out["idempotent"] = count1 == count2

print(json.dumps(out))
"""

    @pytest.mark.timeout(180)
    def test_clone_and_scan(self, exec_python, test_repo: EphemeralGitHubRepo) -> None:
        out = json.loads(
            exec_python(self._service_snippet(test_repo, run_process_all=False))
        )
        assert out["clone_ok"] is True
        formats = {c["format"] for c in out["configs"]}
        assert "quickbook" in formats
        assert any(c["format"] == "asciidoc" for c in out["configs"])

    @pytest.mark.timeout(180)
    def test_project_component_creation(
        self, exec_python, test_repo: EphemeralGitHubRepo
    ) -> None:
        """Direct process_all on a DB with no prior components for this repo."""
        out = json.loads(
            exec_python(self._service_snippet(test_repo, run_process_all=True))
        )
        assert out.get("project_slug")
        assert out.get("component_count_before") == 0
        _assert_process_all_ok(
            out.get("process_all", {}), require_component_changes=True
        )
        assert out["component_count"] > 0, out
        slug = out["project_slug"]
        check = exec_python(
            f"""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "weblate.settings_docker")
import django
django.setup()
from weblate.trans.models import Project, Component
slug = {slug!r}
assert Project.objects.filter(slug=slug).exists()
assert Component.objects.filter(project__slug=slug).exists()
print("ok")
"""
        )
        assert check == "ok"

    @pytest.mark.timeout(180)
    def test_idempotency(self, exec_python, test_repo: EphemeralGitHubRepo) -> None:
        out = json.loads(
            exec_python(
                self._service_snippet(test_repo, run_process_all=True, run_twice=True)
            )
        )
        assert out.get("component_count", 0) > 0, out
        assert out.get("idempotent") is True


# ---------------------------------------------------------------------------
# P1: add-or-update Celery flow (uses ephemeral GitHub test repo)
# Runs after E2E so HTTP/Celery path is tested against existing components too.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def add_or_update_task(api_token: str, test_repo: EphemeralGitHubRepo) -> str:
    """Accepted add-or-update request; returns Celery task id."""
    owner = test_repo.resolve_owner()
    body = {
        "organization": owner,
        "version": TEST_VERSION,
        "add_or_update": {TEST_LANG_CODE: [test_repo.repo_name]},
    }
    code, data = http_json(
        "POST",
        "/boost-endpoint/add-or-update/",
        token=api_token,
        body=body,
    )
    assert code == 202, f"expected 202: {code} {data}"
    assert isinstance(data, dict)
    assert data.get("status") == "accepted"
    assert data.get("task_id")
    return str(data["task_id"])


@pytest.mark.slow
class TestAddOrUpdateCeleryFlow:
    """POST /boost-endpoint/add-or-update/ and poll Celery completion."""

    @pytest.mark.timeout(360)
    def test_add_or_update_task_completes(
        self, weblate_api: WeblateAPI, add_or_update_task: str
    ) -> None:
        result = weblate_api.poll_celery_task(add_or_update_task, timeout=300.0)
        assert isinstance(result, dict)
        lang_result = result.get(TEST_LANG_CODE)
        assert lang_result is not None
        assert isinstance(lang_result, dict), lang_result
        _assert_process_all_ok(lang_result)

    def test_add_or_update_invalid_returns_400(self, api_token: str) -> None:
        code, data = http_json(
            "POST",
            "/boost-endpoint/add-or-update/",
            token=api_token,
            body={"version": TEST_VERSION, "add_or_update": {TEST_LANG_CODE: ["x"]}},
        )
        assert code == 400, f"expected 400: {code} {data}"
        assert isinstance(data, dict)
        assert "errors" in data

    def test_add_or_update_unauthenticated_returns_401(self) -> None:
        code, _ = http_json(
            "POST",
            "/boost-endpoint/add-or-update/",
            body={
                "organization": "x",
                "version": TEST_VERSION,
                "add_or_update": {TEST_LANG_CODE: ["y"]},
            },
        )
        assert code in (401, 403)
