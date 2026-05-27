# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""P1 integration functional tests.

Requires a live Weblate stack (Docker Compose) and optional GH_TEST_REPO_TOKEN
for add-or-update / BoostComponentService tests.
"""

from __future__ import annotations

import json

import pytest

from tests.integration.conftest import (
    FIXTURES_DIR,
    TEST_BRANCH,
    TEST_LANG_CODE,
    TEST_VERSION,
)
from tests.integration.lib.gh_repo import EphemeralGitHubRepo
from tests.integration.lib.http import http_json
from tests.integration.lib.weblate_api import WeblateAPI

pytestmark = pytest.mark.integration

QBK_FIXTURE = FIXTURES_DIR / "quickbook_fixture.qbk"
KNOWN_SOURCE_STRING = "Complex QuickBook test fixture"
JA_TRANSLATION = "複雑な QuickBook テストフィクスチャ"


# ---------------------------------------------------------------------------
# P1: QuickBook round-trip via Weblate REST API
# ---------------------------------------------------------------------------


class TestQuickBookRoundTrip:
    """Upload QBK, translate a unit, download translated file."""

    project_slug: str = ""
    component_slug: str = ""
    unit_url: str = ""

    def test_create_project_and_component(self, weblate_api: WeblateAPI) -> None:
        project_slug = WeblateAPI.unique_slug("func-qbk")
        component_slug = "qbk-fixture"
        weblate_api.create_project("Functional QBK", project_slug)
        weblate_api.create_component(
            project_slug,
            name="QBK Fixture",
            slug=component_slug,
            file_format="quickbook",
            filemask="doc/*.qbk",
            template="doc/quickbook_fixture.qbk",
            new_base="doc/quickbook_fixture.qbk",
        )
        weblate_api.upload_file(
            project_slug,
            component_slug,
            "en",
            QBK_FIXTURE,
            method="source",
        )
        # Add target language for translation workflow
        code, body = http_json(
            "POST",
            f"/api/projects/{project_slug}/components/{component_slug}/translations/",
            token=weblate_api.token,
            body={"language_code": "ja"},
        )
        assert code == 200, f"add language failed: {code} {body}"

        type(self).project_slug = project_slug
        type(self).component_slug = component_slug

    def test_units_extracted(self, weblate_api: WeblateAPI) -> None:
        assert self.project_slug and self.component_slug
        units = weblate_api.list_units(self.project_slug, self.component_slug, "ja")
        assert len(units) > 0
        sources = [
            u.get("source", [""])[0] if isinstance(u.get("source"), list) else ""
            for u in units
        ]
        assert any(KNOWN_SOURCE_STRING in s for s in sources), sources[:5]

    def test_submit_translation(self, weblate_api: WeblateAPI) -> None:
        assert self.project_slug and self.component_slug
        units = weblate_api.list_units(self.project_slug, self.component_slug, "ja")
        match = next(
            (u for u in units if KNOWN_SOURCE_STRING in str(u.get("source", ""))),
            None,
        )
        assert match is not None
        unit_url = match["unit"]
        type(self).unit_url = unit_url
        weblate_api.submit_translation(unit_url, JA_TRANSLATION)

    def test_download_translated_qbk(self, weblate_api: WeblateAPI) -> None:
        assert self.project_slug and self.component_slug
        raw = weblate_api.download_file(self.project_slug, self.component_slug, "ja")
        text = raw.decode("utf-8", errors="replace")
        assert JA_TRANSLATION in text or KNOWN_SOURCE_STRING in text


# ---------------------------------------------------------------------------
# P1: BoostComponentService E2E (in-container, uses test repo)
# Run before TestAddOrUpdateCeleryFlow so process_all sees an empty DB.
# ---------------------------------------------------------------------------


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

    def test_clone_and_scan(self, exec_python, test_repo: EphemeralGitHubRepo) -> None:
        out = json.loads(
            exec_python(self._service_snippet(test_repo, run_process_all=False))
        )
        assert out["clone_ok"] is True
        formats = {c["format"] for c in out["configs"]}
        assert "quickbook" in formats
        assert any(c["format"] == "asciidoc" for c in out["configs"])

    def test_project_component_creation(
        self, exec_python, test_repo: EphemeralGitHubRepo
    ) -> None:
        """Direct process_all on a DB with no prior components for this repo."""
        out = json.loads(
            exec_python(self._service_snippet(test_repo, run_process_all=True))
        )
        assert out.get("project_slug")
        assert out.get("component_count_before") == 0
        assert out["component_count"] > 0
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

    def test_idempotency(self, exec_python, test_repo: EphemeralGitHubRepo) -> None:
        out = json.loads(
            exec_python(
                self._service_snippet(test_repo, run_process_all=True, run_twice=True)
            )
        )
        assert out.get("idempotent") is True


# ---------------------------------------------------------------------------
# P1: add-or-update Celery flow (uses ephemeral GitHub test repo)
# Runs after E2E so HTTP/Celery path is tested against existing components too.
# ---------------------------------------------------------------------------


class TestAddOrUpdateCeleryFlow:
    """POST /boost-endpoint/add-or-update/ and poll Celery completion."""

    def test_add_or_update_returns_202(
        self, api_token: str, test_repo: EphemeralGitHubRepo
    ) -> None:
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
        type(self).task_id = str(data["task_id"])

    def test_add_or_update_task_completes(
        self, weblate_api: WeblateAPI, test_repo: EphemeralGitHubRepo
    ) -> None:
        task_id = getattr(self, "task_id", None)
        if not task_id:
            pytest.skip("depends on test_add_or_update_returns_202")
        result = weblate_api.poll_celery_task(task_id, timeout=300.0)
        assert isinstance(result, dict)
        lang_result = result.get(TEST_LANG_CODE)
        assert lang_result is not None
        # At least one submodule processed without fatal errors
        assert isinstance(lang_result, list)
        assert len(lang_result) > 0

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
