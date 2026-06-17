# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""Pytest hooks: ``sys.path``, ``DJANGO_SETTINGS_MODULE``, and ``django.setup()``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def pytest_configure() -> None:
    root = str(_REPO_ROOT)
    src = str(_REPO_ROOT / "src")
    if root not in sys.path:
        sys.path.insert(0, root)
    if src not in sys.path:
        sys.path.insert(0, src)

    from datetime import timedelta

    from hypothesis import HealthCheck
    from hypothesis import settings as hypothesis_settings

    hypothesis_settings.register_profile(
        "ci",
        max_examples=50,
        deadline=timedelta(milliseconds=500),
        suppress_health_check=[HealthCheck.too_slow],
        derandomize=True,
    )
    hypothesis_settings.register_profile(
        "dev",
        max_examples=200,
        deadline=timedelta(seconds=2),
        suppress_health_check=[HealthCheck.too_slow],
    )
    profile = os.environ.get("HYPOTHESIS_PROFILE", "ci")
    hypothesis_settings.load_profile(profile)

    # Always use bundled settings so a host ``DJANGO_SETTINGS_MODULE`` does not
    # break collection or ``python tests/formats/test_quickbook.py``.
    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.django_qbk_format_settings"

    import django
    from django.conf import settings

    if not settings.configured:
        django.setup()
