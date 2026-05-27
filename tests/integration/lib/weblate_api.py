# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Weblate REST API client for integration tests (stdlib only)."""

from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests.integration.lib.http import base_url, http_json


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

    def create_project(self, name: str, slug: str | None = None) -> dict[str, Any]:
        slug = slug or name.lower().replace(" ", "-")
        code, body = http_json(
            "POST",
            "/api/projects/",
            token=self.token,
            body={
                "name": name,
                "slug": slug,
                "web": f"{self._base}/",
            },
        )
        assert code == 200, f"create_project failed: {code} {body}"
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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "slug": slug,
            "repo": repo,
            "vcs": vcs,
            "file_format": file_format,
            "filemask": filemask,
            "template": template,
            "new_base": new_base or template,
            "source_language": {"code": "en"},
        }
        code, body = http_json(
            "POST",
            f"/api/projects/{project_slug}/components/",
            token=self.token,
            body=payload,
        )
        assert code == 200, f"create_component failed: {code} {body}"
        assert isinstance(body, dict)
        return body

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
                "Authorization": f"Bearer {self.token}",
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
        assert code == 200, f"upload_file failed: {code} {parsed}"
        assert isinstance(parsed, dict)
        return parsed

    def list_units(
        self,
        project_slug: str,
        component_slug: str,
        language_code: str,
    ) -> list[dict[str, Any]]:
        code, body = http_json(
            "GET",
            (
                f"/api/translations/{project_slug}/{component_slug}/"
                f"{language_code}/units/?q=state:>=empty"
            ),
            token=self.token,
        )
        assert code == 200, f"list_units failed: {code} {body}"
        assert isinstance(body, dict)
        results = body.get("results", body)
        assert isinstance(results, list)
        return results

    def submit_translation(self, unit_url: str, target: str) -> dict[str, Any]:
        """PATCH a unit with translated target text."""
        if unit_url.startswith("http"):
            path = unit_url.replace(self._base, "", 1)
        else:
            path = unit_url
        code, body = http_json(
            "PATCH",
            path,
            token=self.token,
            body={"target": [target]},
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
            headers={"Authorization": f"Bearer {self.token}"},
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
