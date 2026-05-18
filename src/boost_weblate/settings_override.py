# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

# ** GENERATED FILE — do not edit by hand. **
# Regenerate after changing the pinned Weblate version in ``pyproject.toml``:
#
#     uv sync && uv run python scripts/generate_settings_override.py
#
# QuickBook format registration for cppa-weblate-plugin (upstream Weblate from PyPI
# plus pip install). ``WEBLATE_FORMATS`` below is the full list: upstream
# ``FormatsConf.FORMATS`` for the Weblate version used to run the generator, plus
# ``boost_weblate.formats.quickbook.QuickBookFormat`` (see script docstring).
#
# Relationship to Weblate Docker settings (see ``weblate.settings_docker``):
# - After environment variables are applied, Weblate sets ``ADDITIONAL_CONFIG`` to a
#   fixed path (upstream: ``Path("/app/data/settings-override.py")``) and, if that file
#   exists, compiles the file and runs it with ``exec()`` in the *same* namespace as
#   the rest of ``settings_docker``. There is no directory walk or pattern match under
#   ``DATA_DIR`` / ``WEBLATE_DATA_DIR`` for this hook—only that single file path.
# - ``DATA_DIR`` (default ``/app/data`` via ``WEBLATE_DATA_DIR``) is the data volume
#   root; the override file lives beside it as ``…/settings-override.py`` (hyphen),
#   not inside ``…/python/customize/`` unless your own image wires an extra import.
#
# ``/app/data/python/customize`` (``WEBLATE_PY_PATH`` in the official container):
# - The ``customize`` Django app (first in ``INSTALLED_APPS``) is for importable
#   customization code, static files, and templates on ``sys.path``—parallel to the
#   exec hook above, not a substitute for it. Stock Weblate does not auto-import
#   ``customize.settings_override``; use the path below unless your Dockerfile extends
#   ``weblate.settings_docker`` to load another module explicitly.
#
# CD / image build — copy this file to the path Weblate execs (official Docker). The
# wheel exposes it as ``boost_weblate/settings_override.py`` (underscore: valid Python
# module path); Weblate still loads only ``…/settings-override.py`` (hyphen) on disk:
#
#     COPY …/site-packages/boost_weblate/settings_override.py \
#         /app/data/settings-override.py
#
# From a plugin source checkout, ``COPY src/boost_weblate/settings_override.py`` with
# the same destination also works.
#
# Generated tail: ``WEBLATE_FORMATS`` tuple, then ``INSTALLED_APPS`` for the
# endpoint app.

WEBLATE_FORMATS = (
    "weblate.formats.ttkit.PoFormat",
    "weblate.formats.ttkit.PoMonoFormat",
    "weblate.formats.ttkit.TSFormat",
    "weblate.formats.ttkit.XliffFormat",
    "weblate.formats.ttkit.RichXliffFormat",
    "weblate.formats.ttkit.Xliff2Format",
    "weblate.formats.ttkit.RichXliff2Format",
    "weblate.formats.ttkit.PoXliffFormat",
    "weblate.formats.ttkit.AppleXliffFormat",
    "weblate.formats.ttkit.StringsFormat",
    "weblate.formats.ttkit.PropertiesFormat",
    "weblate.formats.ttkit.JoomlaFormat",
    "weblate.formats.ttkit.GWTFormat",
    "weblate.formats.ttkit.PhpFormat",
    "weblate.formats.ttkit.LaravelPhpFormat",
    "weblate.formats.ttkit.RESXFormat",
    "weblate.formats.ttkit.AndroidFormat",
    "weblate.formats.ttkit.MOKOFormat",
    "weblate.formats.ttkit.CMPFormat",
    "weblate.formats.ttkit.JSONFormat",
    "weblate.formats.ttkit.JSONNestedFormat",
    "weblate.formats.ttkit.WebExtensionJSONFormat",
    "weblate.formats.ttkit.I18NextFormat",
    "weblate.formats.ttkit.CatkeysFormat",
    "weblate.formats.ttkit.I18NextV4Format",
    "weblate.formats.ttkit.GoI18JSONFormat",
    "weblate.formats.ttkit.GoI18V2JSONFormat",
    "weblate.formats.ttkit.GoTextFormat",
    "weblate.formats.ttkit.ARBFormat",
    "weblate.formats.ttkit.FormatJSFormat",
    "weblate.formats.ttkit.CSVFormat",
    "weblate.formats.ttkit.CSVSimpleFormat",
    "weblate.formats.ttkit.YAMLFormat",
    "weblate.formats.ttkit.RubyYAMLFormat",
    "weblate.formats.ttkit.SubRipFormat",
    "weblate.formats.ttkit.MicroDVDFormat",
    "weblate.formats.ttkit.AdvSubStationAlphaFormat",
    "weblate.formats.ttkit.SubStationAlphaFormat",
    "weblate.formats.ttkit.DTDFormat",
    "weblate.formats.ttkit.FlatXMLFormat",
    "weblate.formats.ttkit.ResourceDictionaryFormat",
    "weblate.formats.ttkit.INIFormat",
    "weblate.formats.ttkit.InnoSetupINIFormat",
    "weblate.formats.ttkit.PropertiesMi18nFormat",
    "weblate.formats.external.XlsxFormat",
    "weblate.formats.txt.AppStoreFormat",
    "weblate.formats.convert.HTMLFormat",
    "weblate.formats.convert.IDMLFormat",
    "weblate.formats.convert.OpenDocumentFormat",
    "weblate.formats.convert.PlainTextFormat",
    "weblate.formats.convert.DokuWikiFormat",
    "weblate.formats.convert.MarkdownFormat",
    "weblate.formats.convert.MediaWikiFormat",
    "weblate.formats.convert.WindowsRCFormat",
    "weblate.formats.convert.AsciiDocFormat",
    "weblate.formats.convert.WXLFormat",
    "weblate.formats.ttkit.XWikiPropertiesFormat",
    "weblate.formats.ttkit.XWikiPagePropertiesFormat",
    "weblate.formats.ttkit.XWikiFullPageFormat",
    "weblate.formats.ttkit.TBXFormat",
    "weblate.formats.ttkit.StringsdictFormat",
    "weblate.formats.ttkit.FluentFormat",
    "weblate.formats.ttkit.GoI18nTOMLFormat",
    "weblate.formats.ttkit.TOMLFormat",
    "weblate.formats.ttkit.RESJSONFormat",
    "weblate.formats.ttkit.NextcloudJSONFormat",
    "weblate.formats.multi.MultiCSVFormat",
    "boost_weblate.formats.quickbook.QuickBookFormat",
)

# Plugin Django app (``boost_weblate.endpoint``): registers ``/boost-endpoint/`` URLs
# from ``AppConfig.ready()``. The full config class path matches ``WEBLATE_ADD_APPS``
# style installs (e.g. ``WEBLATE_ADD_APPS=boost_weblate.endpoint`` in Docker).
INSTALLED_APPS += ("boost_weblate.endpoint.apps.BoostEndpointConfig",)  # noqa: F821
