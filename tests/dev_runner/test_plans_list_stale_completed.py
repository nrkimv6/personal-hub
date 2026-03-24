"""완료된 plan이 plans 목록에 잔존하는 버그 수정 TC

Phase T1 (단위 TC):
  - RIGHT: 100% 진행률 plan이 _is_ignored_plan(progress 포함)에서 True 반환
  - BOUNDARY: progress=None 시 상태 헤더만으로 판단
  - CROSS: _scan_plan_dir가 완료 plan을 list_plans에서 제외
  - RIGHT: list_plans() 결과에 progress 객체 포함 (None 아님)

Phase T3 (통합 TC):
  - 실제 파일시스템에서 100% 완료 _todo.md가 list_plans에서 제외됨
  - 완료 plan 2개 + 미완료 plan 3개 혼합 시 미완료만 반환
"""
import json
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def svc(tmp_path, dev_runner_config_isolation):
    """격리된 PlanService 인스턴스"""
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    return PlanService()


def _make_plan(plan_dir: Path, filename: str, status: str = "구현중", checkboxes: list[str] | None = None) -> Path:
    """테스트용 plan .md 파일 생성"""
    if checkboxes is None:
        checkboxes = ["[ ] 작업1"]
    total = len(checkboxes)
    done = sum(1 for c in checkboxes if c.startswith("[x]"))
    percent = int(done / total * 100) if total > 0 else 0

    lines = "\n".join(f"- {c}" for c in checkboxes)
    content = (
        f"# Test Plan\n\n"
        f"> 상태: {status}\n"
        f"> 진행률: {done}/{total} ({percent}%)\n\n"
        f"## TODO\n\n{lines}\n"
    )
    p = plan_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


def _register_path(reg_file: Path, path: str, path_type: str = "plan"):
    """registered_paths.json에 경로 추가"""
    paths = json.loads(reg_file.read_text(encoding="utf-8"))
    paths.append({"path": path, "type": path_type})
    reg_file.write_text(json.dumps(paths), encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase T1: 단위 TC
# ---------------------------------------------------------------------------

def test_is_ignored_plan_with_full_progress_RIGHT(svc, tmp_path):
    """RIGHT: 100% 진행률 plan이 _is_ignored_plan(progress=PlanProgressResponse(done=3,total=3))에서 True 반환"""
    from app.modules.dev_runner.services.plan_service import PlanProgressResponse

    plan = _make_plan(tmp_path, "test_full_progress.md", status="구현중", checkboxes=["[x] 작업1", "[x] 작업2", "[x] 작업3"])
    progress = PlanProgressResponse(done=3, total=3, percent=100)

    result = svc._is_ignored_plan(plan, "구현중", progress)
    assert result is True, "100% 진행률 plan은 ignored=True 여야 함"


def test_is_ignored_plan_without_progress_BOUNDARY(svc, tmp_path):
    """BOUNDARY: progress=None 시 상태 헤더만으로 판단 — 구현중은 False, 구현완료는 True"""
    plan = _make_plan(tmp_path, "test_no_progress.md", status="구현중", checkboxes=["[x] 작업1", "[x] 작업2"])

    # progress=None이면 체크박스 100%여도 False (상태가 완료 계열 아님)
    result_in_progress = svc._is_ignored_plan(plan, "구현중")
    assert result_in_progress is False, "progress=None, 상태=구현중이면 False 여야 함"

    # 상태가 구현완료면 progress 없어도 True
    result_done = svc._is_ignored_plan(plan, "구현완료")
    assert result_done is True, "상태=구현완료면 progress 없어도 True 여야 함"


def test_scan_plan_dir_filters_completed_todo_CROSS(tmp_path, dev_runner_config_isolation):
    """CROSS: _scan_plan_dir가 100% 완료 _todo.md를 list_plans(include_ignored=False)에서 제외"""
    from app.modules.dev_runner.services.plan_service import PlanService

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()

    # 100% 완료 _todo.md
    _make_plan(plan_dir, "2026-01-01_feature_todo.md", status="구현중", checkboxes=["[x] 작업1", "[x] 작업2"])
    # 미완료 plan
    _make_plan(plan_dir, "2026-01-02_pending.md", status="구현중", checkboxes=["[ ] 작업1"])

    cfg = dev_runner_config_isolation
    _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "plan")

    svc = PlanService()
    results = svc.list_plans(include_ignored=False)
    filenames = [r.filename for r in results]

    assert "2026-01-01_feature_todo.md" not in filenames, "100% 완료 plan은 목록에서 제외돼야 함"
    assert "2026-01-02_pending.md" in filenames, "미완료 plan은 목록에 포함돼야 함"


def test_list_plans_returns_progress_in_response_RIGHT(tmp_path, dev_runner_config_isolation):
    """RIGHT: list_plans() 결과의 PlanFileResponse.progress가 None이 아닌 실제 진행률 객체"""
    from app.modules.dev_runner.services.plan_service import PlanService

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()

    _make_plan(plan_dir, "2026-01-03_active.md", status="구현중", checkboxes=["[ ] 작업1", "[x] 작업2"])

    cfg = dev_runner_config_isolation
    _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "plan")

    svc = PlanService()
    results = svc.list_plans(include_ignored=False)
    assert len(results) == 1
    plan = results[0]

    assert plan.progress is not None, "progress가 None이 아니어야 함"
    assert plan.progress.total == 2
    assert plan.progress.done == 1
    assert plan.progress.percent == 50


# ---------------------------------------------------------------------------
# Phase T3: 통합 TC
# ---------------------------------------------------------------------------

def test_completed_todo_not_in_plans_list_INTEGRATION(tmp_path, dev_runner_config_isolation):
    """INTEGRATION: 100% 완료 _todo.md → list_plans에서 제외, include_ignored=True면 ignored=True로 포함"""
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()

    # 모든 체크박스 완료된 _todo.md
    _make_plan(plan_dir, "2026-01-04_task_todo.md", status="구현중", checkboxes=["[x] 작업1", "[x] 작업2", "[x] 작업3"])

    _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "plan")

    svc = PlanService()
    active = svc.list_plans(include_ignored=False)
    assert not any(r.filename == "2026-01-04_task_todo.md" for r in active), "완료 plan은 활성 목록에서 제외돼야 함"

    all_plans = svc.list_plans(include_ignored=True)
    ignored_plan = next((r for r in all_plans if r.filename == "2026-01-04_task_todo.md"), None)
    assert ignored_plan is not None, "include_ignored=True면 포함돼야 함"
    assert ignored_plan.ignored is True, "ignored=True 여야 함"


def test_mixed_plans_integration(tmp_path, dev_runner_config_isolation):
    """INTEGRATION: 완료 plan 2개 + 미완료 plan 3개 → list_plans에서 미완료 3개만 반환"""
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()

    # 완료 plan 2개
    _make_plan(plan_dir, "2026-01-05_done1_todo.md", status="구현중", checkboxes=["[x] 작업1", "[x] 작업2"])
    _make_plan(plan_dir, "2026-01-06_done2.md", status="구현완료", checkboxes=["[x] 작업1"])

    # 미완료 plan 3개
    _make_plan(plan_dir, "2026-01-07_active1.md", status="구현중", checkboxes=["[ ] 작업1", "[x] 작업2"])
    _make_plan(plan_dir, "2026-01-08_active2.md", status="초안", checkboxes=["[ ] 작업1"])
    _make_plan(plan_dir, "2026-01-09_active3.md", status="구현중", checkboxes=["[ ] 작업1"])

    _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "plan")

    svc = PlanService()
    results = svc.list_plans(include_ignored=False)
    filenames = {r.filename for r in results}

    assert "2026-01-05_done1_todo.md" not in filenames
    assert "2026-01-06_done2.md" not in filenames
    assert "2026-01-07_active1.md" in filenames
    assert "2026-01-08_active2.md" in filenames
    assert "2026-01-09_active3.md" in filenames

    # 진행률 정확성 확인
    active1 = next(r for r in results if r.filename == "2026-01-07_active1.md")
    assert active1.progress is not None
    assert active1.progress.done == 1
    assert active1.progress.total == 2
