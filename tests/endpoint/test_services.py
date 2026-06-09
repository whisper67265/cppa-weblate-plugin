# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import inspect
import os
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from boost_weblate.endpoint.errors import BoostEndpointErrorCode
from boost_weblate.endpoint.services import (
    BoostComponentService,
    _build_extension_to_format,
    _git_commit_and_push_removals,
    _submodule_slug,
    truncate_component_name,
    truncate_component_slug,
)

# ---------------------------------------------------------------------------
# Pure-Python helpers (no Weblate ORM needed)
# ---------------------------------------------------------------------------


def _has_error_code(errors: list, code: BoostEndpointErrorCode | str) -> bool:
    expected = code.value if isinstance(code, BoostEndpointErrorCode) else code
    return any(e.get("code") == expected for e in errors)


class TestSubmoduleSlug:
    def test_lowercase(self) -> None:
        assert _submodule_slug("MyLib") == "mylib"

    def test_underscores_to_hyphens(self) -> None:
        assert _submodule_slug("my_lib") == "my-lib"

    def test_mixed(self) -> None:
        assert _submodule_slug("My_Lib") == "my-lib"

    def test_already_lowercase_hyphen(self) -> None:
        assert _submodule_slug("my-lib") == "my-lib"


class TestTruncateComponentName:
    def test_short_name_unchanged(self) -> None:
        assert truncate_component_name("short", max_len=100) == "short"

    def test_exact_length_unchanged(self) -> None:
        name = "a" * 100
        assert truncate_component_name(name, max_len=100) == name

    def test_over_limit_truncated_with_hash(self) -> None:
        name = "x" * 110
        result = truncate_component_name(name, max_len=100)
        assert len(result) == 100
        assert result.endswith("]")
        assert result[-(10 - 1)].isalnum()  # hex chars in suffix

    def test_two_different_long_names_differ(self) -> None:
        a = "a" * 110
        b = "b" * 110
        assert truncate_component_name(a, max_len=100) != truncate_component_name(
            b, max_len=100
        )

    def test_same_name_is_idempotent(self) -> None:
        name = "z" * 110
        r1 = truncate_component_name(name, max_len=100)
        r2 = truncate_component_name(name, max_len=100)
        assert r1 == r2


class TestTruncateComponentSlug:
    def test_short_slug_unchanged(self) -> None:
        assert truncate_component_slug("my-slug", max_len=100) == "my-slug"

    def test_over_limit_truncated(self) -> None:
        slug = "s" * 110
        result = truncate_component_slug(slug, max_len=100)
        assert len(result) == 100
        assert "-" in result

    def test_two_different_long_slugs_differ(self) -> None:
        a = "a" * 110
        b = "b" * 110
        assert truncate_component_slug(a, max_len=100) != truncate_component_slug(
            b, max_len=100
        )


# ---------------------------------------------------------------------------
# _build_extension_to_format (mocks FILE_FORMATS)
# ---------------------------------------------------------------------------


class TestBuildExtensionToFormat:
    def test_maps_autoload_patterns(self) -> None:
        fake_cls = MagicMock()
        fake_cls.format_id = "po"
        fake_cls.autoload = ["*.po"]

        with patch("boost_weblate.endpoint.services.FILE_FORMATS") as mock_ff:
            mock_ff.data = {"po": fake_cls}
            result = _build_extension_to_format()

        assert result == {".po": "po"}

    def test_skips_format_without_autoload(self) -> None:
        fake_cls = MagicMock()
        fake_cls.format_id = "po"
        fake_cls.autoload = []

        with patch("boost_weblate.endpoint.services.FILE_FORMATS") as mock_ff:
            mock_ff.data = {"po": fake_cls}
            result = _build_extension_to_format()

        assert result == {}

    def test_skips_format_without_format_id(self) -> None:
        fake_cls = MagicMock(spec=[])  # no attributes
        with patch("boost_weblate.endpoint.services.FILE_FORMATS") as mock_ff:
            mock_ff.data = {"x": fake_cls}
            result = _build_extension_to_format()

        assert result == {}

    def test_multiple_extensions(self) -> None:
        cls1 = MagicMock()
        cls1.format_id = "po"
        cls1.autoload = ["*.po"]
        cls2 = MagicMock()
        cls2.format_id = "ts"
        cls2.autoload = ["*.ts"]

        with patch("boost_weblate.endpoint.services.FILE_FORMATS") as mock_ff:
            mock_ff.data = {"po": cls1, "ts": cls2}
            result = _build_extension_to_format()

        assert result == {".po": "po", ".ts": "ts"}


# ---------------------------------------------------------------------------
# BoostComponentService — pure-Python methods
# ---------------------------------------------------------------------------


def _make_svc(**kwargs):
    defaults = dict(organization="boost", lang_code="zh_Hans", version="1.0")
    defaults.update(kwargs)
    return BoostComponentService(**defaults)


class TestGetSupportedExtensions:
    def _svc_with_formats(self, svc, formats):
        """Patch get_extension_to_format to return given formats dict."""
        svc._ext_to_format = formats
        return svc

    def test_no_filter_returns_all(self) -> None:
        svc = _make_svc(extensions=None)
        self._svc_with_formats(svc, {".po": "po", ".adoc": "adoc"})
        assert svc.get_supported_extensions() == {".po", ".adoc"}

    def test_empty_list_returns_all(self) -> None:
        svc = _make_svc(extensions=[])
        self._svc_with_formats(svc, {".po": "po", ".adoc": "adoc"})
        assert svc.get_supported_extensions() == {".po", ".adoc"}

    def test_filter_restricts_to_intersection(self) -> None:
        svc = _make_svc(extensions=[".po"])
        self._svc_with_formats(svc, {".po": "po", ".adoc": "adoc"})
        assert svc.get_supported_extensions() == {".po"}

    def test_filter_adds_leading_dot(self) -> None:
        svc = _make_svc(extensions=["po"])
        self._svc_with_formats(svc, {".po": "po", ".adoc": "adoc"})
        assert svc.get_supported_extensions() == {".po"}

    def test_filter_unsupported_extension_returns_empty(self) -> None:
        svc = _make_svc(extensions=[".xyz"])
        self._svc_with_formats(svc, {".po": "po"})
        assert svc.get_supported_extensions() == set()


class TestGenerateComponentConfig:
    def setup_method(self) -> None:
        self.svc = _make_svc()
        self.svc._ext_to_format = {".adoc": "adoc", ".po": "po"}

    def test_returns_none_for_unknown_extension(self) -> None:
        result = self.svc.generate_component_config("doc/intro.xyz", ".xyz")
        assert result is None

    def test_basic_config_shape(self) -> None:
        result = self.svc.generate_component_config("doc/intro.adoc", ".adoc")
        assert result is not None
        assert result["file_format"] == "adoc"
        assert "component_name" in result
        assert "component_slug" in result
        assert "filemask" in result
        assert "template" in result
        assert "new_base" in result
        assert "file_path" in result

    def test_filemask_uses_lang_wildcard(self) -> None:
        result = self.svc.generate_component_config("doc/intro.adoc", ".adoc")
        assert result is not None
        assert "_*" in result["filemask"]
        assert result["filemask"].endswith(".adoc")

    def test_template_is_original_path(self) -> None:
        result = self.svc.generate_component_config("doc/intro.adoc", ".adoc")
        assert result is not None
        assert result["template"] == "doc/intro.adoc"

    def test_slug_uses_hyphens_and_extension(self) -> None:
        result = self.svc.generate_component_config("doc/my_intro.adoc", ".adoc")
        assert result is not None
        assert "adoc" in result["component_slug"]
        assert "_" not in result["component_slug"]

    def test_component_name_includes_extension(self) -> None:
        result = self.svc.generate_component_config("doc/intro.adoc", ".adoc")
        assert result is not None
        assert "(adoc)" in result["component_name"]

    def test_nested_path_included_in_name(self) -> None:
        result = self.svc.generate_component_config("a/b/intro.adoc", ".adoc")
        assert result is not None
        # Path parts should be reflected in name
        assert (
            "A" in result["component_name"] or "a" in result["component_name"].lower()
        )


class TestScanDocumentationFiles:
    def setup_method(self) -> None:
        self.svc = _make_svc(lang_code="zh_Hans")
        self.svc._ext_to_format = {".adoc": "adoc", ".po": "po"}

    def test_empty_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            assert self.svc.scan_documentation_files(d) == []

    def test_files_in_root_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "intro.adoc").write_text("x")
            result = self.svc.scan_documentation_files(d)
        assert result == []

    def test_files_in_subdir_are_included(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "doc"
            sub.mkdir()
            (sub / "intro.adoc").write_text("x")
            result = self.svc.scan_documentation_files(d)
        assert len(result) == 1
        assert result[0]["file_format"] == "adoc"

    def test_translation_files_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "doc"
            sub.mkdir()
            (sub / "intro.adoc").write_text("source")
            (sub / "intro_zh_Hans.adoc").write_text("translation")
            result = self.svc.scan_documentation_files(d)
        # Only the source file; translation file excluded
        assert len(result) == 1
        assert "intro_zh_Hans" not in result[0]["file_path"]

    def test_hidden_dirs_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            hidden = Path(d) / ".git"
            hidden.mkdir()
            (hidden / "intro.adoc").write_text("x")
            result = self.svc.scan_documentation_files(d)
        assert result == []

    def test_unsupported_extension_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "doc"
            sub.mkdir()
            (sub / "README.txt").write_text("x")
            result = self.svc.scan_documentation_files(d)
        assert result == []

    def test_multiple_files_multiple_configs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "doc"
            sub.mkdir()
            (sub / "a.adoc").write_text("a")
            (sub / "b.adoc").write_text("b")
            result = self.svc.scan_documentation_files(d)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# clone_repository (mocks subprocess.run)
# ---------------------------------------------------------------------------


class TestCloneRepository:
    def setup_method(self) -> None:
        self.svc = _make_svc()

    def test_successful_clone_returns_true(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch(
            "boost_weblate.endpoint.services.subprocess.run", return_value=mock_result
        ):
            assert self.svc.clone_repository("mylib", "/tmp/mylib", "main") is True

    def test_nonzero_returncode_returns_false(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "fatal: repository not found"

        with patch(
            "boost_weblate.endpoint.services.subprocess.run", return_value=mock_result
        ):
            assert self.svc.clone_repository("mylib", "/tmp/mylib", "main") is False

    def test_timeout_returns_false(self) -> None:
        with patch(
            "boost_weblate.endpoint.services.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=300),
        ):
            assert self.svc.clone_repository("mylib", "/tmp/mylib", "main") is False

    def test_generic_exception_returns_false(self) -> None:
        with (
            patch(
                "boost_weblate.endpoint.services.subprocess.run",
                side_effect=OSError("disk full"),
            ),
            patch("boost_weblate.endpoint.services.report_error"),
        ):
            assert self.svc.clone_repository("mylib", "/tmp/mylib", "main") is False

    def test_builds_correct_url(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return mock_result

        with patch(
            "boost_weblate.endpoint.services.subprocess.run", side_effect=fake_run
        ):
            self.svc.clone_repository("mylib", "/tmp/out", "mybranch")

        assert len(calls) == 1
        cmd = calls[0]
        assert "https://github.com/boost/mylib.git" in cmd
        assert "-b" in cmd
        assert "mybranch" in cmd


# ---------------------------------------------------------------------------
# get_or_create_project (mocks Project ORM)
# ---------------------------------------------------------------------------


class TestGetOrCreateProject:
    def setup_method(self) -> None:
        self.svc = _make_svc(lang_code="zh_Hans")

    def _make_mock_project(self, created=False):
        project = MagicMock()
        project.pk = 1
        project.acting_user = None
        return project, created

    def test_returns_project_when_exists(self) -> None:
        project, _ = self._make_mock_project(created=False)

        with (
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.transaction"),
        ):
            MockProject.objects.get_or_create.return_value = (project, False)
            MockProject.ACCESS_PUBLIC = 0
            result = self.svc.get_or_create_project("json", user=None)

        assert result is project

    def test_calls_post_create_when_new_and_user_given(self) -> None:
        project = MagicMock()
        project.pk = 1
        user = MagicMock()

        with (
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.transaction"),
        ):
            MockProject.objects.get_or_create.return_value = (project, True)
            MockProject.ACCESS_PUBLIC = 0
            self.svc.get_or_create_project("json", user=user)

        project.post_create.assert_called_once_with(user, billing=None)

    def test_no_post_create_when_existing(self) -> None:
        project = MagicMock()
        project.pk = 1
        user = MagicMock()

        with (
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.transaction"),
        ):
            MockProject.objects.get_or_create.return_value = (project, False)
            MockProject.ACCESS_PUBLIC = 0
            self.svc.get_or_create_project("json", user=user)

        project.post_create.assert_not_called()

    def test_sets_acting_user(self) -> None:
        project = MagicMock()
        project.pk = 1
        user = MagicMock()

        with (
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.transaction"),
        ):
            MockProject.objects.get_or_create.return_value = (project, False)
            MockProject.ACCESS_PUBLIC = 0
            self.svc.get_or_create_project("json", user=user)

        assert project.acting_user == user

    def test_project_slug_format(self) -> None:
        """Project slug should encode submodule and lang_code (casing preserved)."""
        project = MagicMock()
        project.pk = 1
        captured_kwargs = {}

        def fake_get_or_create(**kwargs):
            captured_kwargs.update(kwargs)
            return project, False

        with (
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.transaction"),
        ):
            MockProject.objects.get_or_create.side_effect = fake_get_or_create
            MockProject.ACCESS_PUBLIC = 0
            self.svc.get_or_create_project("my_lib", user=None)

        assert captured_kwargs["slug"] == "boost-my-lib-documentation-zh_Hans"


# ---------------------------------------------------------------------------
# create_or_update_component (mocks Language + Component ORM)
# ---------------------------------------------------------------------------


class TestCreateOrUpdateComponent:
    def setup_method(self) -> None:
        self.svc = _make_svc(lang_code="zh_Hans", version="1.0")
        self.project = MagicMock()
        self.project.pk = 1
        self.project.slug = "boost-json-documentation-zh_hans"
        self.config = {
            "component_slug": "doc-intro-adoc",
            "component_name": "Doc / Intro (adoc)",
            "filemask": "doc/intro_*.adoc",
            "template": "doc/intro.adoc",
            "new_base": "doc/intro.adoc",
            "file_format": "adoc",
        }

    def test_missing_config_keys_returns_none(self) -> None:
        bad_config = {"component_slug": "x"}  # missing many keys
        result, created = self.svc.create_or_update_component(
            self.project, "json", bad_config
        )
        assert result is None
        assert created is False

    def test_language_not_found_returns_none(self) -> None:
        with (
            patch("boost_weblate.endpoint.services.Language") as MockLang,
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.Component") as MockComp,
            patch("boost_weblate.endpoint.services.transaction"),
            patch("boost_weblate.endpoint.services.report_error"),
        ):
            lang_not_found = Exception("Language.DoesNotExist")
            MockLang.objects.get.side_effect = lang_not_found
            MockLang.DoesNotExist = type(lang_not_found)
            MockProject.objects.filter.return_value.exists.return_value = True
            repo_owner_qs = MockComp.objects.filter.return_value.order_by.return_value
            repo_owner_qs.first.return_value = None
            result, created = self.svc.create_or_update_component(
                self.project, "json", self.config
            )
        assert result is None
        assert created is False

    def test_creates_new_component(self) -> None:
        source_lang = MagicMock()
        component = MagicMock()
        component.push_branch = "translation-zh_Hans-1.0"
        component.is_repo_link = False

        with (
            patch("boost_weblate.endpoint.services.Language") as MockLang,
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.Component") as MockComp,
            patch("boost_weblate.endpoint.services.transaction"),
            patch.object(self.svc, "_sync_component_for_translation"),
            patch.object(self.svc, "add_language_to_component"),
        ):
            MockLang.objects.get.return_value = source_lang
            MockProject.objects.filter.return_value.exists.return_value = True
            repo_owner_qs = MockComp.objects.filter.return_value.order_by.return_value
            repo_owner_qs.first.return_value = None
            MockComp.objects.get_or_create.return_value = (component, True)
            result, created = self.svc.create_or_update_component(
                self.project, "json", self.config, user=None
            )

        assert result is component
        assert created is True

    def test_updates_existing_component(self) -> None:
        source_lang = MagicMock()
        component = MagicMock()
        component.push_branch = "old-branch"
        component.is_repo_link = False

        with (
            patch("boost_weblate.endpoint.services.Language") as MockLang,
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.Component") as MockComp,
            patch("boost_weblate.endpoint.services.transaction"),
            patch.object(self.svc, "_sync_component_for_translation"),
            patch.object(self.svc, "add_language_to_component"),
        ):
            MockLang.objects.get.return_value = source_lang
            MockProject.objects.filter.return_value.exists.return_value = True
            repo_owner_qs = MockComp.objects.filter.return_value.order_by.return_value
            repo_owner_qs.first.return_value = None
            MockComp.objects.get_or_create.return_value = (component, False)
            result, created = self.svc.create_or_update_component(
                self.project, "json", self.config, user=None
            )

        assert result is component
        assert created is False

    def test_exception_returns_none(self) -> None:
        with (
            patch("boost_weblate.endpoint.services.Language") as MockLang,
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.transaction"),
            patch("boost_weblate.endpoint.services.report_error"),
        ):
            MockLang.objects.get.return_value = MagicMock()
            MockProject.objects.filter.return_value.exists.return_value = True
            # Simulate unexpected crash
            with patch("boost_weblate.endpoint.services.Component") as MockComp:
                repo_owner_qs = (
                    MockComp.objects.filter.return_value.order_by.return_value
                )
                repo_owner_qs.first.return_value = None
                MockComp.objects.get_or_create.side_effect = RuntimeError("db error")
                result, created = self.svc.create_or_update_component(
                    self.project, "json", self.config
                )

        assert result is None
        assert created is False


# ---------------------------------------------------------------------------
# add_language_to_component (mocks Language ORM + component attributes)
# ---------------------------------------------------------------------------


class TestAddLanguageToComponent:
    def setup_method(self) -> None:
        self.svc = _make_svc(lang_code="zh_Hans")

    def test_no_request_returns_false(self) -> None:
        component = MagicMock()
        assert self.svc.add_language_to_component(component, request=None) is False

    def test_language_not_found_returns_false(self) -> None:
        request = MagicMock()
        component = MagicMock()

        with patch("boost_weblate.endpoint.services.Language") as MockLang:
            does_not_exist = type("DoesNotExist", (Exception,), {})
            MockLang.DoesNotExist = does_not_exist
            MockLang.objects.get.side_effect = does_not_exist("not found")
            result = self.svc.add_language_to_component(component, request)

        assert result is False

    def test_language_already_in_component_returns_true(self) -> None:
        request = MagicMock()
        language = MagicMock()
        component = MagicMock()
        component.translation_set.filter.return_value.exists.return_value = True

        with patch("boost_weblate.endpoint.services.Language") as MockLang:
            MockLang.objects.get.return_value = language
            result = self.svc.add_language_to_component(component, request)

        assert result is True

    def test_no_add_permission_returns_false(self) -> None:
        request = MagicMock()
        request.user.has_perm.return_value = False
        language = MagicMock()
        component = MagicMock()
        component.translation_set.filter.return_value.exists.return_value = False

        with patch("boost_weblate.endpoint.services.Language") as MockLang:
            MockLang.objects.get.return_value = language
            result = self.svc.add_language_to_component(component, request)

        assert result is False

    def test_language_not_available_returns_false(self) -> None:
        request = MagicMock()
        # has_perm always True so filter_for_add is NOT called;
        # language unavailability comes from filter(pk=...).exists() == False.
        request.user.has_perm.return_value = True
        language = MagicMock()
        component = MagicMock()
        component.translation_set.filter.return_value.exists.return_value = False
        qs = MagicMock()
        qs.filter.return_value.exists.return_value = False
        component.get_all_available_languages.return_value = qs

        with patch("boost_weblate.endpoint.services.Language") as MockLang:
            MockLang.objects.get.return_value = language
            result = self.svc.add_language_to_component(component, request)

        assert result is False

    def test_create_translations_exception_returns_false(self) -> None:
        request = MagicMock()
        request.user.has_perm.return_value = True
        language = MagicMock()
        component = MagicMock()
        component.name = "Test"
        component.translation_set.filter.return_value.exists.return_value = False
        avail_qs = component.get_all_available_languages.return_value
        avail_qs.filter.return_value.exists.return_value = True
        component.create_translations_immediate.side_effect = Exception("fail")

        with patch("boost_weblate.endpoint.services.Language") as MockLang:
            MockLang.objects.get.return_value = language
            result = self.svc.add_language_to_component(component, request)

        assert result is False

    def test_cannot_add_new_language_returns_false(self) -> None:
        request = MagicMock()
        request.user.has_perm.return_value = True
        language = MagicMock()
        component = MagicMock()
        component.name = "Test"
        component.translation_set.filter.return_value.exists.return_value = False
        avail_qs = component.get_all_available_languages.return_value
        avail_qs.filter.return_value.exists.return_value = True
        component.create_translations_immediate.return_value = None
        component.can_add_new_language.return_value = False

        with patch("boost_weblate.endpoint.services.Language") as MockLang:
            MockLang.objects.get.return_value = language
            result = self.svc.add_language_to_component(component, request)

        assert result is False

    def test_add_new_language_returns_none_means_false(self) -> None:
        request = MagicMock()
        request.user.has_perm.return_value = True
        language = MagicMock()
        component = MagicMock()
        component.name = "Test"
        component.translation_set.filter.return_value.exists.return_value = False
        avail_qs = component.get_all_available_languages.return_value
        avail_qs.filter.return_value.exists.return_value = True
        component.create_translations_immediate.return_value = None
        component.can_add_new_language.return_value = True
        component.add_new_language.return_value = None

        with (
            patch("boost_weblate.endpoint.services.Language") as MockLang,
            patch("boost_weblate.endpoint.services.get_messages", return_value=[]),
        ):
            MockLang.objects.get.return_value = language
            result = self.svc.add_language_to_component(component, request)

        assert result is False

    def test_successful_add_returns_true(self) -> None:
        request = MagicMock()
        request.user.has_perm.return_value = True
        language = MagicMock()
        translation = MagicMock()
        component = MagicMock()
        component.name = "Test"
        component.translation_set.filter.return_value.exists.return_value = False
        avail_qs = component.get_all_available_languages.return_value
        avail_qs.filter.return_value.exists.return_value = True
        component.create_translations_immediate.return_value = None
        component.can_add_new_language.return_value = True
        component.add_new_language.return_value = translation

        with patch("boost_weblate.endpoint.services.Language") as MockLang:
            MockLang.objects.get.return_value = language
            result = self.svc.add_language_to_component(component, request)

        assert result is True


# ---------------------------------------------------------------------------
# _git_commit_and_push_removals
# ---------------------------------------------------------------------------


class TestGitCommitAndPushRemovals:
    def test_commit_limits_paths_to_removed_files(self) -> None:
        mock_status = MagicMock()
        mock_status.returncode = 0
        mock_status.stdout = "D zh_Hans/intro.adoc\n"

        with patch("boost_weblate.endpoint.services.subprocess.run") as mock_run:
            mock_run.side_effect = [MagicMock(), mock_status, MagicMock()]
            ok, err, committed = _git_commit_and_push_removals(
                "/repo",
                ["zh_Hans/intro.adoc", "zh_Hans/other.adoc"],
                name="TestComp",
                push_url=None,
                push_branch=None,
            )

        assert ok is True
        assert err is None
        assert committed is True
        commit_args = mock_run.call_args_list[2].args[0]
        assert commit_args[3] == "commit"
        sep = commit_args.index("--")
        assert commit_args[sep + 1 :] == [
            "zh_Hans/intro.adoc",
            "zh_Hans/other.adoc",
        ]

    def test_git_status_failure_returns_error(self) -> None:
        mock_status = MagicMock()
        mock_status.returncode = 128
        mock_status.stderr = "fatal: not a git repository"

        with patch("boost_weblate.endpoint.services.subprocess.run") as mock_run:
            mock_run.side_effect = [MagicMock(), mock_status]
            ok, err, committed = _git_commit_and_push_removals(
                "/repo",
                ["zh_Hans/intro.adoc"],
                name="TestComp",
                push_url=None,
                push_branch=None,
            )

        assert ok is False
        assert committed is False
        assert err is not None
        assert err["code"] == BoostEndpointErrorCode.GIT_PUSH_FAILED.value
        assert err["metadata"]["returncode"] == 128
        assert mock_run.call_count == 2


# ---------------------------------------------------------------------------
# _delete_component_and_commit_removal (mocks component + subprocess)
# ---------------------------------------------------------------------------


class TestDeleteComponentAndCommitRemoval:
    def setup_method(self) -> None:
        self.svc = _make_svc()

    def _make_component(self, *, is_repo_link=False, translation_files=None):
        component = MagicMock()
        component.name = "TestComp"
        component.is_repo_link = is_repo_link
        component.full_path = "/fake/path"
        component.is_glossary = False
        if is_repo_link:
            linked = MagicMock()
            linked.push_branch = "translation-zh_Hans-1.0"
            linked.push = "git@github.com:boost/json.git"
            component.linked_component = linked
        else:
            component.push_branch = "translation-zh_Hans-1.0"
            component.push = "git@github.com:boost/json.git"
            component.linked_component = None

        source_lang = MagicMock()
        component.source_language = source_lang

        translations = []
        for fname in translation_files or []:
            t = MagicMock()
            t.filename = fname
            translations.append(t)

        component.translation_set.exclude.return_value = translations
        return component

    def _git_success_side_effect(self):
        mock_status = MagicMock()
        mock_status.returncode = 0
        mock_status.stdout = "D zh_Hans/intro.adoc\n"
        return [MagicMock(), mock_status, MagicMock(), MagicMock()]

    def _git_push_failure_side_effect(self):
        mock_status = MagicMock()
        mock_status.returncode = 0
        mock_status.stdout = "D zh_Hans/intro.adoc\n"
        err = subprocess.CalledProcessError(1, "git", stderr="push failed")
        return [MagicMock(), mock_status, MagicMock(), err, MagicMock()]

    def test_increments_components_deleted(self) -> None:
        component = self._make_component()
        result = {"components_deleted": 0, "errors": []}
        with patch(
            "boost_weblate.endpoint.services.transaction.atomic",
            return_value=nullcontext(),
        ):
            self.svc._delete_component_and_commit_removal(component, result)
        assert result["components_deleted"] == 1
        component.delete.assert_called_once()

    def test_linked_component_is_none_no_push(self) -> None:
        component = self._make_component(is_repo_link=True)
        component.linked_component = None
        result = {"components_deleted": 0, "errors": []}
        with patch(
            "boost_weblate.endpoint.services.transaction.atomic",
            return_value=nullcontext(),
        ):
            self.svc._delete_component_and_commit_removal(component, result)
        assert result["components_deleted"] == 1
        component.delete.assert_called_once()

    def test_git_subprocess_called_when_files_removed(self) -> None:
        component = self._make_component(translation_files=["zh_Hans/intro.adoc"])
        result = {"components_deleted": 0, "errors": []}

        with (
            patch("os.path.isfile", return_value=True),
            patch("os.remove"),
            patch("os.path.isdir", return_value=True),
            patch("os.path.relpath", return_value="zh_Hans/intro.adoc"),
            patch("boost_weblate.endpoint.services.subprocess.run") as mock_run,
            patch(
                "boost_weblate.endpoint.services.transaction.atomic",
                return_value=nullcontext(),
            ),
        ):
            mock_run.side_effect = self._git_success_side_effect()
            self.svc._delete_component_and_commit_removal(component, result)

        assert mock_run.called
        component.delete.assert_called_once()

    def test_push_success_deletes_component(self) -> None:
        component = self._make_component(translation_files=["zh_Hans/intro.adoc"])
        result = {"components_deleted": 0, "errors": []}

        with (
            patch("os.path.isfile", return_value=True),
            patch("os.remove"),
            patch("os.path.isdir", return_value=True),
            patch("os.path.relpath", return_value="zh_Hans/intro.adoc"),
            patch("boost_weblate.endpoint.services.subprocess.run") as mock_run,
            patch(
                "boost_weblate.endpoint.services.transaction.atomic",
                return_value=nullcontext(),
            ),
        ):
            mock_run.side_effect = self._git_success_side_effect()
            self.svc._delete_component_and_commit_removal(component, result)

        assert result["components_deleted"] == 1
        assert result["errors"] == []
        component.delete.assert_called_once()

    def test_subprocess_error_appended_to_errors(self) -> None:
        component = self._make_component(translation_files=["zh_Hans/intro.adoc"])
        result = {"components_deleted": 0, "errors": []}

        with (
            patch("os.path.isfile", return_value=True),
            patch("os.remove"),
            patch("os.path.isdir", return_value=True),
            patch("os.path.relpath", return_value="zh_Hans/intro.adoc"),
            patch("boost_weblate.endpoint.services.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = self._git_push_failure_side_effect()
            self.svc._delete_component_and_commit_removal(component, result)

        assert _has_error_code(result["errors"], BoostEndpointErrorCode.GIT_PUSH_FAILED)
        assert result["components_deleted"] == 0
        component.delete.assert_not_called()

    def test_push_failure_restores_working_tree(self) -> None:
        component = self._make_component(translation_files=["zh_Hans/intro.adoc"])
        result = {"components_deleted": 0, "errors": []}

        with (
            patch("os.path.isfile", return_value=True),
            patch("os.remove"),
            patch("os.path.isdir", return_value=True),
            patch("os.path.relpath", return_value="zh_Hans/intro.adoc"),
            patch("boost_weblate.endpoint.services.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = self._git_push_failure_side_effect()
            self.svc._delete_component_and_commit_removal(component, result)

        restore_call = mock_run.call_args_list[-1]
        restore_args = restore_call.args[0]
        assert restore_args[:4] == ["git", "-C", "/fake/path", "reset"]
        assert restore_args[4:6] == ["--hard", "HEAD~1"]

    def test_subprocess_timeout_appended_to_errors(self) -> None:
        component = self._make_component(translation_files=["zh_Hans/intro.adoc"])
        result = {"components_deleted": 0, "errors": []}

        with (
            patch("os.path.isfile", return_value=True),
            patch("os.remove"),
            patch("os.path.isdir", return_value=True),
            patch("os.path.relpath", return_value="zh_Hans/intro.adoc"),
            patch("boost_weblate.endpoint.services.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=60)
            self.svc._delete_component_and_commit_removal(component, result)

        assert _has_error_code(
            result["errors"], BoostEndpointErrorCode.GIT_PUSH_TIMEOUT
        )
        assert result["components_deleted"] == 0
        component.delete.assert_not_called()


# ---------------------------------------------------------------------------
# process_submodule (mocks inner methods)
# ---------------------------------------------------------------------------


class TestProcessSubmodule:
    def setup_method(self) -> None:
        self.svc = _make_svc()

    def test_raises_typeerror_without_temp_dir(self) -> None:
        sig = inspect.signature(self.svc.process_submodule)
        assert sig.parameters["temp_dir"].default is inspect.Parameter.empty
        with pytest.raises(
            TypeError, match="missing .* required .* argument.*temp_dir"
        ):
            self.svc.process_submodule("json")

    def test_clone_failure_returns_error_result(self, tmp_path) -> None:
        with patch.object(self.svc, "clone_repository", return_value=False):
            result = self.svc.process_submodule("json", str(tmp_path))
        assert result["success"] is False
        assert _has_error_code(result["errors"], BoostEndpointErrorCode.CLONE_FAILED)

    def test_no_docs_found_returns_error(self, tmp_path) -> None:
        with (
            patch.object(self.svc, "clone_repository", return_value=True),
            patch.object(self.svc, "scan_documentation_files", return_value=[]),
        ):
            result = self.svc.process_submodule("json", str(tmp_path))
        assert result["success"] is False
        assert _has_error_code(
            result["errors"], BoostEndpointErrorCode.NO_DOCUMENTATION_FILES
        )

    def test_permission_denied_project_add(self, tmp_path) -> None:
        user = MagicMock()
        user.has_perm.return_value = False
        request = MagicMock()
        configs = [{"component_slug": "x"}]

        with (
            patch.object(self.svc, "clone_repository", return_value=True),
            patch.object(self.svc, "scan_documentation_files", return_value=configs),
            patch("boost_weblate.endpoint.services.Project") as MockProject,
        ):
            MockProject.objects.filter.return_value.first.return_value = None
            result = self.svc.process_submodule(
                "json", str(tmp_path), user=user, request=request
            )

        assert result["success"] is False
        assert _has_error_code(
            result["errors"], BoostEndpointErrorCode.PERMISSION_DENIED
        )
        assert any(
            e.get("metadata", {}).get("permission") == "project.add"
            for e in result["errors"]
        )

    def test_permission_denied_project_edit(self, tmp_path) -> None:
        user = MagicMock()
        user.has_perm.side_effect = lambda perm, *args: False
        request = MagicMock()
        configs = [{"component_slug": "x"}]
        existing_project = MagicMock()

        with (
            patch.object(self.svc, "clone_repository", return_value=True),
            patch.object(self.svc, "scan_documentation_files", return_value=configs),
            patch("boost_weblate.endpoint.services.Project") as MockProject,
        ):
            MockProject.objects.filter.return_value.first.return_value = (
                existing_project
            )
            result = self.svc.process_submodule(
                "json", str(tmp_path), user=user, request=request
            )

        assert result["success"] is False
        assert _has_error_code(
            result["errors"], BoostEndpointErrorCode.PERMISSION_DENIED
        )
        assert any(
            e.get("metadata", {}).get("permission") == "project.edit"
            for e in result["errors"]
        )

    def test_get_or_create_project_exception(self, tmp_path) -> None:
        configs = [{"component_slug": "x"}]

        with (
            patch.object(self.svc, "clone_repository", return_value=True),
            patch.object(self.svc, "scan_documentation_files", return_value=configs),
            patch.object(
                self.svc, "get_or_create_project", side_effect=RuntimeError("db")
            ),
            patch("boost_weblate.endpoint.services.Project") as MockProject,
            patch("boost_weblate.endpoint.services.report_error"),
        ):
            MockProject.objects.filter.return_value.first.return_value = None
            result = self.svc.process_submodule("json", str(tmp_path))

        assert result["success"] is False
        assert _has_error_code(
            result["errors"], BoostEndpointErrorCode.PROJECT_CREATE_FAILED
        )

    def test_successful_submodule_creates_component(self, tmp_path) -> None:
        project = MagicMock()
        project.component_set.all.return_value = []
        component = MagicMock()
        configs = [
            {
                "component_slug": "doc-intro-adoc",
                "component_name": "Doc / Intro (adoc)",
                "filemask": "doc/intro_*.adoc",
                "template": "doc/intro.adoc",
                "new_base": "doc/intro.adoc",
                "file_format": "adoc",
            }
        ]

        with (
            patch.object(self.svc, "clone_repository", return_value=True),
            patch.object(self.svc, "scan_documentation_files", return_value=configs),
            patch.object(self.svc, "get_or_create_project", return_value=project),
            patch.object(
                self.svc, "create_or_update_component", return_value=(component, True)
            ),
            patch("boost_weblate.endpoint.services.Project") as MockProject,
        ):
            MockProject.objects.filter.return_value.first.return_value = None
            result = self.svc.process_submodule("json", str(tmp_path))

        assert result["success"] is True
        assert result["components_created"] == 1

    def test_invalid_submodule_name_path_traversal(self, tmp_path) -> None:
        result = self.svc.process_submodule("../evil", str(tmp_path))
        assert result["success"] is False
        assert _has_error_code(
            result["errors"], BoostEndpointErrorCode.INVALID_SUBMODULE
        )


# ---------------------------------------------------------------------------
# process_all
# ---------------------------------------------------------------------------


class TestProcessAll:
    def test_clone_failure_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """process_all runs clone; without network, assert structured failure."""
        svc = BoostComponentService(
            organization="o",
            lang_code="en",
            version="v",
            extensions=None,
        )
        monkeypatch.setattr(svc, "clone_repository", lambda *_a, **_kw: False)
        results = svc.process_all(["json"], user=None)
        assert results["total_submodules"] == 1
        assert results["successful"] == 0
        assert results["failed"] == 1
        assert len(results["submodule_results"]) == 1
        sub = results["submodule_results"][0]
        assert sub["submodule"] == "json"
        assert sub["success"] is False
        assert _has_error_code(sub["errors"], BoostEndpointErrorCode.CLONE_FAILED)

    def test_multiple_submodules_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = _make_svc()
        monkeypatch.setattr(svc, "clone_repository", lambda *_a, **_kw: False)
        results = svc.process_all(["lib1", "lib2", "lib3"], user=None)
        assert results["total_submodules"] == 3
        assert results["failed"] == 3
        assert results["successful"] == 0

    def test_empty_submodules_list(self) -> None:
        svc = _make_svc()
        results = svc.process_all([], user=None)
        assert results["total_submodules"] == 0
        assert results["successful"] == 0
        assert results["failed"] == 0
        assert results["submodule_results"] == []

    def test_temp_dir_cleaned_up(self) -> None:
        svc = _make_svc()
        captured_dir = []

        def recording_process_submodule(*args, **kwargs):
            captured_dir.append(kwargs.get("temp_dir", args[1]))
            return {
                "submodule": args[0],
                "success": True,
                "components_created": 1,
                "components_updated": 0,
                "components_failed": 0,
                "components_deleted": 0,
                "errors": [],
            }

        with patch.object(
            svc, "process_submodule", side_effect=recording_process_submodule
        ):
            svc.process_all(["json"])

        assert len(captured_dir) == 1
        assert not os.path.exists(captured_dir[0]), "temp dir should be cleaned up"

    def test_successful_and_failed_mixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = _make_svc()
        call_count = [0]

        def mock_process_submodule(sub, temp_dir, user=None, request=None):
            call_count[0] += 1
            success = call_count[0] % 2 == 0  # even calls succeed
            return {
                "submodule": sub,
                "success": success,
                "components_created": 1 if success else 0,
                "components_updated": 0,
                "components_failed": 0 if success else 1,
                "components_deleted": 0,
                "errors": []
                if success
                else [
                    {
                        "code": "task_internal_error",
                        "message": "fail",
                        "metadata": {},
                    }
                ],
            }

        monkeypatch.setattr(svc, "process_submodule", mock_process_submodule)
        results = svc.process_all(["lib1", "lib2"], user=None)
        assert results["successful"] == 1
        assert results["failed"] == 1
