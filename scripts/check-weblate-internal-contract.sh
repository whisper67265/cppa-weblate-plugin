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
# shellcheck source=weblate-version-map.sh
source "${ROOT}/scripts/weblate-version-map.sh"

LATEST=0

usage() {
  cat <<'EOF'
Usage: check-weblate-internal-contract.sh [--latest]

  (default)  Run contract tests against the already-installed Weblate version.
  --latest   Install the newest modern calver Weblate from PyPI, then run tests.
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

if [[ "$LATEST" -eq 1 ]]; then
  latest_ver="$(latest_modern_weblate_pypi_release)"
  echo "Installing latest PyPI Weblate[postgres]==${latest_ver}"
  uv pip install "Weblate[postgres]==${latest_ver}"
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
