#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0
#
# Resolve the next Weblate pin (PyPI calver + mapped Docker fixed tag) and optionally
# update pyproject.toml, docker/Dockerfile.weblate-plugin, and uv.lock.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=weblate-version-map.sh
source "${ROOT}/scripts/weblate-version-map.sh"

PYPI_FILE="${ROOT}/pyproject.toml"
DOCKER_FILE="${ROOT}/docker/Dockerfile.weblate-plugin"

DRY_RUN=1
FORCE_VERSION=""

usage() {
  cat <<'EOF'
Usage: bump-weblate-version.sh [--dry-run | --apply] [--version PYPI_VERSION]

  --dry-run   Print the resolved bump without changing files (default)
  --apply     Update pyproject.toml, Dockerfile, and uv.lock
  --version   Pin a specific PyPI calver (must have a mapped Docker fixed tag)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --apply)
      DRY_RUN=0
      shift
      ;;
    --version)
      FORCE_VERSION="$2"
      shift 2
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

current="$(parse_pypi_weblate_version "$PYPI_FILE")"
if [[ -z "$current" ]]; then
  echo "ERROR: could not parse current Weblate pin from ${PYPI_FILE}" >&2
  exit 1
fi

list_weblate_pypi_candidates() {
  uv run --with packaging python3 - "$current" "$FORCE_VERSION" <<'PY'
import json
import re
import sys
import urllib.request
from packaging.version import Version

current = Version(sys.argv[1])
force = sys.argv[2]

calver = re.compile(r"^\d{4}\.\d+(?:\.\d+)?$")

def is_modern_calver(name: str) -> bool:
    if not calver.match(name):
        return False
    year = int(name.split(".", 1)[0])
    return year >= 2020

with urllib.request.urlopen("https://pypi.org/pypi/Weblate/json") as resp:
    data = json.load(resp)

releases = [v for v in data["releases"] if is_modern_calver(v)]
releases.sort(key=Version, reverse=True)

if force:
    if force not in releases:
        print(f"ERROR: PyPI release {force!r} not found", file=sys.stderr)
        sys.exit(1)
    print(force)
    sys.exit(0)

candidates = [v for v in releases if Version(v) > current]
if not candidates:
    sys.exit(3)

for candidate in candidates:
    print(candidate)
PY
}

resolve_target() {
  local candidate docker_tag list_output list_status=0

  list_output="$(list_weblate_pypi_candidates)" || list_status=$?

  if [[ $list_status -eq 1 ]]; then
    return 1
  fi
  if [[ $list_status -ne 0 ]] || [[ -z "$list_output" ]]; then
    return 3
  fi

  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    docker_tag="$(pypi_to_docker_fixed "$candidate")"
    if docker_weblate_tag_exists "$docker_tag"; then
      echo "$candidate"
      return 0
    fi
  done <<<"$list_output"

  return 3
}

set +e
target_pypi="$(resolve_target)"
resolve_status=$?
set -e

if [[ $resolve_status -eq 3 ]]; then
  echo "No newer Weblate release with PyPI + Docker fixed tag (current: ${current})."
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      echo "changed=false"
      echo "target_pypi="
      echo "target_docker="
    } >>"$GITHUB_OUTPUT"
  fi
  exit 0
fi

if [[ $resolve_status -ne 0 ]]; then
  exit 1
fi

target_docker="$(pypi_to_docker_fixed "$target_pypi")"

if [[ "$target_pypi" == "$current" ]]; then
  echo "Already pinned to PyPI ${current} (Docker ${target_docker})."
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      echo "changed=false"
      echo "target_pypi=${target_pypi}"
      echo "target_docker=${target_docker}"
    } >>"$GITHUB_OUTPUT"
  fi
  exit 0
fi

echo "Weblate bump: PyPI ${current} -> ${target_pypi}, Docker -> ${target_docker}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "changed=true"
    echo "target_pypi=${target_pypi}"
    echo "target_docker=${target_docker}"
  } >>"$GITHUB_OUTPUT"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "(dry-run; no files changed)"
  exit 0
fi

sed -i "s/Weblate\\[all\\]==[0-9][0-9.]*/Weblate[all]==${target_pypi}/" "$PYPI_FILE"
sed -i "s|^FROM weblate/weblate:[0-9][0-9.]*|FROM weblate/weblate:${target_docker}|" "$DOCKER_FILE"

(
  cd "$ROOT"
  uv lock
)

echo "Updated ${PYPI_FILE}, ${DOCKER_FILE}, and uv.lock"
