# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

# QuickBook format registration for cppa-weblate-plugin (upstream Weblate from PyPI
# plus pip install).
#
# Relationship to Weblate Docker settings (see ``weblate.settings_docker``):
# - After environment variables are applied, Weblate sets ``ADDITIONAL_CONFIG`` to a
#   fixed path (upstream: ``Path("/app/data/settings-override.py")``) and, if that file
#   exists, compiles the file and runs it with ``exec()`` in the *same* namespace as
#   the rest
#   of ``settings_docker``. There is no directory walk or pattern match under
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
#     COPY …/site-packages/boost_weblate/settings_override.py
#         /app/data/settings-override.py
#
# From a plugin source checkout, ``COPY src/boost_weblate/settings_override.py`` with
# the same destination also works.

WEBLATE_FORMATS += (  # noqa: F821  # defined by Weblate before exec()
    "boost_weblate.formats.quickbook.QuickBookFormat",
)

# Plugin Django app (``boost_weblate.endpoint``): registers ``/boost-endpoint/`` URLs
# from ``AppConfig.ready()``. The full config class path matches ``WEBLATE_ADD_APPS``
# style installs (e.g. ``WEBLATE_ADD_APPS=boost_weblate.endpoint`` in Docker).
INSTALLED_APPS += ("boost_weblate.endpoint.apps.BoostEndpointConfig",)  # noqa: F821
