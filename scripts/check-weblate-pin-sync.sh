#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 William Jin <AuraMindNest@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=weblate-version-map.sh
source "${ROOT}/scripts/weblate-version-map.sh"

PYPI_FILE="${ROOT}/pyproject.toml"
DOCKER_FILE="${ROOT}/docker/Dockerfile.weblate-plugin"

pypi_ver="$(parse_pypi_weblate_version "$PYPI_FILE")"
docker_tag="$(parse_docker_weblate_tag "$DOCKER_FILE")"

if [[ -z "$pypi_ver" ]]; then
  echo "ERROR: could not parse Weblate[…]==… from ${PYPI_FILE}" >&2
  exit 1
fi

if [[ -z "$docker_tag" ]]; then
  echo "ERROR: could not parse FROM weblate/weblate:… from ${DOCKER_FILE}" >&2
  exit 1
fi

expected_docker="$(pypi_to_docker_fixed "$pypi_ver")"

if [[ "$docker_tag" != "$expected_docker" ]]; then
  echo "ERROR: Weblate pin mismatch between PyPI and Docker base image." >&2
  echo "  pyproject.toml (PyPI):     Weblate[postgres]==${pypi_ver}" >&2
  echo "  Dockerfile tag:           weblate/weblate:${docker_tag}" >&2
  echo "  expected Docker fixed tag: weblate/weblate:${expected_docker}" >&2
  exit 1
fi

echo "Weblate pins in sync: PyPI ${pypi_ver} -> Docker ${docker_tag}"
