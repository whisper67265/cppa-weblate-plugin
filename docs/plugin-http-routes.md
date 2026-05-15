<!--
SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# Why the plugin must register its own URLs

This answers [Boost Weblate Plugin Refactor — Plan](boost-weblate-plugin-refactor-plan.md) (§ URL registration): Weblate’s `urls.py` does **not** auto-discover URLconfs from arbitrary `INSTALLED_APPS` entries; the plugin must attach routes explicitly.

Read **`boost-weblate/weblate/urls.py`** (same layout as [upstream `weblate/urls.py`](https://github.com/WeblateOrg/weblate/blob/main/weblate/urls.py)):

1. **Single hand-built list.** Routes are collected in **`real_patterns`**, starting with concrete `path(...)` entries—not Django’s per-app `urls.py` autoload.

```74:76:boost-weblate/weblate/urls.py
real_patterns = [
    path("", weblate.trans.views.dashboard.home, name="home"),
    path("projects/", weblate.trans.views.basic.list_projects, name="projects"),
```

2. **Optional apps only by name.** Extra routes appear when `urls.py` **explicitly** checks for known dotted apps in `settings.INSTALLED_APPS`, then mutates **`real_patterns`** (same file; examples include legal, git export, SAML—each `if "…" in settings.INSTALLED_APPS:` followed by `real_patterns +=` / `append`).

```1041:1047:boost-weblate/weblate/urls.py
if "weblate.legal" in settings.INSTALLED_APPS:
    real_patterns.extend(
        (
            path(
                "legal/",
                include(("weblate.legal.urls", "weblate.legal"), namespace="legal"),
```

3. **Final URLconf.** Either `urlpatterns = real_patterns` or, when `URL_PREFIX` is set, a wrapper `include(real_patterns)`—still no generic scan of your plugin package.

```1091:1095:boost-weblate/weblate/urls.py
# Handle URL prefix configuration
if not URL_PREFIX:
    urlpatterns = real_patterns
else:
    urlpatterns = [path(URL_PREFIX, include(real_patterns))]
```

**Conclusion:** Putting **`boost_weblate.endpoint`** in `INSTALLED_APPS` does not register HTTP routes by itself. The plan’s two supported approaches are:

- **`AppConfig.ready()`** — at startup, extend Weblate’s pattern list (this repo appends to **`weblate.urls.real_patterns`** in **`src/boost_weblate/endpoint/apps.py`**), **or**
- **`ROOT_URLCONF`** in **`boost_weblate/settings_override.py`** (copied to **`/app/data/settings-override.py`** in Docker) — a custom root URLconf that includes Weblate’s patterns and adds the plugin’s `include()`.
