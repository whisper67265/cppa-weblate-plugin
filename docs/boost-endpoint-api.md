<!--
SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# Boost Endpoint API

The Boost Endpoint is the HTTP API surface of this plugin. It provides three routes mounted under `/boost-endpoint/` on the Weblate site and exposes one asynchronous operation — `add-or-update` — for bulk creation and maintenance of Weblate projects and components from Boost C++ library submodule repositories.

## Contents

- [Installation and registration](#installation-and-registration)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
  - [GET /boost-endpoint/plugin-ping/](#get-boost-endpointplugin-ping)
  - [GET /boost-endpoint/info/](#get-boost-endpointinfo)
  - [POST /boost-endpoint/add-or-update/](#post-boost-endpointadd-or-update)
- [Request reference](#request-reference)
- [Response reference](#response-reference)
- [Async execution model](#async-execution-model)
- [BoostComponentService internals](#boostcomponentservice-internals)
- [Error handling](#error-handling)
- [Component naming](#component-naming)

---

## Installation and registration

Adding the app to `INSTALLED_APPS` is required but not sufficient for routes to be active. Weblate's `urls.py` builds its route list by hand (`real_patterns`) and does not auto-discover URLconfs from arbitrary apps.

`BoostEndpointConfig.ready()` (`src/boost_weblate/endpoint/apps.py`) delegates to `register_boost_endpoint_urls()` in `src/boost_weblate/endpoint/weblate_urls_adapter.py`, which appends to `weblate.urls.real_patterns` at Django startup after verifying Weblate's URL layout (raises `WeblateUrlLayoutError` on incompatibility).

Registration is idempotent via `functools.lru_cache` on the adapter. The routes inherit Weblate's `URL_PREFIX` handling because `real_patterns` is processed before the prefix wrapper is applied.

For `INSTALLED_APPS` registration, use `settings_override.py` (recommended) or the `WEBLATE_ADD_APPS` Docker environment variable — **not both**. See the main [README](../README.md#weblate_add_apps) for the full comparison.

---

## Authentication

All endpoints except `plugin-ping` require an authenticated Weblate session or token. The API uses Django REST Framework's standard `IsAuthenticated` permission class.

| Endpoint | Authentication |
|----------|---------------|
| `GET /boost-endpoint/plugin-ping/` | None |
| `GET /boost-endpoint/info/` | Required |
| `POST /boost-endpoint/add-or-update/` | Required |

Unauthenticated requests to protected endpoints receive `HTTP 401 Unauthorized`.

The `add-or-update` endpoint also checks object-level permissions inside the Celery worker:

- `project.add` — required to create a new Weblate project.
- `project.edit` — required to modify components in an existing project.
- `translation.add` — required to add a language to a component.
- `translation.add_more` — if absent, the language must be in the project's allowed set rather than any globally available language.

---

## Endpoints

### GET /boost-endpoint/plugin-ping/

Minimal health check. Returns a plain-text `ok` string. No authentication required. Useful for smoke-testing that the URL registration succeeded.

**Request**

```http
GET /boost-endpoint/plugin-ping/
```

**Response**

```http
HTTP/1.1 200 OK
Content-Type: text/plain

ok
```

---

### GET /boost-endpoint/info/

Returns metadata about the installed plugin: package name, version, and the list of supported capability strings.

**Request**

```http
GET /boost-endpoint/info/
Authorization: Token <token>
```

**Response**

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "module": "cppa-weblate-plugin",
  "version": "0.1.0",
  "capabilities": ["info", "add-or-update"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `module` | string | PyPI package name (`cppa-weblate-plugin`) |
| `version` | string | Installed package version from `importlib.metadata`; falls back to `"0.0.0"` if metadata is not found |
| `capabilities` | array of strings | Fixed list of supported endpoint names |

---

### POST /boost-endpoint/add-or-update/

Creates or updates Weblate projects and components for one or more Boost library submodules, for one or more target languages. Heavy work runs in a Celery worker; the view returns `HTTP 202 Accepted` immediately with a `task_id`.

**Request**

```http
POST /boost-endpoint/add-or-update/
Authorization: Token <token>
Content-Type: application/json
```

See [Request reference](#request-reference) for the full body schema.

**Response (202 Accepted)**

```json
{
  "status": "accepted",
  "task_id": "d3b07384-d9a2-4f9b-a0cf-1234567890ab",
  "detail": "Boost add-or-update is running in the background; check Celery logs or task result for completion."
}
```

**Response (400 Bad Request)**

```json
{
  "errors": [
    {
      "code": "required_field",
      "message": "This field is required.",
      "metadata": {"field": "organization", "drf_code": "required"}
    },
    {
      "code": "invalid_submodule_list",
      "message": "Expected a list of items but got type \"str\".",
      "metadata": {
        "field": "add_or_update",
        "language": "zh_Hans",
        "drf_code": "not_a_list"
      }
    }
  ]
}
```

---

## Request reference

`POST /boost-endpoint/add-or-update/` accepts a JSON body validated by `AddOrUpdateRequestSerializer`.

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `organization` | string | Yes | GitHub organization that owns the Boost submodule repositories (e.g. `"boostorg"`) |
| `version` | string | Yes | Boost release tag used as the branch name for cloning and as the translation push branch suffix (e.g. `"boost-1.90.0"`) |
| `add_or_update` | object | Yes | Map of language code → list of submodule names. Each key must be a non-empty string BCP-47 language code. Each value must be a non-empty list of repository/submodule name strings. |
| `extensions` | array of strings | No | File extensions to restrict scanning to (e.g. `[".adoc", ".md"]`). Only extensions that are also supported by Weblate's `FILE_FORMATS` are effective. If omitted, `null`, or empty, all Weblate-supported extensions are used. |

### Validation rules

- `organization`: must be a non-empty string.
- `version`: must be a non-empty string.
- `add_or_update`: must be a non-empty object. Each key must be a non-empty language code string. Each value must be a non-empty list of submodule name strings.
- `extensions`: optional. Blank-stripped entries that reduce to empty strings are removed silently. An all-blank list is treated as no filter (same as omitting the field).

### Example request

```json
{
  "organization": "boostorg",
  "version": "boost-1.90.0",
  "add_or_update": {
    "zh_Hans": ["json", "unordered"],
    "ja": ["json"]
  },
  "extensions": [".adoc", ".md"]
}
```

This processes the `json` and `unordered` submodules for Simplified Chinese, and only `json` for Japanese, restricting scanned files to AsciiDoc and Markdown.

---

## Response reference

### 202 Accepted

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"accepted"` |
| `task_id` | string | Celery task UUID; use to query task state via Weblate's Celery result backend or monitoring tools |
| `detail` | string | Human-readable message describing background execution |

### 400 Bad Request

| Field | Type | Description |
|-------|------|-------------|
| `errors` | array | Unified list of structured error objects (see [Error handling](#error-handling)) |

### 401 Unauthorized

Standard DRF 401 response when no valid authentication credentials are provided.

### Celery task result shape

The Celery task (`boost_add_or_update_task`) returns a dictionary keyed by language code. Each value is the output of `BoostComponentService.process_all()` for that language:

```json
{
  "zh_Hans": {
    "total_submodules": 2,
    "successful": 2,
    "failed": 0,
    "submodule_results": [
      {
        "submodule": "json",
        "success": true,
        "components_created": 4,
        "components_updated": 0,
        "components_failed": 0,
        "components_deleted": 0,
        "errors": []
      },
      {
        "submodule": "unordered",
        "success": false,
        "components_created": 0,
        "components_updated": 0,
        "components_failed": 0,
        "components_deleted": 0,
        "errors": [
          {
            "code": "clone_failed",
            "message": "Failed to clone repository for unordered",
            "metadata": {
              "submodule": "unordered",
              "organization": "boostorg",
              "lang_code": "zh_Hans"
            }
          }
        ]
      }
    ]
  },
  "ja": { ... }
}
```

#### `process_all` result fields

| Field | Type | Description |
|-------|------|-------------|
| `total_submodules` | integer | Number of submodules submitted for this language |
| `successful` | integer | Submodules where at least one component was created or updated |
| `failed` | integer | Submodules where every component failed or the clone failed |
| `submodule_results` | array | Per-submodule result objects (see below) |

#### Per-submodule result fields

| Field | Type | Description |
|-------|------|-------------|
| `submodule` | string | Submodule name |
| `success` | boolean | `true` if at least one component was created or updated |
| `components_created` | integer | New components added to Weblate |
| `components_updated` | integer | Existing components whose push branch was refreshed |
| `components_failed` | integer | Components where `create_or_update_component` returned `None` |
| `components_deleted` | integer | Components removed because they were no longer found in the repo scan |
| `errors` | array of objects | Non-fatal structured errors (`code`, `message`, `metadata`); see [Error handling](#error-handling) |

---

## Async execution model

```text
POST /boost-endpoint/add-or-update/
        │
        ▼
AddOrUpdateView.post()
  Deserialize + validate → AddOrUpdateRequestSerializer
        │ valid
        ▼
boost_add_or_update_task.delay(
    organization, add_or_update, version, extensions, user_id
)
        │                           │
        │ HTTP 202 + task_id        │ (Celery worker picks up)
        ◄─────────────────────      ▼
                            for each lang_code, submodule_list
                            in add_or_update.items():
                                BoostComponentService(...).process_all(
                                    submodule_list, user, request
                                )
                            return dict[lang_code → process_all result]
```

The task uses Weblate's own Celery `app` instance (`weblate.utils.celery.app`) and runs inside the same worker pool as all other Weblate background tasks. No additional broker configuration is needed beyond a working Weblate Celery setup.

`user_id` (an integer primary key) is passed rather than the user object itself because Celery serializes task arguments to JSON. The task re-fetches the user with `User.objects.get(pk=user_id)` inside the worker.

Fatal task failures raise `BoostEndpointError` (a `WeblateError` subclass from `weblate.trans.exceptions`) with a stable `code` and `metadata`, causing Celery to mark the task `FAILURE`. Examples: `task_user_not_found` when the `user_id` no longer exists, `task_timeout` when the task exceeds its Celery soft time limit, or `task_internal_error` for unexpected exceptions (after `report_error()`). Per-submodule errors that are recoverable (e.g. clone failure, permission denial for a single submodule) are collected into the submodule `errors` list as structured objects and do not raise exceptions.

The task declares Celery `soft_time_limit` and `time_limit` from `settings_override.py` (defaults **1800** s / **2100** s, overridable via `BOOST_TASK_SOFT_TIME_LIMIT` and `BOOST_TASK_TIME_LIMIT`). Defaults align with `BOOST_TASK_LOCK_TIMEOUT` so the Redis task lock does not expire while a long-running add-or-update is still active. When the soft limit is exceeded, Celery raises `SoftTimeLimitExceeded`; the task catches it and re-raises `BoostEndpointError` with code `task_timeout` and metadata `soft_time_limit` / `time_limit`.

`trail=False` is set on the task to suppress Celery's default task-result trail and avoid unbounded result-backend growth in long-running deployments.

---

## BoostComponentService internals

`BoostComponentService` (`src/boost_weblate/endpoint/services.py`) performs all the heavy work for a single language. It is instantiated once per language code by the Celery task.

### Constructor parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `organization` | string | GitHub organization name |
| `lang_code` | string | BCP-47 language code for this run |
| `version` | string | Boost release tag (used in branch and push-branch names) |
| `extensions` | `list[str] \| None` | Extension filter; `None` means no filtering |

### `process_all(submodules, user, request)`

Top-level entry point called by the Celery task. Creates a temporary directory, processes each submodule in sequence, cleans up the temp directory in a `finally` block, and returns the aggregated result dictionary.

### Per-submodule pipeline (`process_submodule`)

For each submodule the following steps run in order:

1. **Path validation** — the submodule name is checked against the temp directory root to prevent path traversal. Organization and submodule names must match `^[A-Za-z0-9._-]+$`. Clone URLs are validated before any `git` subprocess: only `https://` (and SCP-style SSH normalized to HTTPS for checks) is allowed; resolved addresses must not be private, loopback, or link-local; the hostname must appear in `ALLOWED_CLONE_HOSTS` (default `github.com`, overridable via `BOOST_ALLOWED_CLONE_HOSTS`).

2. **Clone** — `git clone -b local-{lang_code} --depth 1 https://github.com/{organization}/{submodule}.git` into a temporary subdirectory. A 300-second timeout applies. Clone failure is recorded in `errors` and processing stops for that submodule.

3. **Scan** — `scan_documentation_files()` walks the cloned tree, skipping hidden directories, `__pycache__`, and `node_modules`. Files at the repository root are skipped (only files inside subdirectories are included). Files whose stem ends with `_{lang_code}` (existing translation files) are excluded. Each remaining file with a Weblate-supported extension (filtered by `self.extensions` when set) produces a component config dict.

4. **Permission check** — before touching the database, the user's `project.add` or `project.edit` permission is verified against the existing or prospective project. Failure records an error and stops the submodule.

5. **Project get-or-create** — `Project.objects.get_or_create(slug=...)`. The project slug is `boost-{submodule}-documentation-{lang_code}`. On creation, `project.post_create(user, billing=None)` is called to match the REST API path.

6. **Component get-or-create** (per scanned file) — `Component.objects.get_or_create(project=project, slug=...)`. The first component in a project uses the real SSH remote (`git@github.com:{org}/{submodule}.git`) as its `repo`; subsequent components link to the first via `weblate://{project_slug}/{owner_slug}` to share a single clone. On creation, `component.post_create(user, origin="boost_endpoint")` runs, followed by `_sync_component_for_translation()`.

7. **Sync** — for new repo-owner components, `component.sync_git_repo(skip_push=True)` performs the initial clone. For existing components, a targeted git update (fetch + merge/rebase) runs via `_do_update_git_only()` without a full `do_update`. Both paths finish with `component.create_translations_immediate(force=True)` to ensure translation files are on disk before the language is added.

8. **Language add** — `component.add_new_language(language, request)` following the same permission and availability checks as the Weblate REST API (`translation.add`, `translation.add_more`, `can_add_new_language`).

9. **Stale component deletion** — components in the project whose slugs are not in the set of scanned configs are deleted. Glossary components (`is_glossary=True`) are never deleted. For each deletion: translation files are removed from disk, staged with `git add`, committed, and pushed to `origin HEAD:{push_branch}`.

### Component configuration

| Setting | Value |
|---------|-------|
| `vcs` | `"github"` |
| `branch` | `"local-{lang_code}"` |
| `push_branch` | `"translation-{lang_code}-{version}"` |
| `source_language` | English (`"en"`) |
| `language_regex` | `"^{lang_code}$"` (one language per component) |
| `allow_translation_propagation` | `False` |
| `edit_template` | `False` |
| `manage_units` | `False` |
| `enable_suggestions` | `True` |

---

## Error handling

All Boost endpoint errors share one JSON-serializable shape (`src/boost_weblate/endpoint/errors.py`):

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Stable machine-readable identifier (see table below) |
| `message` | string | Human-readable description |
| `metadata` | object | Context for monitoring, retry logic, and client handling |

### Where errors appear

| Layer | HTTP status / Celery state | Shape |
|-------|---------------------------|-------|
| Request validation | `400 Bad Request` | `{"errors": [<error>, ...]}` |
| Recoverable submodule failure | `202` accepted; task `SUCCESS` with partial failures | `submodule_results[].errors: [<error>, ...]` |
| Fatal task failure | Task `FAILURE` | `BoostEndpointError` exception with `.code` and `.metadata` |

HTTP `400` responses and submodule `errors` lists use the same object schema. Validation errors may include `metadata.field`, `metadata.language`, and `metadata.drf_code` (the original DRF `ErrorDetail.code` when applicable).

### Error codes

| Code | Typical source |
|------|----------------|
| `required_field` | Missing `organization`, `version`, or `add_or_update`; empty `add_or_update` dict |
| `invalid_language_code` | Non-string or blank language key in `add_or_update` |
| `invalid_submodule_list` | Submodule value is not a non-empty list |
| `invalid_submodule` | Submodule name fails path or segment validation |
| `invalid_clone_url` | Organization/submodule or resolved clone URL fails SSRF checks (bad scheme, private IP, or host not in `ALLOWED_CLONE_HOSTS`) |
| `clone_failed` | `git clone` failed or timed out |
| `no_documentation_files` | No supported doc files found after scan |
| `permission_denied` | Missing `project.add` or `project.edit` |
| `project_create_failed` | Project `get_or_create` raised |
| `component_delete_failed` | Stale component deletion failed |
| `file_remove_failed` | Translation file removal from disk failed |
| `git_push_failed` | Git status, commit, or push failed |
| `git_push_timeout` | Git commit/push subprocess timeout |
| `all_components_failed` | Every scanned component failed create/update |
| `task_user_not_found` | Celery task `user_id` not found |
| `task_timeout` | Celery soft time limit exceeded (`BOOST_TASK_SOFT_TIME_LIMIT`) |
| `task_internal_error` | Unexpected exception in the Celery task |

### Recoverable vs fatal

The service uses a non-fatal error collection strategy: individual submodule failures are appended to `errors` and processing continues with the next submodule. The `success` flag is `false` when no component was created or updated for that submodule (including clone failure).

Internal exceptions within `create_or_update_component`, `add_language_to_component`, and `_delete_component_and_commit_removal` are caught, logged via Weblate's `LOGGER`, reported via `report_error()`, and reflected as incremented failure counters or structured entries in `errors`. Unexpected exceptions that escape `process_all` are wrapped as `BoostEndpointError` in the Celery task.

---

## Component naming

Component names and slugs are derived from the relative file path within the cloned repository.

**Name** — directory parts are joined with ` / `, each part title-cased with underscores and hyphens replaced by spaces, and the file extension (without the leading dot) is appended in parentheses:

```text
doc/html/intro.adoc  →  "Doc / Html / Intro (adoc)"
```

**Slug** — directory and file parts are lowercased with underscores replaced by hyphens, joined with `-`, and the extension is appended:

```text
doc/html/intro.adoc  →  "doc-html-intro-adoc"
```

If a name or slug exceeds Weblate's `COMPONENT_NAME_LENGTH` limit (100 characters), it is truncated with a hash suffix to guarantee uniqueness:

- **Name**: keep first `(max_len - 10)` characters, append `[{8-hex}]` derived from SHA-256 of the full name.
- **Slug**: keep first `(max_len - 9)` characters, append `-{8-hex}` derived from SHA-256 of the full slug.
