"""resolve_project_dir TC — RIGHT-BICEP 기반

resolve_project_dir() 헬퍼 함수 검증.
(MergeOrchestrator는 PostMergePipeline 리팩토링으로 삭제됨 — handle_merge_stage로 대체)
"""

import json
import sys
import pytest
from pathlib import Path

# plan-runner 모듈을 직접 import 가능하도록 sys.path에 추가
_PLAN_RUNNER_DIR = Path(r"D:\work\project\service\wtools\common\tools\plan-runner")
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

from core.merge import resolve_project_dir


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def projects_json(tmp_path):
    """임시 projects.json 파일 생성 및 경로 반환"""
    data = {
        "projects": [
            {"name": "monitor-page", "path": r"D:\work\project\tools\monitor-page"},
            {"name": "wtools", "path": r"D:\work\project\service\wtools"},
        ]
    }
    p = tmp_path / "projects.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# RIGHT: 정상 동작 — resolve_project_dir
# ---------------------------------------------------------------------------


def test_resolve_project_dir_found(projects_json):
    """R: 존재하는 프로젝트명 → 올바른 Path 반환"""
    result = resolve_project_dir("monitor-page", projects_json)
    assert result == Path(r"D:\work\project\tools\monitor-page")


# ---------------------------------------------------------------------------
# BOUNDARY: 경계값 — resolve_project_dir
# ---------------------------------------------------------------------------


def test_resolve_project_dir_not_found(projects_json):
    """B: 존재하지 않는 프로젝트명 → None 반환"""
    result = resolve_project_dir("nonexistent", projects_json)
    assert result is None


# ---------------------------------------------------------------------------
# EDGE: 예외 상황 — resolve_project_dir
# ---------------------------------------------------------------------------


def test_resolve_project_dir_file_missing():
    """E: projects.json 파일 미존재 → None 반환 (예외 미전파)"""
    result = resolve_project_dir("monitor-page", Path("/nonexistent/path.json"))
    assert result is None


def test_resolve_project_dir_invalid_json(tmp_path):
    """E: 잘못된 JSON → None 반환 (예외 미전파)"""
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{", encoding="utf-8")
    result = resolve_project_dir("monitor-page", bad)
    assert result is None
