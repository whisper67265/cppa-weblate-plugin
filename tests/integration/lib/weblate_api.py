# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Weblate REST API client for integration tests (stdlib only)."""

from __future__ import annotations

import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from tests.integration.lib.http import auth_header, base_url, http_json

# Weblate blocks localhost/loopback in project.web (SSRF protection).
_DEFAULT_PROJECT_WEB = "https://example.com/"


def project_web_url(live_base_url: str | None = None) -> str:
    """Return a project ``web`` URL accepted by Weblate in CI/local stacks."""
    override = os.environ.get("WEBLATE_PROJECT_WEB", "").strip()
    if override:
        return override if override.endswith("/") else f"{override}/"

    base = (live_base_url or base_url()).rstrip("/")
    host = (urlparse(base).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return _DEFAULT_PROJECT_WEB
    return f"{base}/"


def _expect_status(
    code: int, allowed: tuple[int, ...], label: str, detail: Any
) -> None:
    if code not in allowed:
        raise AssertionError(f"{label} failed: {code} {detail}")


def _unwrap_api_result(body: dict[str, Any]) -> dict[str, Any]:
    """Unwrap ``{"result": ...}`` envelopes from Weblate write endpoints."""
    result = body.get("result")
    if isinstance(result, dict):
        return result
    return body


def component_defaults_payload(
    *,
    name: str,
    slug: str,
    file_format: str,
    filemask: str,
    template: str = "",
    new_base: str | None = None,
    repo: str = "local:",
    vcs: str = "local",
    source_language_code: str = "en",
    language_regex: str = "",
) -> dict[str, Any]:
    """Component fields aligned with ``BoostComponentService`` (services.py)."""
    return {
        "name": name,
        "slug": slug,
        "repo": repo,
        "vcs": vcs,
        "file_format": file_format,
        "filemask": filemask,
        "template": template,
        "new_base": new_base or template,
        "source_language": {"code": source_language_code},
        "edit_template": False,
        "manage_units": False,
        "license": "",
        "allow_translation_propagation": False,
        "enable_suggestions": True,
        "suggestion_voting": False,
        "suggestion_autoaccept": 0,
        "check_flags": "",
        "language_regex": language_regex,
    }


def _payload_to_multipart_fields(payload: dict[str, Any]) -> dict[str, str]:
    """Convert JSON API payload values to multipart form strings."""
    fields: dict[str, str] = {}
    for key, value in payload.items():
        if key == "source_language" and isinstance(value, dict):
            fields["source_language"] = str(value.get("code", "en"))
        elif isinstance(value, bool):
            fields[key] = "true" if value else "false"
        else:
            fields[key] = str(value)
    return fields


def _multipart_encode(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    """Build multipart/form-data body for file upload."""
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        lines.append(value.encode())
        lines.append(b"\r\n")

    for name, (filename, content, content_type) in files.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        lines.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        lines.append(content)
        lines.append(b"\r\n")

    lines.append(f"--{boundary}--\r\n".encode())
    body = b"".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


class WeblateAPI:
    """Thin wrapper around Weblate's REST API for functional tests."""

    def __init__(self, token: str, *, live_base_url: str | None = None) -> None:
        self.token = token
        self._base = (live_base_url or base_url()).rstrip("/")

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self._base}{path}"

    def _api_path(self, url_or_path: str) -> str:
        if url_or_path.startswith("http"):
            return url_or_path.replace(self._base, "", 1)
        if not url_or_path.startswith("/"):
            return f"/{url_or_path}"
        return url_or_path

    def create_project(self, name: str, slug: str | None = None) -> dict[str, Any]:
        slug = slug or name.lower().replace(" ", "-")
        code, body = http_json(
            "POST",
            "/api/projects/",
            token=self.token,
            body={
                "name": name,
                "slug": slug,
                "web": project_web_url(self._base),
            },
        )
        _expect_status(code, (200, 201), "create_project", body)
        assert isinstance(body, dict)
        return body

    def create_component(
        self,
        project_slug: str,
        *,
        name: str,
        slug: str,
        file_format: str,
        filemask: str,
        template: str,
        new_base: str | None = None,
        repo: str = "local:",
        vcs: str = "local",
        language_regex: str = "",
    ) -> dict[str, Any]:
        payload = component_defaults_payload(
            name=name,
            slug=slug,
            file_format=file_format,
            filemask=filemask,
            template=template,
            new_base=new_base,
            repo=repo,
            vcs=vcs,
            language_regex=language_regex,
        )
        code, body = http_json(
            "POST",
            f"/api/projects/{project_slug}/components/",
            token=self.token,
            body=payload,
        )
        _expect_status(code, (200, 201), "create_component", body)
        assert isinstance(body, dict)
        component = _unwrap_api_result(body)
        task_url = component.get("task_url")
        if isinstance(task_url, str) and task_url:
            self.wait_for_background_task(task_url)
        return component

    def _post_multipart(
        self,
        path: str,
        fields: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        *,
        label: str,
        timeout: float = 120.0,
    ) -> tuple[int, Any]:
        body_bytes, content_type = _multipart_encode(fields, files)
        req = Request(
            self._url(path),
            data=body_bytes,
            headers={
                "Authorization": auth_header(self.token),
                "Content-Type": content_type,
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                code = resp.getcode()
        except HTTPError as e:
            raw = e.read()
            code = e.code

        if not raw:
            return code, {"status_code": code}
        try:
            parsed: Any = json.loads(raw.decode())
        except json.JSONDecodeError:
            parsed = raw.decode(errors="replace")
        _expect_status(code, (200, 201), label, parsed)
        return code, parsed

    def create_component_from_docfile(
        self,
        project_slug: str,
        *,
        name: str,
        slug: str,
        file_format: str,
        docfile_path: Path,
        filemask: str = "*.qbk",
        language_regex: str = "",
    ) -> dict[str, Any]:
        """Create a component by uploading a document (Weblate multipart API)."""
        content = docfile_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(docfile_path))
        mime = mime or "application/octet-stream"
        payload = component_defaults_payload(
            name=name,
            slug=slug,
            file_format=file_format,
            filemask=filemask,
            template="",
            new_base="",
            language_regex=language_regex,
        )
        fields = _payload_to_multipart_fields(payload)
        fields["new_lang"] = "add"
        _code, body = self._post_multipart(
            f"/api/projects/{project_slug}/components/",
            fields,
            {"docfile": (docfile_path.name, content, mime)},
            label="create_component_from_docfile",
        )
        assert isinstance(body, dict)
        component = _unwrap_api_result(body)
        resolved_slug = str(component.get("slug", slug))
        task_url = component.get("task_url")
        if isinstance(task_url, str) and task_url:
            self.wait_for_background_task(task_url)
        self.wait_for_component(project_slug, resolved_slug)
        return component

    def wait_for_background_task(
        self,
        task_url: str,
        *,
        timeout: float = 120.0,
        interval: float = 2.0,
    ) -> dict[str, Any]:
        """Poll ``GET /api/tasks/(uuid)/`` until component creation finishes."""
        path = self._api_path(task_url)
        deadline = time.monotonic() + timeout
        last: tuple[int, Any] = (0, None)
        while time.monotonic() < deadline:
            code, body = http_json("GET", path, token=self.token)
            last = (code, body)
            if code == 200 and isinstance(body, dict) and body.get("completed"):
                return body
            time.sleep(interval)
        raise TimeoutError(
            f"Background task {task_url} not completed after {timeout}s: "
            f"{last[0]} {last[1]}"
        )

    def wait_for_component(
        self,
        project_slug: str,
        component_slug: str,
        *,
        timeout: float = 120.0,
        interval: float = 2.0,
    ) -> dict[str, Any]:
        """Poll until a component is visible (docfile create can be asynchronous)."""
        deadline = time.monotonic() + timeout
        last: tuple[int, Any] = (0, None)
        while time.monotonic() < deadline:
            code, body = http_json(
                "GET",
                f"/api/components/{project_slug}/{component_slug}/",
                token=self.token,
            )
            last = (code, body)
            if code == 200 and isinstance(body, dict):
                return body
            time.sleep(interval)
        raise TimeoutError(
            f"Component {project_slug}/{component_slug} not ready after {timeout}s: "
            f"{last[0]} {last[1]}"
        )

    def ensure_translation(
        self,
        project_slug: str,
        component_slug: str,
        language_code: str,
    ) -> dict[str, Any]:
        """Ensure a translation exists (idempotent; uses component-scoped API paths)."""
        self.wait_for_component(project_slug, component_slug)
        code, body = http_json(
            "GET",
            f"/api/components/{project_slug}/{component_slug}/translations/",
            token=self.token,
        )
        assert code == 200, f"list translations failed: {code} {body}"
        assert isinstance(body, dict)
        for item in body.get("results", []):
            if not isinstance(item, dict):
                continue
            lang = item.get("language_code")
            if lang is None:
                lang_obj = item.get("language")
                if isinstance(lang_obj, dict):
                    lang = lang_obj.get("code")
            if lang == language_code:
                return item

        code, body = http_json(
            "POST",
            f"/api/components/{project_slug}/{component_slug}/translations/",
            token=self.token,
            body={"language_code": language_code},
        )
        if code in (200, 201) and isinstance(body, dict):
            if body.get("language_code"):
                return body
            result = body.get("result")
            if isinstance(result, dict):
                return result
            return body
        if code == 400 and isinstance(body, (dict, list)):
            detail = json.dumps(body).lower()
            if "already exists" in detail:
                return {"language_code": language_code}
        raise AssertionError(f"add translation failed: {code} {body}")

    def upload_file(
        self,
        project_slug: str,
        component_slug: str,
        language_code: str,
        file_path: Path,
        *,
        method: str = "translate",
    ) -> dict[str, Any]:
        """Upload a translation file (multipart POST)."""
        content = file_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        body_bytes, content_type = _multipart_encode(
            {"method": method},
            {"file": (file_path.name, content, mime)},
        )
        url = self._url(
            f"/api/translations/{project_slug}/{component_slug}/{language_code}/file/"
        )
        req = Request(
            url,
            data=body_bytes,
            headers={
                "Authorization": auth_header(self.token),
                "Content-Type": content_type,
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=120.0) as resp:
                raw = resp.read()
                code = resp.getcode()
        except HTTPError as e:
            raw = e.read()
            code = e.code

        if not raw:
            return {"status_code": code}
        try:
            parsed: Any = json.loads(raw.decode())
        except json.JSONDecodeError:
            parsed = raw.decode(errors="replace")
        _expect_status(code, (200, 201), "upload_file", parsed)
        if isinstance(parsed, dict):
            return parsed
        return {"status_code": code, "body": parsed}

    def list_units(
        self,
        project_slug: str,
        component_slug: str,
        language_code: str,
        *,
        min_count: int = 1,
        timeout: float = 120.0,
        interval: float = 2.0,
    ) -> list[dict[str, Any]]:
        """List translation units, polling until strings are extracted."""
        path = (
            f"/api/translations/{project_slug}/{component_slug}/"
            f"{language_code}/units/?page_size=100"
        )
        deadline = time.monotonic() + timeout
        last: tuple[int, Any] = (0, None)
        while time.monotonic() < deadline:
            code, body = http_json("GET", path, token=self.token)
            last = (code, body)
            if code != 200:
                break
            assert isinstance(body, dict)
            results = body.get("results")
            if isinstance(results, list) and len(results) >= min_count:
                return results
            time.sleep(interval)
        raise AssertionError(f"list_units failed: {last[0]} {last[1]}")

    @staticmethod
    def unit_api_url(unit: dict[str, Any]) -> str:
        """Return the REST path for PATCHing a unit from a list-units result item."""
        url = unit.get("url")
        if isinstance(url, str) and url:
            return url
        nested = unit.get("unit")
        if isinstance(nested, str) and nested:
            return nested
        if isinstance(nested, dict):
            nested_url = nested.get("url")
            if isinstance(nested_url, str) and nested_url:
                return nested_url
        unit_id = unit.get("id")
        if unit_id is not None:
            return f"/api/units/{unit_id}/"
        raise KeyError(f"unit has no API URL: {unit!r}")

    def submit_translation(self, unit_url: str, target: str) -> dict[str, Any]:
        """PATCH a unit with translated target text (state 20 = translated)."""
        path = self._api_path(unit_url)
        code, body = http_json(
            "PATCH",
            path,
            token=self.token,
            body={"target": [target], "state": 20},
        )
        assert code == 200, f"submit_translation failed: {code} {body}"
        assert isinstance(body, dict)
        return body

    def download_file(
        self,
        project_slug: str,
        component_slug: str,
        language_code: str,
    ) -> bytes:
        url = self._url(
            f"/api/translations/{project_slug}/{component_slug}/{language_code}/file/"
        )
        req = Request(
            url,
            headers={"Authorization": auth_header(self.token)},
            method="GET",
        )
        try:
            with urlopen(req, timeout=120.0) as resp:
                return resp.read()
        except HTTPError as e:
            raise AssertionError(
                f"download_file failed: {e.code} {e.read().decode(errors='replace')}"
            ) from e

    def poll_celery_task(
        self,
        task_id: str,
        *,
        timeout: float = 240.0,
        interval: float = 3.0,
    ) -> Any:
        """Poll Celery task result inside the Weblate container."""
        from tests.integration.lib.docker_exec import docker_exec_python

        deadline = time.monotonic() + timeout
        snippet_template = """
import json
import time

from celery.result import AsyncResult
from weblate.utils.celery import app

task_id = {task_id!r}
deadline = time.monotonic() + {remaining:.1f}
result = None
while time.monotonic() < deadline:
    ar = AsyncResult(task_id, app=app)
    if ar.ready():
        if ar.failed():
            raise RuntimeError(str(ar.result))
        result = ar.result
        break
    time.sleep({interval})
else:
    raise TimeoutError(f"Task {{task_id}} not ready")

print(json.dumps({{"ok": True, "result": result}}))
"""
        last_exc: BaseException | None = None
        while time.monotonic() < deadline:
            remaining = max(deadline - time.monotonic(), interval)
            snippet = snippet_template.format(
                task_id=task_id,
                remaining=remaining,
                interval=interval,
            )
            try:
                out = docker_exec_python(snippet, timeout=timeout)
                data = json.loads(out)
                return data.get("result")
            except (RuntimeError, json.JSONDecodeError, TimeoutError) as exc:
                last_exc = exc
            time.sleep(interval)
        raise TimeoutError(
            f"Celery task {task_id} did not complete within {timeout}s: {last_exc}"
        )

    @staticmethod
    def unique_slug(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:8]}"
