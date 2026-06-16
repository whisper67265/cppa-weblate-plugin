# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Docker ``settings-override.py`` fragment for QuickBook and the Boost endpoint app.

Weblate's official image runs this file with ``exec()`` in the same namespace as
``weblate.settings_docker`` (see upstream ``ADDITIONAL_CONFIG``). Copy this module to
``/app/data/settings-override.py`` (hyphen on disk) or keep it on ``PYTHONPATH`` and
point your image at the same content.

``WEBLATE_FORMATS`` is built by **reading** ``weblate/formats/models.py`` and
AST-parsing ``FormatsConf.FORMATS``. That avoids ``import weblate.formats.models``,
which pulls in Django ORM classes during settings import and raises
``AppRegistryNotReady``. If upstream restructures ``FormatsConf`` (e.g. renames the
class or moves ``FORMATS`` off a simple tuple assignment), update the AST helpers
below.

When this file is ``exec``'d into Weblate's settings namespace (Docker),
``INSTALLED_APPS`` is taken from ``globals()`` and extended. Upstream
``weblate.settings_docker`` uses a **list**; the override appends in place with
``+=``. Settings that use an **immutable tuple** instead get a new tuple assigned
back to ``globals()["INSTALLED_APPS"]``. Importing this module without
``INSTALLED_APPS`` in the namespace (typical unit tests) still defines
``WEBLATE_FORMATS`` and skips the apps mutation.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

# Package ``__init__`` is empty; does not import ``formats.models``.
import weblate.formats

_QUICKBOOK_FORMAT = "boost_weblate.formats.quickbook.QuickBookFormat"
_ENDPOINT_APP_CONFIG = "boost_weblate.endpoint.apps.BoostEndpointConfig"


def _parse_formatsconf_formats_ast(models_text: str) -> list[str]:
    tree = ast.parse(models_text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FormatsConf":
            return _formats_assignment_to_strings(node.body)
    msg = "Class FormatsConf not found in weblate formats models source"
    raise RuntimeError(msg)


def _formats_assignment_to_strings(class_body: list[ast.stmt]) -> list[str]:
    for node in class_body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "FORMATS":
                return _string_tuple_or_list(node.value)
    msg = "FORMATS assignment not found on FormatsConf"
    raise RuntimeError(msg)


def _string_tuple_or_list(node: ast.expr) -> list[str]:
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            else:
                msg = f"Unexpected literal in FormatsConf.FORMATS: {ast.dump(elt)}"
                raise RuntimeError(msg)
        return out
    msg = f"Unexpected FormatsConf.FORMATS value: {ast.dump(node)}"
    raise RuntimeError(msg)


def weblate_formats_with_quickbook() -> tuple[str, ...]:
    """Upstream ``FormatsConf.FORMATS`` paths plus QuickBook.

    Avoids importing ``weblate.formats.models``.
    """
    models_py = Path(weblate.formats.__file__).resolve().parent / "models.py"
    src = models_py.read_text(encoding="utf-8")
    try:
        core = tuple(_parse_formatsconf_formats_ast(src))
    except RuntimeError:
        raise
    except (SyntaxError, ValueError) as exc:
        msg = f"boost_weblate: could not parse FormatsConf.FORMATS from {models_py}"
        raise RuntimeError(msg) from exc
    if not core:
        msg = f"boost_weblate: no format paths parsed from {models_py}"
        raise RuntimeError(msg)
    if _QUICKBOOK_FORMAT in core:
        return core
    return core + (_QUICKBOOK_FORMAT,)


WEBLATE_FORMATS = weblate_formats_with_quickbook()

_DEFAULT_BOOST_ENDPOINT_THROTTLE_RATES = {
    "info": "60/minute",
    "add-or-update": "10/hour",
}


def boost_endpoint_throttle_rates() -> dict[str, str]:
    """Scoped throttle rates for Boost endpoint views (env overrides optional)."""
    return {
        "info": os.environ.get(
            "BOOST_ENDPOINT_THROTTLE_INFO",
            _DEFAULT_BOOST_ENDPOINT_THROTTLE_RATES["info"],
        ),
        "add-or-update": os.environ.get(
            "BOOST_ENDPOINT_THROTTLE_ADD_OR_UPDATE",
            _DEFAULT_BOOST_ENDPOINT_THROTTLE_RATES["add-or-update"],
        ),
    }


BOOST_ENDPOINT_THROTTLE_RATES = boost_endpoint_throttle_rates()

_DEFAULT_ALLOWED_CLONE_HOSTS = ("github.com",)


def allowed_clone_hosts() -> list[str]:
    """Hostnames permitted for git clone URLs (env override optional)."""
    raw = os.environ.get("BOOST_ALLOWED_CLONE_HOSTS")
    if raw is None:
        return list(_DEFAULT_ALLOWED_CLONE_HOSTS)
    if raw.strip() == "":
        return []
    return [host.strip().lower() for host in raw.split(",") if host.strip()]


ALLOWED_CLONE_HOSTS = allowed_clone_hosts()


def merge_boost_endpoint_throttle_rates(
    rest_framework: dict[str, Any],
) -> dict[str, Any]:
    """Merge Boost endpoint scoped rates into ``REST_FRAMEWORK``."""
    merged = dict(rest_framework)
    existing = dict(merged.get("DEFAULT_THROTTLE_RATES", {}))
    existing.update(BOOST_ENDPOINT_THROTTLE_RATES)
    merged["DEFAULT_THROTTLE_RATES"] = existing
    return merged


_REST_FRAMEWORK = globals().get("REST_FRAMEWORK")
if _REST_FRAMEWORK is not None:
    globals()["REST_FRAMEWORK"] = merge_boost_endpoint_throttle_rates(_REST_FRAMEWORK)

_INSTALLED_APPS = globals().get("INSTALLED_APPS")
if _INSTALLED_APPS is not None:
    # Tuple += creates a new object; assign back so exec namespace / settings see it.
    # List += mutates in place, matching Weblate/Docker settings namespaces.
    if isinstance(_INSTALLED_APPS, tuple):
        globals()["INSTALLED_APPS"] = _INSTALLED_APPS + (_ENDPOINT_APP_CONFIG,)
    else:
        _INSTALLED_APPS += (_ENDPOINT_APP_CONFIG,)
