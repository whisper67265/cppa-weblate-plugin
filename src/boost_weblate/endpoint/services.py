# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""
Internal Django service for Boost documentation add-or-update.

Uses only in-memory component data: no temporary JSON files.
Builds supported formats from Weblate's FILE_FORMATS (same as
list_file_format_params).
Creates/updates Project and Component via Django ORM only (no external API).

Alignment with REST API (POST /api/projects/, POST .../components/,
POST .../translations/):
- Project: same as API (get_or_create + post_create when created).
  API does not use Celery for create.
- Component: same create + post_create; we then call
  do_update/create_translations_immediate so the component is ready before
  adding a language. The API relies on Component.save() which schedules
  component_after_save (Celery when not eager), so the API does not wait for
  repo/template in the request.
- Translation: same checks and add_new_language as API; we call
  create_translations_immediate before so template is on disk (API assumes
  component was already synced).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.db import transaction
from weblate.formats.models import FILE_FORMATS
from weblate.lang.models import Language
from weblate.logger import LOGGER
from weblate.trans.defines import COMPONENT_NAME_LENGTH
from weblate.trans.models import Component, Project
from weblate.utils.errors import report_error
from weblate.vcs.base import RepositoryError

from boost_weblate.endpoint.errors import (
    BoostEndpointErrorCode,
    append_error,
    to_error_dict,
)
from boost_weblate.endpoint.validators import (
    github_https_clone_url,
    github_ssh_repo_url,
    validate_repo_segment,
)

if TYPE_CHECKING:
    from weblate.lang.models import LanguageQuerySet

# Component.name / Component.slug max_length — from weblate.trans.defines so this
# matches the database column constraint (100 as of this writing).
MAX_COMPONENT_NAME_LENGTH = COMPONENT_NAME_LENGTH
MAX_COMPONENT_SLUG_LENGTH = COMPONENT_NAME_LENGTH
# When over limit: keep first (max_len - 10) chars and append "[<8-hex-hash>]"
# (10 chars) so the result is always <= max_len and is unique for any two names.
TRUNCATE_NAME_HASH_LEN = 8  # 1 "[" + 8 hex + 1 "]" = 10 chars suffix
# Slug truncation: keep first (max_len - 9) chars and append "-<8-hex>" (9 chars).
# Uses URL-safe hex only (no brackets); uniqueness same as name truncation.
TRUNCATE_SLUG_HASH_LEN = 8  # 1 "-" + 8 hex = 9 chars suffix


def _submodule_slug(name: str) -> str:
    """Normalize submodule name to URL-safe slug: lower case, underscores to hyphens."""
    return name.lower().replace("_", "-")


def truncate_component_name(name: str, max_len: int = MAX_COMPONENT_NAME_LENGTH) -> str:
    """
    Truncate component name to max_len.

    If over limit: keep first (max_len - 10) chars and append "[<8-hex>]"
    (10 chars) derived from the full name's SHA-256.  This guarantees
    uniqueness: two distinct full names always produce distinct truncated
    names (collision probability ≈ 1/16^8, negligible).
    """
    if len(name) <= max_len:
        return name
    hash_suffix = (
        "[" + hashlib.sha256(name.encode()).hexdigest()[:TRUNCATE_NAME_HASH_LEN] + "]"
    )
    head_len = max_len - len(hash_suffix)
    return name[:head_len] + hash_suffix


def truncate_component_slug(slug: str, max_len: int = MAX_COMPONENT_SLUG_LENGTH) -> str:
    """
    Truncate component slug to max_len.

    If over limit: keep first (max_len - 9) chars and append "-<8-hex>" derived from the
    slug's SHA-256.  Uses only URL-safe characters (lowercase hex + hyphen)
    and guarantees uniqueness for any two distinct full slugs.
    """
    if len(slug) <= max_len:
        return slug
    hash_suffix = (
        "-" + hashlib.sha256(slug.encode()).hexdigest()[:TRUNCATE_SLUG_HASH_LEN]
    )
    head_len = max_len - len(hash_suffix)
    return slug[:head_len] + hash_suffix


def _git_commit_and_push_removals(
    base_path: str,
    rel_paths: list[str],
    *,
    name: str,
    push_url: str | None,
    push_branch: str | None,
) -> tuple[bool, dict[str, Any] | None, bool]:
    """
    Stage removed files, commit, and optionally push.

    Returns (success, error_dict, committed). ``committed`` is True when a
    local commit was created (used to choose rollback strategy on push failure).
    """
    committed = False
    try:
        subprocess.run(
            ["git", "-C", base_path, "add", "--", *rel_paths],
            check=True,
            capture_output=True,
            timeout=60,
        )
        git_status = subprocess.run(
            ["git", "-C", base_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if git_status.returncode != 0:
            stderr = (git_status.stderr or "").strip()
            LOGGER.warning(
                "Git status failed for %s (exit %s): %s",
                name,
                git_status.returncode,
                stderr,
            )
            return (
                False,
                to_error_dict(
                    BoostEndpointErrorCode.GIT_PUSH_FAILED,
                    f"Git status failed (exit {git_status.returncode}): {stderr}",
                    component_name=name,
                    stderr=stderr[:500],
                    returncode=git_status.returncode,
                ),
                committed,
            )
        if git_status.stdout.strip():
            committer = getattr(settings, "DEFAULT_COMMITER_NAME", "Weblate")
            email = getattr(
                settings,
                "DEFAULT_COMMITER_EMAIL",
                "noreply@weblate.org",
            )
            author = f"{committer} <{email}>"
            subprocess.run(
                [
                    "git",
                    "-C",
                    base_path,
                    "commit",
                    "-m",
                    f"Remove translation files for deleted component: {name}",
                    "--author",
                    author,
                    "--",
                    *rel_paths,
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            committed = True
            LOGGER.info("Committed deletion of translation files for: %s", name)
            if push_url and push_branch:
                subprocess.run(
                    [
                        "git",
                        "-C",
                        base_path,
                        "push",
                        "origin",
                        f"HEAD:{push_branch}",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
                LOGGER.info("Pushed to origin %s", push_branch)
        return True, None, committed
    except subprocess.CalledProcessError as e:
        err = e.stderr or e
        LOGGER.warning("Git commit/push failed for %s: %s", name, err)
        stderr = err.decode(errors="replace") if isinstance(err, bytes) else str(err)
        return (
            False,
            to_error_dict(
                BoostEndpointErrorCode.GIT_PUSH_FAILED,
                f"Git commit/push failed: {stderr}",
                component_name=name,
                stderr=stderr[:500],
            ),
            committed,
        )
    except subprocess.TimeoutExpired as e:
        LOGGER.warning("Git commit/push timeout for %s", name)
        timeout = e.timeout if e.timeout is not None else 0
        return (
            False,
            to_error_dict(
                BoostEndpointErrorCode.GIT_PUSH_TIMEOUT,
                "Git commit/push timeout",
                component_name=name,
                timeout_seconds=timeout,
            ),
            committed,
        )


def _git_restore_removed_files(
    base_path: str,
    rel_paths: list[str],
    *,
    committed: bool,
) -> None:
    """Restore removed translation files in the working tree after git failure."""
    try:
        if committed:
            subprocess.run(
                ["git", "-C", base_path, "reset", "--hard", "HEAD~1"],
                check=True,
                capture_output=True,
                timeout=30,
            )
        else:
            subprocess.run(
                ["git", "-C", base_path, "checkout", "--", *rel_paths],
                check=True,
                capture_output=True,
                timeout=30,
            )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        LOGGER.warning("Failed to restore translation files after git error: %s", e)


def _build_extension_to_format() -> dict[str, str]:
    """Build extension -> format_id from Weblate FILE_FORMATS (internal API)."""
    result = {}
    for format_cls in FILE_FORMATS.data.values():
        format_id = getattr(format_cls, "format_id", None)
        if not format_id or not getattr(format_cls, "autoload", ()):
            continue
        for pattern in format_cls.autoload:
            # e.g. "*.adoc" -> ".adoc", "*.po" -> ".po"
            if pattern.startswith("*.") and len(pattern) > 2:
                ext = "." + pattern[2:].lower()
                result[ext] = format_id
    return result


class BoostComponentService:
    """Service for managing Boost documentation components (internal Django usage)."""

    def __init__(
        self,
        organization: str,
        lang_code: str,
        version: str,
        extensions: list[str] | None = None,
    ):
        self.organization = organization
        self.lang_code = lang_code
        self.version = version
        self.extensions = extensions  # If None or empty, no filtering by extension list
        self._ext_to_format: dict[str, str] | None = None

    def get_extension_to_format(self) -> dict[str, str]:
        """Extension -> Weblate format_id from FILE_FORMATS."""
        if self._ext_to_format is None:
            self._ext_to_format = _build_extension_to_format()
        return self._ext_to_format

    def get_supported_extensions(self) -> set[str]:
        """
        Set of supported file extensions (from Weblate formats).

        If self.extensions is non-empty, restrict to those that are both
        Weblate-supported and in the list.
        """
        supported = set(self.get_extension_to_format().keys())
        if not self.extensions:
            return supported
        # Normalize: ensure leading dot and lower case for comparison
        allowed = set()
        for e in self.extensions:
            e = e.strip().lower()
            if e and not e.startswith("."):
                e = "." + e
            if e:
                allowed.add(e)
        return supported & allowed

    def clone_repository(self, submodule: str, target_dir: str, branch: str) -> bool:
        """Clone a git repository to target directory."""
        try:
            repo_url = github_https_clone_url(self.organization, submodule)
        except ValidationError as exc:
            LOGGER.error("Invalid clone URL for %s: %s", submodule, exc)
            return False

        try:
            LOGGER.info("Cloning %s to %s", repo_url, target_dir)
            cmd = ["git", "clone", "-b", branch, "--depth", "1", repo_url, target_dir]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )

            if result.returncode != 0:
                LOGGER.error("Failed to clone: %s", result.stderr)
                return False

            LOGGER.info("Cloned %s", submodule)
            return True

        except subprocess.TimeoutExpired:
            LOGGER.error("Clone timeout for %s", submodule)
            return False
        except Exception as e:
            LOGGER.error("Clone exception: %s", e)
            report_error(cause="Boost component clone")
            return False

    def scan_documentation_files(self, repo_dir: str) -> list[dict[str, Any]]:
        """
        Scan repo for doc files; return list of in-memory component configs.

        Only files in subfolders are included; files in repo root are skipped.
        Uses get_supported_extensions() which respects self.extensions when set.
        """
        supported_exts = self.get_supported_extensions()
        configs = []

        for root, dirs, files in os.walk(repo_dir):
            # Skip hidden directories and common non-doc directories
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") and d not in {"__pycache__", "node_modules"}
            ]

            for file in files:
                file_path = Path(root) / file
                ext = file_path.suffix.lower()

                if ext not in supported_exts:
                    continue

                # Exclude translation files: *_{lang_code} (e.g. intro_zh_Hans.adoc)
                if file_path.stem.endswith("_" + self.lang_code):
                    continue

                relative_path = file_path.relative_to(repo_dir)
                # Skip files in repo root (only include files in subfolders)
                if len(relative_path.parts) <= 1:
                    continue

                config = self.generate_component_config(str(relative_path), ext)
                if config:
                    configs.append(config)

        return configs

    def generate_component_config(
        self, file_path: str, extension: str
    ) -> dict[str, Any] | None:
        """Build in-memory component config for a doc file (no JSON file written)."""
        ext_to_fmt = self.get_extension_to_format()
        file_format = ext_to_fmt.get(extension)
        if not file_format:
            return None

        # Extract file name without extension
        path_obj = Path(file_path)
        filename_base = path_obj.stem
        dir_path = path_obj.parent

        # Name from path; include extension (intro.adoc vs intro.md differ).
        component_name_parts: list[str] = []
        if str(dir_path) != ".":
            component_name_parts.extend(dir_path.parts)
        component_name_parts.append(filename_base)
        ext_display = extension.lstrip(".").lower()
        component_name = " / ".join(
            part.replace("_", " ").replace("-", " ").title()
            for part in component_name_parts
        )
        component_name = f"{component_name} ({ext_display})"

        # Generate slug (include extension so doc/intro.adoc vs doc/intro.md differ)
        slug_parts = [part.lower().replace("_", "-") for part in component_name_parts]
        slug_parts.append(extension.lstrip(".").lower())
        component_slug = "-".join(slug_parts)

        # File mask for translations (e.g., "doc/intro_*.adoc" for "doc/intro.adoc")
        filemask = str(dir_path / f"{filename_base}_*{extension}")
        template = file_path
        new_base = file_path

        return {
            "component_name": component_name,
            "component_slug": component_slug,
            "filemask": filemask,
            "template": template,
            "new_base": new_base,
            "file_format": file_format,
            "file_path": file_path,
        }

    def get_or_create_project(self, submodule: str, user=None) -> Project:
        """Get or create a Weblate project for the submodule."""
        slug = _submodule_slug(submodule)
        submodule_title = submodule.replace("_", " ").title()
        project_name = f"Boost {submodule_title} Translation ({self.lang_code})"
        project_slug = f"boost-{slug}-documentation-{self.lang_code}"
        project_web = (
            f"https://www.boost.org/doc/libs/master/libs/{submodule}/doc/html/"
        )

        with transaction.atomic():
            project, created = Project.objects.get_or_create(
                slug=project_slug,
                defaults={
                    "name": project_name,
                    "web": project_web,
                    "instructions": (
                        f"Please translate the Boost.{submodule_title} "
                        "documentation. Maintain technical accuracy and follow exact "
                        "formatting conventions."
                    ),
                    "access_control": Project.ACCESS_PUBLIC,
                    "commit_policy": 0,
                },
            )

            if created:
                LOGGER.info("Created project: %s", project_name)
                # Match API: perform_create -> post_create(user, billing).
                if user:
                    project.post_create(user, billing=None)
            else:
                LOGGER.info("Project exists: %s", project_name)

            if user:
                project.acting_user = user

        return project

    def create_or_update_component(
        self,
        project: Project,
        submodule: str,
        config: dict[str, Any],
        user=None,
        request=None,
    ) -> tuple[Component | None, bool]:
        """
        Create or update a component. Returns (component, was_created).

        Settings and logic aligned with scripts/auto/create_component.py and
        scripts/auto/boost-submodule-component-configs/
        setup_boost-*-.json (same as API POST projects/{project_slug}/components/).
        """
        required_config_keys = {
            "component_slug",
            "component_name",
            "filemask",
            "template",
            "new_base",
            "file_format",
        }
        missing = required_config_keys - set(config.keys())
        if missing:
            LOGGER.error("Invalid component config: missing keys %s", missing)
            return None, False

        component_slug = truncate_component_slug(config["component_slug"])
        # Push branch name: translation-{self.lang_code}-{self.version}
        push_branch = f"translation-{self.lang_code}-{self.version}"

        # Path-based name, e.g. "Doc / ... / Intro (adoc)"
        component_name = truncate_component_name(config["component_name"])

        # Source language: "en" (hardcoded)
        try:
            source_language = Language.objects.get(code="en")
        except Language.DoesNotExist:
            LOGGER.error("Source language 'en' not found; cannot create component")
            report_error(cause="Component creation/update")
            return None, False

        # Single clone per repo: first component gets real repo, others use weblate://
        try:
            real_repo = github_ssh_repo_url(self.organization, submodule)
        except ValidationError as exc:
            LOGGER.error(
                "Invalid repo URL for %s/%s: %s", self.organization, submodule, exc
            )
            report_error(cause="Component creation/update")
            return None, False

        repo_owner = (
            Component.objects.filter(project=project, repo=real_repo)
            .order_by("slug")
            .first()
        )
        if repo_owner is not None:
            # Another component already has the clone; link to it
            repo_url = f"weblate://{project.slug}/{repo_owner.slug}"
            push_url = ""
        else:
            repo_url = real_repo
            push_url = real_repo

        # Component defaults aligned with create_component.py / reference JSON
        component_defaults = {
            "name": component_name,
            "vcs": "github",
            "repo": repo_url,
            "push": push_url,
            "branch": f"local-{self.lang_code}",
            "push_branch": push_branch,
            "filemask": config["filemask"],
            "template": config["template"],
            "new_base": config["new_base"],
            "file_format": config["file_format"],
            "edit_template": False,
            "source_language": source_language,
            "license": "",
            "allow_translation_propagation": False,
            "enable_suggestions": True,
            "suggestion_voting": False,
            "suggestion_autoaccept": 0,
            "check_flags": "",
            "language_regex": f"^{self.lang_code}$",
            "manage_units": False,
        }

        try:
            # Ensure project still exists (e.g. not deleted by another process)
            if not Project.objects.filter(pk=project.pk).exists():
                project = self.get_or_create_project(submodule, user=user)
            with transaction.atomic():
                component, created = Component.objects.get_or_create(
                    project=project,
                    slug=component_slug,
                    defaults=component_defaults,
                )

                if user:
                    component.acting_user = user

                if created:
                    LOGGER.info("Created component: %s", component.name)
                    # Match API: components POST -> post_create(..., origin="api")
                    if user:
                        component.post_create(user, origin="boost_endpoint")
                    # Repo + translations ready before add_language_to_component.
                    self._sync_component_for_translation(
                        component, request, created=True
                    )
                else:
                    LOGGER.info("Component exists: %s", component.name)
                    # Branch "local-{lang_code}" (avoid missing master/main on remote).
                    update_fields = []
                    if component.push_branch != push_branch:
                        component.push_branch = push_branch
                        update_fields.append("push_branch")
                    if update_fields:
                        component.save(update_fields=update_fields)

                    # Git pull for repo owner only; linked components share the lock.
                    self._sync_component_for_translation(
                        component, request, created=False
                    )
                self.add_language_to_component(component, request)

            return component, created

        except Exception as e:
            LOGGER.error(
                "Failed to create/update component (%s): %s",
                type(e).__name__,
                e,
            )
            report_error(cause="Component creation/update")
            return None, False

    def _do_update_git_only(self, component: Component, request) -> bool:
        """
        Perform only the git update (fetch, merge/rebase).

        Does not call create_translations. Mirrors Component.do_update lock
        block + push_if_needed; caller must call create_translations_immediate
        after.
        """
        component.translations_progress = 0
        component.translations_count = 0
        # Hold lock all time here to avoid somebody writing between commit
        # and merge/rebase.
        with component.repository.lock:
            component.store_background_task()
            component.progress_step(0)
            component.configure_repo(pull=False)

            # pull remote
            if not component.update_remote_branch():
                return False

            component.configure_branch()

            # do we have something to merge?
            try:
                needs_merge = component.repo_needs_merge()
            except RepositoryError:
                # Not yet configured repository
                needs_merge = True

            if not needs_merge:
                component.delete_alert("MergeFailure")
                component.delete_alert("RepositoryOutdated")
                return True

            # commit possible pending changes if needed
            if component.needs_commit_upstream():
                component.commit_pending(
                    "update", request.user if request else None, skip_push=True
                )

            # update local branch
            try:
                result = component.update_branch(request, method=None, skip_push=True)
            except RepositoryError:
                result = False

        if result:
            # Push after possible merge (create_translations is called by caller)
            component.push_if_needed(do_update=False)

        if not component.repo_needs_push():
            component.delete_alert("RepositoryChanges")

        component.progress_step(100)
        component.translations_count = None

        return result

    def _sync_component_for_translation(
        self, component: Component, request, *, created: bool
    ) -> None:
        """Prepare repo/translations before add_language_to_component.

        Idempotent.
        """
        if not component.is_repo_link:
            try:
                # For a newly created repo-owner component the VCS directory does not
                # exist yet.  sync_git_repo(validate=False) clones when is_valid() is
                # False, then configures the repo and branch — exactly what the ORM-
                # save path would do.  For existing components we skip straight to the
                # lighter _do_update_git_only (fetch + merge only).
                if created and not component.repository.is_valid():
                    component.sync_git_repo(skip_push=True)
                    LOGGER.info(
                        "Initial clone completed for new component: %s", component.name
                    )
                else:
                    result = self._do_update_git_only(component, request)
                    if result:
                        LOGGER.info("Updated component repository: %s", component.name)
                    else:
                        LOGGER.warning(
                            "Git update did not succeed for %s", component.name
                        )
            except Exception as e:
                LOGGER.warning(
                    "Failed to %s %s: %s",
                    "clone/update new component" if created else "update component",
                    component.name,
                    e,
                )
                report_error(
                    cause="Component creation" if created else "Component update"
                )
        try:
            component.create_translations_immediate(request=request, force=True)
            LOGGER.info(
                "%s: %s",
                "Loaded translations for new repo link"
                if created
                else "Refreshed translations for repo link",
                component.name,
            )
        except Exception as e:
            LOGGER.warning(
                "Failed to %s %s: %s",
                "load translations for new link"
                if created
                else "refresh translations for",
                component.name,
                e,
            )

    def add_language_to_component(self, component: Component, request=None) -> bool:
        """
        Add language to component if not already added.

        Logic matches API view ComponentViewSet.translations (POST).
        """
        if request is None:
            LOGGER.error("add_language_to_component requires request for permissions")
            return False

        try:
            language = Language.objects.get(code=self.lang_code)
        except Language.DoesNotExist:
            LOGGER.error("Language %s not found", self.lang_code)
            return False

        if component.translation_set.filter(language=language).exists():
            LOGGER.info(
                "Language %s already exists in %s", self.lang_code, component.name
            )
            return True

        # Order: (1) permission, (2) allowed languages, (3) sync,
        # (4) policy/validity, (5) add.
        # (1) has_perm("translation.add"): permission only, no I/O; fail fast.
        if not request.user.has_perm("translation.add", component):
            LOGGER.warning(
                "Can not create translation: no translation.add on %s", component.name
            )
            return False

        # (2) get_all_available_languages + add_more: DB only. lang_code must be
        # in the allowed set. Without add_more, restrict to basic/project langs.
        # Fail fast before I/O.
        base_languages = cast(
            "LanguageQuerySet", component.get_all_available_languages()
        )
        if not request.user.has_perm("translation.add_more", component):
            base_languages = base_languages.filter_for_add(component.project)
        if not base_languages.filter(pk=language.pk).exists():
            LOGGER.error(
                "Could not add %r to %s (language not available)",
                self.lang_code,
                component.name,
            )
            return False

        # (3) create_translations_immediate: template/new_base on disk.
        # Needed before (4): can_add_new_language checks files and template.
        try:
            component.create_translations_immediate(request=request, force=True)
        except Exception as e:
            LOGGER.warning("create_translations_immediate before add language: %s", e)
            return False

        # (4) can_add_new_language: new_lang config, template/new_base,
        # is_valid_base_for_new. Needs (3).
        if not component.can_add_new_language(request.user):
            reason = (
                getattr(component, "new_lang_error_message", None)
                or "Can not add new language"
            )
            LOGGER.warning(
                "Could not add language %s to %s: %s",
                self.lang_code,
                component.name,
                reason,
            )
            return False

        # (5) add_new_language: file + DB. Needs (3) and (4).
        try:
            translation = component.add_new_language(language, request)
        except Exception as e:
            LOGGER.error("Failed to add language %s: %s", self.lang_code, e)
            report_error(cause="Add language")
            return False

        if translation is None:
            storage = get_messages(request)
            message = (
                "\n".join(m.message for m in storage)
                if storage
                else (
                    getattr(component, "new_lang_error_message", None)
                    or f"Could not add {self.lang_code!r}!"
                )
            )
            LOGGER.warning(
                "Could not add language %s to %s: %s",
                self.lang_code,
                component.name,
                message,
            )
            return False

        LOGGER.info("Added language %s to %s", self.lang_code, component.name)
        return True

    def _delete_component_and_commit_removal(
        self, component: Component, result: dict[str, Any]
    ) -> None:
        """
        Remove translation files, commit and push, then delete the component.

        DB deletion is deferred until after git push succeeds so a failed push
        does not leave the database inconsistent with the remote repository.

        Updates result["components_deleted"] and result["errors"] as needed.
        """
        name = component.name
        base_path = component.full_path
        repo_owner = component.linked_component if component.is_repo_link else component
        if repo_owner is None:
            LOGGER.warning(
                "Cannot push after delete: no linked component for %s", component.slug
            )
            push_branch = None
            push_url = None
        else:
            push_branch = repo_owner.push_branch
            push_url = repo_owner.push
        translation_files = [
            os.path.join(base_path, t.filename)
            for t in component.translation_set.exclude(
                language=component.source_language
            )
        ]

        actually_removed = []
        for file_path in translation_files:
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    actually_removed.append(file_path)
                    LOGGER.info("Removed translation file: %s", file_path)
                except OSError as e:
                    LOGGER.warning(
                        "Failed to remove translation file %s: %s",
                        file_path,
                        e,
                    )
                    result["errors"].append(
                        to_error_dict(
                            BoostEndpointErrorCode.FILE_REMOVE_FAILED,
                            f"Failed to remove {file_path}: {e}",
                            file_path=file_path,
                        )
                    )

        if actually_removed and os.path.isdir(os.path.join(base_path, ".git")):
            rel_paths = [os.path.relpath(p, base_path) for p in actually_removed]
            ok, err, committed = _git_commit_and_push_removals(
                base_path,
                rel_paths,
                name=name,
                push_url=push_url,
                push_branch=push_branch,
            )
            if not ok:
                result["errors"].append(
                    err
                    or to_error_dict(
                        BoostEndpointErrorCode.GIT_PUSH_FAILED,
                        "Git commit/push failed",
                        component_name=name,
                    )
                )
                _git_restore_removed_files(base_path, rel_paths, committed=committed)
                return

        with transaction.atomic():
            component.delete()

        result["components_deleted"] += 1
        LOGGER.info("Deleted component (not in configs): %s", name)

    def process_submodule(
        self, submodule: str, temp_dir: str, user=None, request=None
    ) -> dict[str, Any]:
        """Process a single submodule: clone, scan, create/update components."""
        result: dict[str, Any] = {
            "submodule": submodule,
            "success": False,
            "components_created": 0,
            "components_updated": 0,
            "components_failed": 0,
            "components_deleted": 0,
            "errors": [],
        }

        try:
            validate_repo_segment(self.organization, field="organization")
            validate_repo_segment(submodule, field="submodule")
        except ValidationError as exc:
            append_error(
                result,
                BoostEndpointErrorCode.INVALID_CLONE_URL,
                str(exc),
                submodule=submodule,
                organization=self.organization,
            )
            return result

        # Create temp directory for this submodule
        temp_submodule_dir = os.path.join(temp_dir, submodule)
        resolved = Path(temp_submodule_dir).resolve()
        temp_dir_resolved = Path(temp_dir).resolve()
        try:
            resolved.relative_to(temp_dir_resolved)
        except ValueError:
            append_error(
                result,
                BoostEndpointErrorCode.INVALID_SUBMODULE,
                f"Invalid submodule name: {submodule}",
                submodule=submodule,
            )
            return result
        os.makedirs(temp_submodule_dir, exist_ok=True)

        # Clone repository
        if not self.clone_repository(
            submodule, temp_submodule_dir, f"local-{self.lang_code}"
        ):
            append_error(
                result,
                BoostEndpointErrorCode.CLONE_FAILED,
                f"Failed to clone repository for {submodule}",
                submodule=submodule,
                organization=self.organization,
                lang_code=self.lang_code,
            )
            return result

        # Scan for documentation files
        configs = self.scan_documentation_files(temp_submodule_dir)
        if not configs:
            append_error(
                result,
                BoostEndpointErrorCode.NO_DOCUMENTATION_FILES,
                f"No supported documentation files found in {submodule}",
                submodule=submodule,
            )
            return result

        LOGGER.info("Found %s documentation files in %s", len(configs), submodule)

        # Check permissions before creating so no Project is committed when denied
        slug = _submodule_slug(submodule)
        project_slug = f"boost-{slug}-documentation-{self.lang_code}"
        existing_project = Project.objects.filter(slug=project_slug).first()
        if request is not None and user is not None:
            if existing_project is not None:
                if not user.has_perm("project.edit", existing_project):
                    append_error(
                        result,
                        BoostEndpointErrorCode.PERMISSION_DENIED,
                        "Can not create components (missing project.edit)",
                        permission="project.edit",
                        project_slug=project_slug,
                    )
                    return result
            elif not user.has_perm("project.add"):
                append_error(
                    result,
                    BoostEndpointErrorCode.PERMISSION_DENIED,
                    "Can not create project (missing project.add)",
                    permission="project.add",
                    project_slug=project_slug,
                )
                return result

        # Get or create project
        try:
            project = self.get_or_create_project(submodule, user)
        except Exception as e:
            append_error(
                result,
                BoostEndpointErrorCode.PROJECT_CREATE_FAILED,
                f"Failed to create project: {e}",
                submodule=submodule,
                exception_type=type(e).__name__,
            )
            report_error(cause="Project creation")
            return result

        # Create or update components
        for config in configs:
            component, was_created = self.create_or_update_component(
                project, submodule, config, user=user, request=request
            )
            if component is not None:
                if was_created:
                    result["components_created"] += 1
                else:
                    result["components_updated"] += 1
            else:
                result["components_failed"] += 1

        # Delete components that are not in configs (no longer in repo scan).
        # Never delete glossary components (is_glossary); they are managed by Weblate.
        wanted_slugs = {truncate_component_slug(c["component_slug"]) for c in configs}
        for component in project.component_set.all():
            if component.slug not in wanted_slugs and not component.is_glossary:
                try:
                    self._delete_component_and_commit_removal(component, result)
                except Exception as e:
                    LOGGER.warning(
                        "Failed to delete component %s: %s", component.slug, e
                    )
                    append_error(
                        result,
                        BoostEndpointErrorCode.COMPONENT_DELETE_FAILED,
                        f"Failed to delete {component.slug}: {e}",
                        component_slug=component.slug,
                        exception_type=type(e).__name__,
                    )

        any_component_ok = (
            result["components_created"] + result["components_updated"]
        ) > 0
        result["success"] = any_component_ok
        if not any_component_ok and result["components_failed"]:
            append_error(
                result,
                BoostEndpointErrorCode.ALL_COMPONENTS_FAILED,
                "Failed to create or update every scanned component "
                f"({result['components_failed']} config(s))",
                components_failed=result["components_failed"],
            )
        return result

    def process_all(
        self, submodules: list[str], user=None, request=None
    ) -> dict[str, Any]:
        """Process all submodules."""
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="boost_endpoint_")
        LOGGER.info("Using temp directory: %s", temp_dir)

        results: dict[str, Any] = {
            "total_submodules": len(submodules),
            "successful": 0,
            "failed": 0,
            "submodule_results": [],
        }

        try:
            for submodule in submodules:
                LOGGER.info("Processing submodule: %s", submodule)
                result = self.process_submodule(
                    submodule, temp_dir, user=user, request=request
                )
                results["submodule_results"].append(result)

                if result["success"]:
                    results["successful"] += 1
                else:
                    results["failed"] += 1

        finally:
            # Cleanup temp directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                LOGGER.info("Cleaned up temp directory: %s", temp_dir)

        return results
