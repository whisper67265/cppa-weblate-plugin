<!--
SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-06-11

### Added

- **QuickBook format** — `QuickBookFormat` convert pipeline for `.qbk` templates; parsing and reconstruction in `boost_weblate.utils.quickbook`; registration via `WEBLATE_FORMATS` in `settings_override.py`.
- **Boost endpoint HTTP API** — routes under `/boost-endpoint/`:
  - `GET /boost-endpoint/plugin-ping/` (public health check)
  - `GET /boost-endpoint/info/` (authenticated plugin metadata)
  - `POST /boost-endpoint/add-or-update/` (authenticated; Celery-backed project/component management)
- **Celery integration** — `boost_add_or_update_task` on Weblate's Celery app; `BoostComponentService` for GitHub submodule clone, scan, and Weblate ORM create/update.
- **Rate limiting** — scoped DRF throttles for protected endpoints (`info`: 60/minute; `add-or-update`: 10/hour); `BOOST_ENDPOINT_THROTTLE_INFO` and `BOOST_ENDPOINT_THROTTLE_ADD_OR_UPDATE` env overrides; HTTP 429 with `Retry-After`.
- **CI pipeline** — umbrella `ci.yml` with lint, test (90% coverage gate), package, dependency audit, Weblate pin sync, and Docker-based plugin smoke/auth/functional jobs.
- **CD pipeline** — staging auto-deploy on `develop` (`cd.yml`); production via `promote-main.yml` (ff-only `develop` → `main`) followed by `main` CD.
- **Weblate version pinning** — `Weblate[all]==…` in `pyproject.toml` synced with Docker `FROM weblate/weblate:…`; enforced by `ci-weblate-pin.yml`; scheduled bumps via `weblate-pin-bump.yml`.
- **Release workflow** — manual `release.yml` tags `main` from `pyproject.toml` version and creates GitHub Releases.

## Deprecation Policy

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The plugin version in `pyproject.toml` uses `MAJOR.MINOR.PATCH`:

- **MAJOR** — incompatible API or integration changes
- **MINOR** — backward-compatible functionality
- **PATCH** — backward-compatible bug fixes

### Notice period

Breaking removals or behavior changes require at least **one minor release** of deprecation. For example, a feature deprecated in `1.1.0` may be removed in `2.0.0`, not in `1.2.0`.

### How changes are communicated

1. **Changelog** — each deprecation is recorded under `### Deprecated` in the release where it is announced; removal appears under `### Removed` in the major release that drops it.
2. **Runtime warnings** — deprecated Python APIs emit `warnings.warn(..., DeprecationWarning)` where applicable so integrators can detect usage in tests or logs.

### Public integration surface

The following are subject to this policy:

- **HTTP API** — request/response schema and auth requirements for `POST /boost-endpoint/add-or-update/`, `GET /boost-endpoint/info/`, and related Boost endpoint routes documented in `docs/boost-endpoint-api.md`.
- **Format registration** — dotted import paths registered in `WEBLATE_FORMATS` (e.g. `boost_weblate.formats.quickbook.QuickBookFormat`).
- **Settings hook** — documented environment variables read by `settings_override.py` (e.g. `BOOST_ENDPOINT_THROTTLE_INFO`, `BOOST_ENDPOINT_THROTTLE_ADD_OR_UPDATE`).

### Non-guarantees

Internal modules under `boost_weblate.utils.*` and undocumented environment variables may change in minor releases unless explicitly listed above.
