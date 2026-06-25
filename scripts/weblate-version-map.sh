# SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0
#
# Map PyPI Weblate calver releases to fixed Docker Hub tags (YEAR.MONTH.PATCH.BUILD).
# See https://docs.weblate.org/en/latest/contributing/release.html

# shellcheck shell=bash

pypi_to_docker_fixed() {
  local v="$1"
  local year month patch
  IFS=. read -r year month patch <<< "$v"
  patch="${patch:-0}"
  echo "${year}.${month}.${patch}.0"
}

parse_pypi_weblate_version() {
  local file="${1:-pyproject.toml}"
  grep -E '^[[:space:]]*"Weblate(\[[^]]+\])?==[0-9][0-9.]+"' "$file" \
    | head -n1 \
    | sed -E 's/.*Weblate(\[[^]]+\])?==([0-9][0-9.]+).*/\2/'
}

parse_docker_weblate_tag() {
  local file="${1:-docker/Dockerfile.weblate-plugin}"
  grep -E '^FROM weblate/weblate:[0-9][0-9.]+' "$file" \
    | head -n1 \
    | sed -E 's/^FROM weblate\/weblate:([0-9][0-9.]+).*/\1/'
}

docker_weblate_tag_exists() {
  local tag="$1"
  local code
  code="$(curl -sS --connect-timeout 10 --max-time 30 -o /dev/null -w '%{http_code}' \
    "https://hub.docker.com/v2/repositories/weblate/weblate/tags/${tag}/")"
  [[ "$code" == "200" ]]
}

# Modern calver Weblate releases from PyPI (newest first, one per line).
list_modern_weblate_pypi_releases() {
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

with urllib.request.urlopen(
    "https://pypi.org/pypi/Weblate/json", timeout=30
) as resp:
    data = json.load(resp)

releases = [v for v in data["releases"] if is_modern_calver(v)]
if not releases:
    print("ERROR: no modern calver Weblate releases found on PyPI", file=sys.stderr)
    raise SystemExit(1)

for version in sorted(releases, key=Version, reverse=True):
    print(version)
PY
}

latest_modern_weblate_pypi_release() {
  list_modern_weblate_pypi_releases | head -n1
}
