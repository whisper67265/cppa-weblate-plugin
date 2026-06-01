<!--
SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# Boost Weblate Plugin Refactor — Plan

**Goal:** Replace the Weblate fork with a standalone plugin package `cppa-weblate-plugin`
installed on top of **upstream Weblate from PyPI**. Once complete, the fork repo is retired
and upstream Weblate + this plugin is installed. The package repository must meet
Alliance minimum engineering standards.

---

## Feasibility Assessment

> **Verdict: GO**

Every required capability maps to an officially documented Weblate extension point from [Customizing Weblate](https://docs.weblate.org/en/latest/admin/customize.html). No fork, no monkey-patching, no modification to upstream source is needed.

- **Custom file format (`quickbook.py`)** — subclasses `weblate.formats.base.BaseFormat` and registers via `WEBLATE_FORMATS`. This is the explicit documented mechanism; see [Appendix C](#appendix-c-prototype--minimal-plugin) for a working skeleton.
- **Custom Django app (`boost_endpoint`)** — added to `INSTALLED_APPS` via `WEBLATE_ADD_APPS`. Standard Django URL routing serves the endpoints; no internal patching needed.
- **Package installation** — `pip install git+https://…@<tag>` alongside upstream Weblate from PyPI, exactly as the docs endorse for third-party packages.
- **Settings injection** — a single override file at `/app/data/python/customize/settings.py`, copied into the image with one `COPY` line; no `weblate-docker` source changes required.

The only structural risk is internal API churn: Weblate's docs warn that internal interfaces may change without notice. Both the format subclass and the Django app touch only the public `BaseFormat` ABC and standard Django APIs, so exposure is minimal. Version pinning keeps this within normal team discipline — see [Appendix B: Risk Register](#appendix-b-risk-register). Four alternatives were evaluated and rejected — see [Appendix A: Alternatives Considered](#appendix-a-alternatives-considered).

---

## Package Structure

```text
cppa-weblate-plugin/
├── LICENSE                          ← GPL-3.0-or-later (aligned with upstream Weblate)
├── README.md                        ← package overview, quickstart, architecture section, config reference
├── settings-override.py             ← CD copies into image build context
├── docs/
│   ├── deployment-runbook.md        ← install, rollback, health checks
│   └── boost-endpoint-api.md        ← OpenAPI / REST reference for /boost-endpoint/
├── pyproject.toml                   ← declares ALL runtime deps
├── .github/
│   └── workflows/
│       ├── ci.yml                   ← pytest, ruff, coverage gate
│       └── integration.yml          ← Weblate + package smoke tests
├── tests/
│   ├── formats/
│   │   └── test_quickbook.py        ← QuickBook parser unit tests
│   └── endpoint/
│       ├── test_views.py            ← boost_endpoint request/response tests
│       └── test_services.py         ← BoostComponentService unit tests
└── src/boost_weblate/
    ├── __init__.py
    ├── formats/
    │   ├── __init__.py
    │   └── quickbook.py             ← subclass of weblate.formats.base.BaseFormat; registered via WEBLATE_FORMATS += in settings-override.py
    ├── utils/
    │   ├── __init__.py
    │   └── quickbook.py             ← QuickBook utilities
    └── endpoint/                    ← boost_endpoint Django app; loaded via INSTALLED_APPS / WEBLATE_ADD_APPS
        ├── __init__.py
        ├── apps.py                  ← AppConfig (name = "boost_weblate.endpoint")
        ├── urls.py
        ├── views.py
        ├── serializers.py
        └── services.py
```

## Quality Baseline

| Requirement | Standard |
|-------------|----------|
| Test coverage | ≥ 90 % (enforced by `--cov-fail-under=90`) |
| CI | GitHub Actions: `pytest`, `ruff check`, coverage gate on every PR |
| Plugin test | CI job: `uv pip install weblate "git+https://…/cppa-weblate-plugin@HEAD"` in a Docker-compose stack → smoke-test endpoint + format registration |
| CD | CD workflow clones **upstream** `weblate-docker`, edits its `Dockerfile` (install upstream Weblate from PyPI + plugin from `git+https://…/cppa-weblate-plugin@<tag>`, `COPY` `settings-override.py` into the image). `settings-override.py` is versioned in **this** repo. `WEBLATE_ADD_APPS` adds `boost_weblate.endpoint` to `INSTALLED_APPS`; `WEBLATE_FORMATS +=` registers the QuickBook format class. |
| LICENSE | GPL-3.0-or-later in repo root (same license family as Weblate) |
| Runtime deps | All deps declared in `pyproject.toml`; no implicit system deps without docs |
| Documentation | README (quickstart + architecture section), deployment runbook, REST API reference |
| Reproducible install | `uv pip install "git+https://…/cppa-weblate-plugin@<tag>"` works against upstream Weblate PyPI package |

---

## Week 1

**Weekly outcome:** A cloneable package with QuickBook fully done: implementation, tests, and **≥ 90 %** coverage on `formats/quickbook.py` and `utils/quickbook.py`; placeholder CI workflows only; URL registration approach for `boost_endpoint` resolved and documented.

## Repo skeleton & README

- Create `cppa-weblate-plugin` with `pyproject.toml` (build backend: `uv_build`), `LICENSE`, `.github/` stub.
- Add **placeholder** workflows `ci.yml` and `integration.yml` (empty or minimal) so PRs have CI targets from day one.
- Write `README.md`: overview, quickstart, architecture (Weblate → QuickBook → boost-endpoint → boost-docs-translation), config reference **for QuickBook / `WEBLATE_FORMATS` and `settings-override.py` copy semantics** (upstream `weblate-docker` + `Dockerfile` `COPY` at deploy tag). Defer boost-endpoint env vars and `WEBLATE_ADD_APPS` to Week 2 when that app ships.
- Declare all runtime dependencies in `pyproject.toml` (Weblate pin, any others).
- Add root `settings-override.py` with **`WEBLATE_FORMATS +=`** only this week. Document the CD clone-and-patch flow for this file; endpoint-related settings land in Week 2.

## QuickBook — complete in this week

- Implement `formats/quickbook.py` as a subclass of `weblate.formats.base.BaseFormat` and `utils/quickbook.py` (fresh code; fork is reference only).
- Register the format class in `settings-override.py` via `WEBLATE_FORMATS += ("boost_weblate.formats.quickbook.QuickBookFormat",)`.
- Add unit tests (round-trip, edge cases) until **`formats/quickbook.py` and `utils/quickbook.py` meet ≥ 90 % coverage** (same gate as Quality Baseline).

The minimal format handler skeleton and settings registration snippet are in [Appendix C: Prototype — Minimal Plugin](#appendix-c-prototype--minimal-plugin).

## URL registration approach — resolve in this week

Weblate's `urls.py` does **not** auto-discover URL patterns from `INSTALLED_APPS`; it hardcodes `include()` calls gated by `if "app" in settings.INSTALLED_APPS` for known apps only. The plugin must register its own URLs via one of:

- `AppConfig.ready()` — programmatically append to `urlpatterns` at startup (simplest for a self-contained plugin), **or**
- `ROOT_URLCONF` override in `settings-override.py` — point to a custom URL conf that imports Weblate's patterns and adds the plugin's `include()`.

**Action:** prototype both approaches in the plugin test environment and pick the one that survives Weblate upgrades best. Document the chosen approach in `README.md` so Week 2 implementation can proceed without ambiguity.

---

## Week 2

**Weekly outcome:** `boost_endpoint` fully implemented and tested; PR **`ci.yml`** enforces ruff + pytest + coverage; **`docs/boost-endpoint-api.md`** matches shipped endpoints; README updated for endpoint configuration.

**boost_endpoint — complete in this week**

- Implement `src/boost_weblate/endpoint/` in full (fresh code; fork is reference only): `AppConfig`, URLs, views, serializers, and services for **all** REST endpoints.
- Load the app by setting `WEBLATE_ADD_APPS=boost_weblate.endpoint` (Docker env var) or adding `"boost_weblate.endpoint"` to `INSTALLED_APPS` in `settings-override.py`.
- **URL registration:** use the approach resolved in Week 1 (see above).
- Add a request/response test for **every** endpoint. Document `WEBLATE_ADD_APPS` and endpoint URLs in `README.md`.

The `AppConfig`, URL config, and settings registration skeletons are in [Appendix C: Prototype — Minimal Plugin](#appendix-c-prototype--minimal-plugin).

## Documentation & unit CI — complete in this week

- Write **`docs/boost-endpoint-api.md`**: REST contract for `/boost-endpoint/` (aligned with the endpoints shipped above).
- Implement **`ci.yml`**: `ruff check`, `pytest --cov --cov-fail-under=90`, coverage upload.

---

## Week 3

**Weekly outcome:** **`integration.yml`** is fully working (no partial phases); **`docs/deployment-runbook.md`** written once to match the live CD path; CD script and release tag; fork retired.

## Plugin CI — complete in this week

- Replace the **`integration.yml`** placeholder with a finished workflow: Docker Compose stack, `uv pip install weblate "git+https://…/cppa-weblate-plugin@HEAD"`, smoke-test format registration and `/boost-endpoint/`.

## CD, deployment docs, and release — complete in this week

- Document `WEBLATE_ADD_APPS=boost_weblate.endpoint` and full `settings-override.py` wiring in the example environment file and **`docs/deployment-runbook.md`**. No manual volume steps. Include install, env vars, health checks, and **plugin-tag rollback** (pin CD to previous tag, redeploy). Validate the runbook against the CD stack you ship in this week’s PR so operator steps match the built image and compose layout.
- **CD script:** clone upstream `weblate-docker`, edit `Dockerfile`: replace `"/app/boost-weblate[${WEBLATE_EXTRAS}]"` with PyPI `weblate[${WEBLATE_EXTRAS}]`, add `uv pip install "git+https://…/cppa-weblate-plugin@<tag>"`, `COPY` `settings-override.py` from the plugin checkout (e.g. `/app/data/settings-override.py`), then build and deploy. Document plugin tag/ref in the runbook; add Renovate or equivalent **on the CD side** if desired.
- **Tag & version:** Git tag uses the format `boost-plugin-vX.Y.Z` (e.g. `boost-plugin-v1.0.0`). The Python package version in `pyproject.toml` is the PEP 440-compatible `X.Y.Z` (e.g. `1.0.0`). The CD script pins the plugin via the git tag; `pip`/`uv` sees the numeric version. Roll forward/rollback via CD script / deploy config (plugin tag).
- **Retire `boost-weblate` fork** after production verification; remove any install path still referencing it.

---

## Appendix A: Alternatives Considered

| Alternative | Why rejected |
|---|---|
| **Continue maintaining the fork** | Fork diverges from upstream on every Weblate release; upgrade cost grows over time; security patches must be cherry-picked manually; no path to using upstream Weblate from PyPI |
| **Monkey-patch Weblate at runtime** | Brittle against any internal refactor; not endorsed by Weblate docs; would fail C1 and C2 |
| **Contribute QuickBook format upstream** | QuickBook is Alliance-specific; upstream is unlikely to accept it; does not cover `boost_endpoint` |
| **Custom Weblate Docker image with source edits** | Still a fork problem in disguise; `COPY`-in override approach achieves the same result without source modification |

The standalone plugin approach is the only alternative that satisfies all six criteria.

---

## Appendix B: Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | `BaseFormat` ABC changes between Weblate releases, breaking `QuickBookFormat` | Low — it is the public extension API | High | Pin Weblate version in `pyproject.toml`; plugin CI installs both packages on every PR; bumping the pin is a deliberate, tested action |
| R2 | Weblate removes or renames `WEBLATE_FORMATS` / `WEBLATE_ADD_APPS` Docker env vars | Very low — these are documented deployment knobs | High | Same pin + plugin CI; if removed, `settings-override.py` `COPY` path is a fallback requiring only a `Dockerfile` edit |
| R3 | Django major-version upgrade inside Weblate breaks `boost_endpoint` views/serializers | Low — Django REST patterns are stable across majors | Medium | Standard Django upgrade path applies; no Weblate-internal Django usage in the plugin |
| R4 | `git+https://…@<tag>` install fails in air-gapped or restricted network environments | Medium — depends on deployment environment | Medium | Mirror the plugin package to an internal PyPI index if required; the install mechanism is standard pip and switchable |
| R5 | Scope creep requiring Weblate internal API access (e.g. signals, celery tasks) | Low given current requirements | High | Any new requirement that cannot be satisfied via documented extension points is a no-go trigger |

---

## Appendix C: Prototype — Minimal Plugin

### Translation format handler (`QuickBookFormat`)

The minimal skeleton needed to register one translation format handler in Weblate. Confirms that `BaseFormat` subclassing and `WEBLATE_FORMATS` registration work end-to-end with no fork or monkey-patch.

```python
# src/boost_weblate/formats/quickbook.py
from weblate.formats.base import BaseFormat

class QuickBookFormat(BaseFormat):
    name = "QuickBook"
    format_id = "quickbook"
    monolingual = True
    autodetect_extensions = [".qbk"]

    def load(self, storefile, template_store):
        # Parse QuickBook source into translation units
        ...

    def save(self):
        # Serialise translation units back to QuickBook
        ...
```

```python
# settings-override.py  (snippet)
WEBLATE_FORMATS += ("boost_weblate.formats.quickbook.QuickBookFormat",)
```

**Acceptance check:** install alongside upstream Weblate and verify the format appears in the Weblate admin UI under **Formats**.

### Django app skeleton (`boost_endpoint`)

The minimal skeleton needed to load `boost_endpoint` as a standard Django app via `INSTALLED_APPS`. Note: Weblate's `urls.py` does not auto-discover URL patterns from added apps — the plugin must register its own URLs (e.g. via `AppConfig.ready()` or a `ROOT_URLCONF` override).

```python
# src/boost_weblate/endpoint/apps.py
from django.apps import AppConfig

class BoostEndpointConfig(AppConfig):
    name = "boost_weblate.endpoint"
    label = "boost_endpoint"
    verbose_name = "Boost documentation translation API"
```

```python
# src/boost_weblate/endpoint/urls.py
from django.urls import path
from . import views

app_name = "boost_endpoint"

urlpatterns = [
    path("components/", views.ComponentListView.as_view(), name="component-list"),
    path("components/<str:project>/<str:component>/", views.ComponentDetailView.as_view(), name="component-detail"),
]
```

```python
# settings-override.py  (snippet)
INSTALLED_APPS += ["boost_weblate.endpoint"]
# or via Docker env var: WEBLATE_ADD_APPS=boost_weblate.endpoint
```

**Acceptance check:** install alongside upstream Weblate and confirm `/boost-endpoint/components/` returns HTTP 200.
