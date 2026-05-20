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
inside ``FormatsConf`` is followed by ``class Meta:`` at the same indent; if upstream
reformats that class, update the pattern here.

``INSTALLED_APPS`` is extended via ``globals().get("INSTALLED_APPS")`` when this file
is ``exec``'d (Docker): the list exists in the settings namespace. Importing this
module for tests still defines ``WEBLATE_FORMATS`` on the module without mutating
Django settings.
"""

from __future__ import annotations

import re
from pathlib import Path

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

_INSTALLED_APPS = globals().get("INSTALLED_APPS")
if _INSTALLED_APPS is not None:
    _INSTALLED_APPS += (_ENDPOINT_APP_CONFIG,)
