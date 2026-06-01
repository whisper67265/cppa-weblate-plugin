# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Ephemeral GitHub repository lifecycle for plugin tests (stdlib only)."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_GITHUB_API = "https://api.github.com"


def _api_error_message(method: str, path: str, code: int, raw: bytes) -> str:
    body = raw.decode(errors="replace")
    return f"GitHub API {method} {path} failed: {code} {body}"


class EphemeralGitHubRepo:
    """Create, populate, and destroy a temporary GitHub repo for plugin tests."""

    __test__ = False  # not a pytest test class

    def __init__(self, token: str, repo_name: str) -> None:
        self.token = token
        self.repo_name = repo_name
        self.owner: str | None = None
        self.repo_full_name: str | None = None
        self._created = False

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        url = f"{_GITHUB_API}{path}"
        data: bytes | None = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                raw = resp.read()
                code = resp.getcode()
        except urllib.error.HTTPError as e:
            raw = e.read()
            code = e.code
            if code not in expected:
                raise RuntimeError(_api_error_message(method, path, code, raw)) from e
            if not raw:
                return None
            return json.loads(raw.decode())

        if code not in expected:
            raise RuntimeError(_api_error_message(method, path, code, raw))
        if not raw:
            return None
        return json.loads(raw.decode())

    def resolve_owner(self) -> str:
        if self.owner:
            return self.owner
        user = self._request("GET", "/user")
        assert isinstance(user, dict)
        login = user.get("login")
        if not login:
            raise RuntimeError("GitHub /user did not return login")
        self.owner = str(login)
        return self.owner

    def create_repo(self) -> str:
        """Create a repo; return SSH clone URL."""
        owner = self.resolve_owner()
        self._request(
            "POST",
            "/user/repos",
            body={
                "name": self.repo_name,
                "private": False,
                "auto_init": True,
            },
            expected=(201,),
        )
        self._created = True
        self.repo_full_name = f"{owner}/{self.repo_name}"
        return f"git@github.com:{self.repo_full_name}.git"

    def _put_file(
        self,
        path: str,
        content: bytes,
        branch: str,
        *,
        message: str,
    ) -> None:
        owner = self.resolve_owner()
        encoded = base64.b64encode(content).decode("ascii")
        api_path = f"/repos/{owner}/{self.repo_name}/contents/{path}"
        self._request(
            "PUT",
            api_path,
            body={
                "message": message,
                "content": encoded,
                "branch": branch,
            },
            expected=(201,),
        )

    def ensure_branch(self, branch: str) -> None:
        """Create branch from the repo default if it does not exist yet."""
        owner = self.resolve_owner()
        repo = self._request("GET", f"/repos/{owner}/{self.repo_name}")
        assert isinstance(repo, dict)
        default_branch = str(repo.get("default_branch") or "main")
        ref_path = f"/repos/{owner}/{self.repo_name}/git/ref/heads/{branch}"
        existing = self._request("GET", ref_path, expected=(200, 404))
        if isinstance(existing, dict) and existing.get("object"):
            return
        default_ref = self._request(
            "GET",
            f"/repos/{owner}/{self.repo_name}/git/ref/heads/{default_branch}",
        )
        assert isinstance(default_ref, dict)
        sha = default_ref["object"]["sha"]
        self._request(
            "POST",
            f"/repos/{owner}/{self.repo_name}/git/refs",
            body={"ref": f"refs/heads/{branch}", "sha": sha},
            expected=(201,),
        )

    def push_fixtures(self, fixture_dir: Path, branch: str) -> None:
        """Upload fixture files under doc/ on the given branch."""
        self.ensure_branch(branch)
        files = [
            ("doc/quickbook_fixture.qbk", "quickbook_fixture.qbk"),
            ("doc/asciidoc_fixture.adoc", "asciidoc_fixture.adoc"),
        ]
        for dest, src_name in files:
            src = fixture_dir / src_name
            if not src.is_file():
                raise FileNotFoundError(src)
            self._put_file(
                dest,
                src.read_bytes(),
                branch,
                message=f"Add {dest} for plugin tests",
            )

    def add_deploy_key(self, public_key: str, title: str = "weblate-ci") -> None:
        """Register read-only deploy key on the repo."""
        owner = self.resolve_owner()
        self._request(
            "POST",
            f"/repos/{owner}/{self.repo_name}/keys",
            body={
                "title": title,
                "key": public_key.strip(),
                "read_only": True,
            },
            expected=(201,),
        )

    def delete_repo(self) -> None:
        """Delete the repository (no-op if never created)."""
        if not self._created:
            return
        owner = self.resolve_owner()
        try:
            self._request(
                "DELETE",
                f"/repos/{owner}/{self.repo_name}",
                expected=(204,),
            )
        except RuntimeError:
            pass
        finally:
            self._created = False


def default_repo_name() -> str:
    """Unique repo name for this CI run.

    Keep short: Weblate project slug is
    ``boost-{repo}-documentation-{lang}`` (max ~60 chars).
    """
    run_id = os.environ.get("GITHUB_RUN_ID", os.environ.get("PYTEST_XDIST_WORKER", ""))
    suffix = str(run_id or os.getpid())
    # Use tail of run id so long GITHUB_RUN_ID values stay within slug limits.
    if len(suffix) > 10:
        suffix = suffix[-10:]
    return f"cppa-wl-ft-{suffix}"
