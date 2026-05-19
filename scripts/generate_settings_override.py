# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Emit ``src/boost_weblate/settings_override.py`` for Docker ``exec()`` overrides.

Writes a frozen ``WEBLATE_FORMATS = (…,)`` tuple (upstream ``FormatsConf.FORMATS`` plus
QuickBook, merged in this script) and an ``INSTALLED_APPS += (…,)`` line for the
endpoint Django app with operator-facing comments.

Usage::

    uv sync
    uv run python scripts/generate_settings_override.py

Re-run whenever the pinned Weblate version changes so new upstream formats stay listed.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import textwrap
from pathlib import Path

_QUICKBOOK_FORMAT = "boost_weblate.formats.quickbook.QuickBookFormat"
_ENDPOINT_APP_CONFIG = "boost_weblate.endpoint.apps.BoostEndpointConfig"

# Appended after ``WEBLATE_FORMATS`` (comments + ``INSTALLED_APPS +=``).
_INSTALLED_APPS_PLUGIN_FRAGMENT = f"""
# Plugin Django app (``boost_weblate.endpoint``): registers ``/boost-endpoint/`` URLs
# from ``AppConfig.ready()``. The full config class path matches ``WEBLATE_ADD_APPS``
# style installs (e.g. ``WEBLATE_ADD_APPS=boost_weblate.endpoint`` in Docker).
INSTALLED_APPS += ("{_ENDPOINT_APP_CONFIG}",)  # noqa: F821
"""


def _final_weblate_format_paths(stock_paths: list[str]) -> list[str]:
    """Upstream paths plus QuickBook (dedupe); used only while generating."""
    out = list(stock_paths)
    if _QUICKBOOK_FORMAT not in out:
        out.append(_QUICKBOOK_FORMAT)
    return out


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_formatsconf_paths(models_text: str) -> list[str]:
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


def _load_weblate_models_source() -> str:
    spec = importlib.util.find_spec("weblate")
    if spec is None or not spec.submodule_search_locations:
        msg = "Weblate is not installed; run ``uv sync`` in this repository first."
        raise RuntimeError(msg)
    path = Path(spec.submodule_search_locations[0]) / "formats" / "models.py"
    return path.read_text(encoding="utf-8")


def _render_weblate_formats_tuple_lines(paths: list[str]) -> list[str]:
    lines = ["WEBLATE_FORMATS = ("]
    for p in paths:
        lines.append(f'    "{p}",')
    lines.append(")")
    return lines


_SETTINGS_OVERRIDE_TEMPLATE = """\
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
#     COPY …/site-packages/boost_weblate/settings_override.py \\
#         /app/data/settings-override.py
#
# From a plugin source checkout, ``COPY src/boost_weblate/settings_override.py`` with
# the same destination also works.
#
# Generated tail: ``WEBLATE_FORMATS`` tuple, then ``INSTALLED_APPS`` for the
# endpoint app.

{tuple_block}
"""


def _installed_apps_plugin_block() -> str:
    return textwrap.dedent(_INSTALLED_APPS_PLUGIN_FRAGMENT).strip()


def generate(*, dry_run: bool = False) -> str:
    stock = _parse_formatsconf_paths(_load_weblate_models_source())
    full = _final_weblate_format_paths(stock)
    tuple_block = "\n".join(_render_weblate_formats_tuple_lines(full))
    head = _SETTINGS_OVERRIDE_TEMPLATE.format(tuple_block=tuple_block).rstrip()
    content = head + "\n\n" + _installed_apps_plugin_block() + "\n"
    out = _repo_root() / "src" / "boost_weblate" / "settings_override.py"
    if not dry_run:
        out.write_text(content, encoding="utf-8")
    return content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print to stdout only; do not write settings_override.py",
    )
    args = parser.parse_args()
    text = generate(dry_run=args.dry_run)
    if args.dry_run:
        print(text, end="")


if __name__ == "__main__":
    main()
