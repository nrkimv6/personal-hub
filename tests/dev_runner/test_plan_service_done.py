"""plan_service done 흐름 관련 TC — Phase T1 (RIGHT-BICEP + CORRECT)

대상:
- _archive_plan(): companion _todo.md 아카이브 처리
- _can_done(): worktree/branch 존재 시 False 반환
- get_plan_status(): 가이드/아이디어 문서 유형 감지
- _check_branch_exists() / _check_worktree_exists(): subprocess 안전 기본값
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.dev_runner.schemas import PlanFileResponse, PlanProgressResponse
from app.modules.dev_runner.services.plan_service import PlanService
from app.modules.dev_runner.services.plan_path_resolver import PathRuleError


# ===========================================================================
# 헬퍼 픽스처
# ===========================================================================

@pytest.fixture
def service(tmp_path):
    """PlanService 인스턴스 (임시 디렉토리 기반)"""
    svc = PlanService.__new__(PlanService)
    svc._cache = {}
    svc._ignored_plans = set()
    svc._registered_paths = []
    return svc


def make_plan_response(path: str, status: str = "구현완료", total: int = 5, done: int = 5) -> PlanFileResponse:
    return PlanFileResponse(
        path=path,
        filename=Path(path).name,
        title="test plan",
        status=status,
        progress=PlanProgressResponse(done=done, total=total, percent=int(done / total * 100) if total else 0),
        summary=None,
        branch=None,
        worktree=None,
    )


# ===========================================================================
# TC 14: _archive_plan() — companion _todo.md도 함께 이동 (R: Right)
# ===========================================================================

def test_archive_plan_also_archives_todo_right(tmp_path, service):
    """R: _archive_plan() 호출 시 companion _todo.md도 archive 디렉토리로 이동"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    archive_dir = tmp_path / "docs" / "archive"
    archive_dir.mkdir(parents=True)

    plan_file = plan_dir / "2026-01-01_test.md"
    todo_file = plan_dir / "2026-01-01_test_todo.md"
    plan_file.write_text("> 상태: 구현완료\n\n# Test\n", encoding="utf-8")
    todo_file.write_text("# Test TODO\n", encoding="utf-8")

    mv_calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        mv_calls.append(args)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        archive_path, todo_archive_path = asyncio.run(
            service._archive_plan(str(plan_file), plan_file.read_text(encoding="utf-8"))
        )

    assert len(mv_calls) == 2, f"git mv 2회 호출 기대, 실제: {len(mv_calls)}"
    # 두 번째 호출에 _todo.md 포함 확인
    second_call_args = mv_calls[1]
    assert "_todo" in second_call_args[2] or "_todo" in second_call_args[3], \
        f"두 번째 git mv에 _todo.md 경로 기대: {second_call_args}"
    assert todo_archive_path is not None


# ===========================================================================
# TC 15: _archive_plan() — _todo.md 없으면 git mv 1회 (B: Boundary)
# ===========================================================================

def test_archive_plan_no_todo_unchanged_boundary(tmp_path, service):
    """B: companion _todo.md 없는 plan → git mv 1회만 호출"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    (tmp_path / "docs" / "archive").mkdir(parents=True)

    plan_file = plan_dir / "2026-01-01_solo.md"
    plan_file.write_text("> 상태: 구현완료\n# Solo Plan\n", encoding="utf-8")

    mv_calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        mv_calls.append(args)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
        archive_path, todo_archive_path = asyncio.run(
            service._archive_plan(str(plan_file), plan_file.read_text(encoding="utf-8"))
        )

    assert len(mv_calls) == 1, f"git mv 1회 호출 기대, 실제: {len(mv_calls)}"
    assert todo_archive_path is None


def test_archive_plan_resolver_error_keeps_companion_todo_error(tmp_path, service):
    """E: resolver 실패 시 plan/_todo 모두 원위치 유지 + git mv 미호출."""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)

    plan_file = plan_dir / "2026-01-01_test.md"
    todo_file = plan_dir / "2026-01-01_test_todo.md"
    plan_original = "> 상태: 구현완료\n\n# Test\n"
    todo_original = "# Test TODO\n"
    plan_file.write_text(plan_original, encoding="utf-8")
    todo_file.write_text(todo_original, encoding="utf-8")

    with patch(
        "app.modules.dev_runner.services.archive_service.resolve_archive_target_or_raise",
        side_effect=PathRuleError("archive target resolve failed: source=/x rule=resolve_plan_target reason=invalid"),
    ), patch("asyncio.create_subprocess_exec") as mock_exec:
        with pytest.raises(ValueError, match="archive target resolve failed"):
            asyncio.run(service._archive_plan(str(plan_file), plan_file.read_text(encoding="utf-8")))

    mock_exec.assert_not_called()
    assert plan_file.read_text(encoding="utf-8") == plan_original
    assert todo_file.read_text(encoding="utf-8") == todo_original


# ===========================================================================
# TC 16: _can_done() — 살아있는 branch 있으면 False (E: Error)
# ===========================================================================

def test_can_done_live_branch_returns_false_error(tmp_path, service):
    """E: > branch: impl/foo + 해당 branch 존재 → _can_done() False"""
    plan_file = tmp_path / "plan_with_branch.md"
    plan_file.write_text(
        "> 상태: 구현완료\n> branch: impl/foo\n> 진행률: 5/5 (100%)\n",
        encoding="utf-8"
    )

    plan = make_plan_response(str(plan_file))

    with patch.object(service, "_check_branch_exists", return_value=True):
        result = service._can_done(plan)

    assert result is False


# ===========================================================================
# TC 17: _can_done() — 살아있는 worktree 있으면 False (E: Error)
# ===========================================================================

def test_can_done_live_worktree_returns_false_error(tmp_path, service):
    """E: > worktree: .worktrees/impl-foo + 해당 worktree 존재 → _can_done() False"""
    plan_file = tmp_path / "plan_with_worktree.md"
    plan_file.write_text(
        "> 상태: 구현완료\n> worktree: .worktrees/impl-foo\n> 진행률: 5/5 (100%)\n",
        encoding="utf-8"
    )

    plan = make_plan_response(str(plan_file))

    with patch.object(service, "_check_branch_exists", return_value=False), \
         patch.object(service, "_check_worktree_exists", return_value=True):
        result = service._can_done(plan)

    assert result is False


# ===========================================================================
# TC 18: _can_done() — branch 필드 없는 plan, 100% 완료 → True (R: Right)
# ===========================================================================

def test_can_done_no_branch_field_skips_check_right(tmp_path, service):
    """R: > branch: 없는 plan, 100% 완료 → 기존 로직으로 True"""
    plan_file = tmp_path / "plan_no_branch.md"
    plan_file.write_text(
        "> 상태: 구현완료\n> 진행률: 5/5 (100%)\n",
        encoding="utf-8"
    )

    plan = make_plan_response(str(plan_file))

    result = service._can_done(plan)

    assert result is True


# ===========================================================================
# TC 19: _can_done() — branch 있지만 삭제됨 → True (R: Right)
# ===========================================================================

def test_can_done_dead_branch_proceeds_right(tmp_path, service):
    """R: > branch: impl/old 있지만 branch 삭제됨 → _can_done() True"""
    plan_file = tmp_path / "plan_dead_branch.md"
    plan_file.write_text(
        "> 상태: 구현완료\n> branch: impl/old\n> 진행률: 5/5 (100%)\n",
        encoding="utf-8"
    )

    plan = make_plan_response(str(plan_file))

    with patch.object(service, "_check_branch_exists", return_value=False):
        result = service._can_done(plan)

    assert result is True


# ===========================================================================
# TC 20: get_plan_status() — > 유형: 가이드 → "가이드" (R: Right)
# ===========================================================================

def test_get_plan_status_guide_by_type_field_right(tmp_path, service):
    """R: > 유형: 가이드 → status '가이드' 반환"""
    plan_file = tmp_path / "some-doc.md"
    plan_file.write_text(
        "> 유형: 가이드\n\n# 가이드 문서\n",
        encoding="utf-8"
    )

    result = service.get_plan_status(plan_file)

    assert result == "가이드"


# ===========================================================================
# TC 21: get_plan_status() — 파일명 foo-guide.md → "가이드" (R: Right)
# ===========================================================================

def test_get_plan_status_guide_by_stem_right(tmp_path, service):
    """R: 파일명 foo-guide.md (상태/유형 헤더 없음) → '가이드' 반환"""
    plan_file = tmp_path / "foo-guide.md"
    plan_file.write_text("# 가이드 제목\n\n내용\n", encoding="utf-8")

    result = service.get_plan_status(plan_file)

    assert result == "가이드"


# ===========================================================================
# TC 22: _can_done() — status "가이드", total=0 → False (B: Boundary)
# ===========================================================================

def test_can_done_guide_status_false_boundary(tmp_path, service):
    """B: status '가이드', progress total=0 → _can_done() False"""
    plan_file = tmp_path / "guide.md"
    plan_file.write_text("# 가이드\n내용\n", encoding="utf-8")

    plan = make_plan_response(str(plan_file), status="가이드", total=0, done=0)

    result = service._can_done(plan)

    assert result is False


# ===========================================================================
# TC 23: _check_branch_exists() — subprocess 실패 시 False (B: Boundary)
# ===========================================================================

def test_check_branch_exists_subprocess_error_boundary(service):
    """B: git 명령 실패(FileNotFoundError) 시 → False (안전 기본값)"""
    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        result = service._check_branch_exists("any-branch")

    assert result is False


# ===========================================================================
# Phase T4: HTTP 통합 테스트
# ===========================================================================

import pytest
import requests


ADMIN_API = "http://localhost:8001"


def test_batch_done_endpoint_responds_http():
    """T4: POST /api/v1/dev-runner/plans/batch-done — 엔드포인트 존재 및 응답 스키마 확인"""
    try:
        r = requests.post(f"{ADMIN_API}/api/v1/dev-runner/plans/batch-done", timeout=10)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        pytest.skip("Admin API (port 8001) not available or timed out — skip T4")

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "total" in body, f"'total' field missing: {body}"
    assert "success" in body
    assert "failed" in body
    assert "results" in body


def test_batch_done_skips_live_worktree_http():
    """T4: batch-done API — worktree/branch 필드가 있는 plan은 _can_done()에서 False → results 미포함
    (단위 테스트 TC16/TC17로 직접 검증, HTTP 레이어 응답 스키마 확인)
    """
    try:
        r = requests.post(f"{ADMIN_API}/api/v1/dev-runner/plans/batch-done", timeout=10)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        pytest.skip("Admin API (port 8001) not available or timed out — skip T4")

    assert r.status_code == 200
    body = r.json()
    # 현재 실행 중인 impl/improve-done-skill branch plan은 results에서 제외되어야 함
    results = body.get("results", [])
    live_plan = next(
        (x for x in results if "improve-done-skill" in x.get("filename", "")),
        None
    )
    assert live_plan is None or live_plan.get("success") is False, \
        "현재 활성 worktree plan이 batch-done에서 처리됐으면 안 됨"
