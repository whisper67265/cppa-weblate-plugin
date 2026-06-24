#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0
#
# Verify plugin assumptions about undocumented Weblate internals
# (FormatsConf.FORMATS AST, WEBLATE_FORMATS, weblate.urls.real_patterns).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LATEST=0

usage() {
  cat <<'EOF'
Usage: check-weblate-internal-contract.sh [--latest]

  (default)  Run contract tests against the already-installed Weblate version.
  --latest   Install the newest modern calver Weblate[all] from PyPI, then run tests.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest)
      LATEST=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

resolve_latest_weblate_pypi() {
  uv run --with packaging python3 - <<'PY'
import json
import re
import sys
import urllib.request
from packaging.version import Version

calver = re.compile(r"^\d{4}\.\d+(?:\.\d+)?$")

def is_modern_calver(name: str) -> bool:
    if not calver.match(name):
        return False
    year = int(name.split(".", 1)[0])
    return year >= 2020

with urllib.request.urlopen("https://pypi.org/pypi/Weblate/json") as resp:
    data = json.load(resp)

releases = [v for v in data["releases"] if is_modern_calver(v)]
if not releases:
    print("ERROR: no modern calver Weblate releases found on PyPI", file=sys.stderr)
    raise SystemExit(1)

releases.sort(key=Version, reverse=True)
print(releases[0])
PY
}

if [[ "$LATEST" -eq 1 ]]; then
  latest_ver="$(resolve_latest_weblate_pypi)"
  echo "Installing latest PyPI Weblate[all]==${latest_ver}"
  uv pip install "Weblate[all]==${latest_ver}"
fi

weblate_version="$(uv run python3 -c 'import importlib.metadata; print(importlib.metadata.version("Weblate"))')"
echo "Weblate version under test: ${weblate_version}"
echo "Contracts checked:"
echo "  - FormatsConf.FORMATS AST (weblate/formats/models.py)"
echo "  - WEBLATE_FORMATS (weblate_formats_with_plugin_formats)"
echo "  - weblate.urls.real_patterns (list accepts URLResolver append)"

set +e
uv run --group dev pytest tests/test_weblate_internal_contract.py -v --tb=short -m weblate_contract
pytest_status=$?
set -e

if [[ "$pytest_status" -ne 0 ]]; then
  echo "Weblate internal API contract check failed." >&2
  echo "Review pytest output above for which contract broke:" >&2
  echo "  [FormatsConf.FORMATS AST] | [WEBLATE_FORMATS] | [weblate.urls.real_patterns]" >&2
  exit "$pytest_status"
fi

echo "Weblate internal API contract check passed (Weblate ${weblate_version})."
