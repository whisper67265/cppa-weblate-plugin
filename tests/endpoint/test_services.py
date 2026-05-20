# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import pytest

from boost_weblate.endpoint.services import BoostComponentService


def test_boost_component_service_process_all_not_implemented() -> None:
    svc = BoostComponentService(
        organization="o",
        lang_code="en",
        version="v",
        extensions=None,
    )
    with pytest.raises(NotImplementedError) as excinfo:
        svc.process_all(["json"], user=None)
    assert "not implemented" in str(excinfo.value).lower()
