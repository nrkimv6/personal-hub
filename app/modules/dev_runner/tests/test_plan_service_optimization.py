"""plan_service 최적화 단위 테스트 (Phase 1+2)"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.modules.dev_runner.services.plan_service import PlanService
from app.modules.dev_runner.schemas import PlanProgressResponse


@pytest.fixture
def tmp_plan_dir(tmp_path):
    """임시 plan/archive 디렉토리 구조 생성"""
    plan_dir = tmp_path / "plans"
    archive_dir = tmp_path / "plans" / "archive"
    plan_dir.mkdir()
    archive_dir.mkdir()

    # plan 파일 2개
    (plan_dir / "task1.md").write_text("# Task 1\n> 상태: 구현중\n- [ ] item1\n", encoding="utf-8")
    (plan_dir / "task2.md").write_text("# Task 2\n> 상태: 구현중\n- [ ] item2\n", encoding="utf-8")

    # archive 파일 1개
    (archive_dir / "done1.md").write_text("# Done 1\n> 상태: 완료\n- [x] item1\n", encoding="utf-8")

    return tmp_path


def _make_service(tmp_path) -> PlanService:
    """테스트용 PlanService (등록 경로 설정)"""
    svc = PlanService.__new__(PlanService)
    svc._registered_paths = [
        {"path": str(tmp_path / "plans"), "type": "folder", "path_type": "plan"}
    ]
    svc._ignore_list = set()
    svc._ignored_plans = []
    svc._plans_cache = None
    svc._plans_cache_with_ignored = None
    svc._archive_cache = {}
    return svc


def test_scan_all_plans_skip_archive(tmp_plan_dir):
    """R: include_ignored=False일 때 archive 경로 plan 미포함"""
    svc = _make_service(tmp_plan_dir)
    results = svc._scan_all_plans(include_ignored=False)
    paths = [r.path for r in results]
    assert all("archive" not in p for p in paths), f"archive가 포함됨: {paths}"
    assert len(paths) >= 1


def test_scan_all_plans_include_archive_when_ignored(tmp_plan_dir):
    """R: include_ignored=True일 때 archive 타입 경로 포함"""
    svc = _make_service(tmp_plan_dir)
    # archive 폴더를 archive 타입으로 별도 등록
    svc._registered_paths = [
        {"path": str(tmp_plan_dir / "plans"), "type": "folder", "path_type": "plan"},
        {"path": str(tmp_plan_dir / "plans" / "archive"), "type": "archive", "path_type": "archive"},
    ]
    results = svc._scan_all_plans(include_ignored=True)
    paths = [r.path for r in results]
    assert any("archive" in p for p in paths), f"archive가 미포함: {paths}"


def test_list_plans_no_progress(tmp_plan_dir):
    """R: list_plans() 반환 시 progress는 None"""
    svc = _make_service(tmp_plan_dir)
    plans = svc.list_plans()
    for p in plans:
        assert p.progress is None, f"{p.path}의 progress가 None이 아님: {p.progress}"


def test_list_plans_status_only_io(tmp_plan_dir):
    """B: progress 없이도 status만으로 ignored 판정 가능"""
    svc = _make_service(tmp_plan_dir)
    # 완료 상태 파일
    done_file = tmp_plan_dir / "plans" / "completed.md"
    done_file.write_text("# Completed\n> 상태: 완료\n- [x] item\n", encoding="utf-8")
    svc._plans_cache = None  # 캐시 초기화
    plans = svc.list_plans()
    # 완료 상태는 ignored로 처리되어 list_plans(include_ignored=False)에 나타나지 않아야 함
    for p in plans:
        assert p.status != "완료", f"완료 상태 plan이 목록에 포함됨: {p.path}"


def test_is_ignored_plan_without_progress(tmp_plan_dir):
    """B: progress=None일 때 status 기반 판정 정상 동작"""
    svc = _make_service(tmp_plan_dir)
    plan_path = tmp_plan_dir / "plans" / "task1.md"

    # status="구현중", progress=None → ignored 아님
    result = svc._is_ignored_plan(plan_path, "구현중", progress=None)
    assert result is False

    # status="완료", progress=None → ignored
    result = svc._is_ignored_plan(plan_path, "완료", progress=None)
    assert result is True


def test_scan_all_plans_empty_registered_paths():
    """B: 등록 경로 0개일 때 빈 리스트 반환"""
    svc = PlanService.__new__(PlanService)
    svc._registered_paths = []
    svc._ignore_list = set()
    svc._ignored_plans = []
    svc._plans_cache = None
    svc._plans_cache_with_ignored = None
    svc._archive_cache = {}
    results = svc._scan_all_plans(include_ignored=False)
    assert results == []


def test_invalidate_cache_after_mutation(tmp_plan_dir):
    """R: set_plan_status() 후 캐시 무효화 확인"""
    svc = _make_service(tmp_plan_dir)
    # 첫 번째 list_plans 호출로 캐시 채움
    plans_before = svc.list_plans()
    assert svc._plans_cache is not None

    # invalidate 후 캐시 None
    svc.invalidate_plans_cache()
    assert svc._plans_cache is None
    assert svc._plans_cache_with_ignored is None
