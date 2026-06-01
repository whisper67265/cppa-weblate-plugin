# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Docker ``settings-override.py`` fragment for QuickBook and the Boost endpoint app.

Weblate's official image runs this file with ``exec()`` in the same namespace as
``weblate.settings_docker`` (see upstream ``ADDITIONAL_CONFIG``). Copy this module to
``/app/data/settings-override.py`` (hyphen on disk) or keep it on ``PYTHONPATH`` and
point your image at the same content.

``WEBLATE_FORMATS`` is built by **reading** ``weblate/formats/models.py`` as text and
regex-slicing ``FormatsConf.FORMATS``. That avoids ``import weblate.formats.models``,
which pulls in Django ORM classes during settings import and raises
``AppRegistryNotReady``. The slice is **layout-sensitive**: it assumes ``FORMATS = (``
inside ``FormatsConf`` (same file) is followed by ``class Meta:`` at the same indent;
if upstream reformats ``FormatsConf`` or moves ``FORMATS`` / ``Meta``, update
``_FORMATS_BLOCK`` below.

When this file is ``exec``'d into Weblate's settings namespace (Docker),
``INSTALLED_APPS`` is taken from ``globals()`` and extended. Upstream
``weblate.settings_docker`` uses a **list**; the override appends in place with
``+=``. Settings that use an **immutable tuple** instead get a new tuple assigned
back to ``globals()["INSTALLED_APPS"]``. Importing this module without
``INSTALLED_APPS`` in the namespace (typical unit tests) still defines
``WEBLATE_FORMATS`` and skips the apps mutation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Package ``__init__`` is empty; does not import ``formats.models``.
import weblate.formats

_QUICKBOOK_FORMAT = "boost_weblate.formats.quickbook.QuickBookFormat"
_ENDPOINT_APP_CONFIG = "boost_weblate.endpoint.apps.BoostEndpointConfig"

_FORMATS_BLOCK = re.compile(
    r"^\s{4}FORMATS\s*=\s*\(([\s\S]*?)\)\s*\n\s{4}class Meta:",
    re.MULTILINE,
)
_STRING_LITERAL = re.compile(r'"([^"\\]*)"(?:\s*,|\s*$)', re.MULTILINE)


def weblate_formats_with_quickbook() -> tuple[str, ...]:
    """Upstream ``FormatsConf.FORMATS`` paths plus QuickBook.

    Avoids importing ``weblate.formats.models``.
    """
    models_py = Path(weblate.formats.__file__).resolve().parent / "models.py"
    src = models_py.read_text(encoding="utf-8")
    m = _FORMATS_BLOCK.search(src)
    if not m:
        msg = f"boost_weblate: could not parse FormatsConf.FORMATS from {models_py}"
        raise RuntimeError(msg)
    body = m.group(1)
    core = tuple(
        p for p in _STRING_LITERAL.findall(body) if p.startswith("weblate.formats.")
    )
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
