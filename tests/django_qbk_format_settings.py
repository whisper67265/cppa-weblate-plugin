# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Django settings for local QuickBookFormat smoke tests.

Uses Weblate's packaged ``settings_example`` then overrides paths and the
database to SQLite so ``django.setup()`` works without PostgreSQL.

``django.contrib.postgres`` is dropped because Weblate migrations still
reference PostgreSQL extensions when ``migrate`` runs; these smoke tests
only need ``django.setup()`` and do not run migrations.

Run::

    uv run python tests/formats/test_quickbook.py
"""

from __future__ import annotations

import os
import tempfile

import weblate.settings_example as _wl_example

from boost_weblate.settings_override import (
    ALLOWED_CLONE_HOSTS,
    merge_boost_endpoint_throttle_rates,
)

for _key, _value in _wl_example.__dict__.items():
    if _key.isupper():
        globals()[_key] = _value

INSTALLED_APPS = tuple(
    app for app in _wl_example.INSTALLED_APPS if app != "django.contrib.postgres"
)

_data = tempfile.mkdtemp(prefix="qbk_plugin_django_")
DATA_DIR = _data
CACHE_DIR = os.path.join(DATA_DIR, "cache")
MEDIA_ROOT = os.path.join(DATA_DIR, "media")
STATIC_ROOT = os.path.join(DATA_DIR, "static")
for _p in (CACHE_DIR, MEDIA_ROOT, STATIC_ROOT):
    os.makedirs(_p, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(DATA_DIR, "test.sqlite3"),
    }
}

SITE_DOMAIN = "test.invalid"
DEBUG = False

CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_RESULT_BACKEND = None

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

REST_FRAMEWORK = merge_boost_endpoint_throttle_rates(_wl_example.REST_FRAMEWORK)

ALLOWED_CLONE_HOSTS = ALLOWED_CLONE_HOSTS
