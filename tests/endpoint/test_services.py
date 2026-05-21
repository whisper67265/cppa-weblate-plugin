# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

from __future__ import annotations

import pytest

from boost_weblate.endpoint.services import BoostComponentService


def test_boost_component_service_process_all_clone_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """process_all runs clone; without network, assert structured failure."""
    svc = BoostComponentService(
        organization="o",
        lang_code="en",
        version="v",
        extensions=None,
    )
    monkeypatch.setattr(svc, "clone_repository", lambda *_a, **_kw: False)
    results = svc.process_all(["json"], user=None)
    assert results["total_submodules"] == 1
    assert results["successful"] == 0
    assert results["failed"] == 1
    assert len(results["submodule_results"]) == 1
    sub = results["submodule_results"][0]
    assert sub["submodule"] == "json"
    assert sub["success"] is False
    assert any("clone" in err.lower() for err in sub["errors"])
