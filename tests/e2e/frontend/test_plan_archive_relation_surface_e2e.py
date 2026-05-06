from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[3]


def test_archive_tab_relation_surface_source_contract():
    source = (ROOT / "frontend/src/routes/plans/ArchiveTab.svelte").read_text(encoding="utf-8")

    assert "selectedRelations" in source
    assert "미해결 후속" in source
    assert "관계 없음" in source


def test_plan_viewer_relation_surface_source_contract():
    source = (ROOT / "frontend/src/routes/plans/PlanViewer.svelte").read_text(encoding="utf-8")

    assert "계획 관계" in source
    assert "getRelations" in source
    assert "unresolved_followup" in source
