"""dev-runner-command-listener.py — merge 완료 후 plan-runner 재시작 로직 테스트

테스트 대상:
1. 잔여 항목 카운트 로직 (_count_remaining_todos 상당)
2. _do_inline_merge() 성공 시 재시작 플래그 설정 및 _restart_plan_runner_after_merge() 호출
"""
import re
import sys
import types
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


# ============================================================
# 헬퍼: 잔여 항목 카운트 로직 (dev-runner-command-listener.py 내부 로직 재현)
# ============================================================

def _count_remaining_todos(plan_file) -> int:
    """_do_inline_merge finally 블록의 잔여 항목 카운트 로직 재현."""
    if plan_file is None:
        return 0
    try:
        plan_path = Path(plan_file)
        if not plan_path.is_file():
            return 0
        content = plan_path.read_text(encoding="utf-8")
        return len(re.findall(r'- \[ \]', content))
    except Exception:
        return 0


# ============================================================
# Phase T1-6: _count_remaining_todos 로직 TC
# ============================================================

class TestCountRemainingTodos:
    """잔여 TODO 카운트 로직 테스트"""

    def test_right_mixed_checkboxes(self, tmp_path):
        """Right: [ ] 2개 + [x] 1개 혼합 → 2 반환"""
        plan = tmp_path / "plan.md"
        plan.write_text(
            "- [ ] 작업1\n- [ ] 작업2\n- [x] 완료작업\n",
            encoding="utf-8",
        )
        assert _count_remaining_todos(str(plan)) == 2

    def test_boundary_all_checked(self, tmp_path):
        """Boundary: [x]만 있는 파일 → 0 반환"""
        plan = tmp_path / "plan.md"
        plan.write_text("- [x] 완료1\n- [x] 완료2\n", encoding="utf-8")
        assert _count_remaining_todos(str(plan)) == 0

    def test_boundary_empty_file(self, tmp_path):
        """Boundary: 빈 파일 → 0 반환"""
        plan = tmp_path / "plan.md"
        plan.write_text("", encoding="utf-8")
        assert _count_remaining_todos(str(plan)) == 0

    def test_error_missing_file(self, tmp_path):
        """Error: 존재하지 않는 경로 → 0 반환 (예외 전파 없음)"""
        missing = str(tmp_path / "nonexistent.md")
        assert _count_remaining_todos(missing) == 0

    def test_error_none_path(self):
        """Error: plan_file=None → 0 반환"""
        assert _count_remaining_todos(None) == 0


# ============================================================
# Phase T1-7: _do_inline_merge 재시작 로직 TC
# ============================================================

class TestDoInlineMergeRestart:
    """_do_inline_merge() 완료 후 재시작 트리거 로직 테스트

    구현 로직을 인라인으로 재현하여 조건별 동작을 검증한다.
    실제 _do_inline_merge는 Redis/MergeWorkflow 의존성이 크므로
    finally 블록의 재시작 결정 로직만 추출하여 단위 테스트한다.
    """

    def _simulate_restart_decision(
        self,
        redis_restart_value,  # Redis에서 읽은 restart_after_merge 값 (None이면 플래그 없음)
        plan_file_content,    # plan 파일 내용 (None이면 파일 없음)
        tmp_path,
    ):
        """finally 블록의 재시작 결정 로직을 재현."""
        mock_restart_fn = MagicMock()

        # plan 파일 준비
        if plan_file_content is not None:
            plan_path = tmp_path / "plan.md"
            plan_path.write_text(plan_file_content, encoding="utf-8")
            plan_file_str = str(plan_path)
        else:
            plan_file_str = None

        # Redis에서 restart_after_merge 읽기 (simulate)
        _restart_plan_file = redis_restart_value if redis_restart_value else None
        if _restart_plan_file and plan_file_str:
            _restart_plan_file = plan_file_str  # 실제로는 plan_file_str이 저장됨

        _restart_remaining = 0
        if _restart_plan_file:
            try:
                _content = Path(_restart_plan_file).read_text(encoding="utf-8")
                _restart_remaining = len(re.findall(r'- \[ \]', _content))
            except Exception:
                _restart_remaining = 1

        # 재시작 결정
        if _restart_plan_file and _restart_remaining > 0:
            mock_restart_fn(_restart_plan_file, _restart_remaining)

        return mock_restart_fn

    def test_right_merged_with_remaining(self, tmp_path):
        """Right: merge 성공 + [ ] 2개 → restart 함수 1회 호출"""
        plan_content = "- [ ] 작업1\n- [ ] 작업2\n"
        restart_fn = self._simulate_restart_decision(
            redis_restart_value="set",  # 플래그가 설정된 상태
            plan_file_content=plan_content,
            tmp_path=tmp_path,
        )
        restart_fn.assert_called_once()
        _, remaining_arg = restart_fn.call_args[0]
        assert remaining_arg == 2

    def test_boundary_no_remaining(self, tmp_path):
        """Boundary: merge 성공 + [ ] 0개 → 재시작 없음"""
        plan_content = "- [x] 완료1\n- [x] 완료2\n"
        restart_fn = self._simulate_restart_decision(
            redis_restart_value="set",
            plan_file_content=plan_content,
            tmp_path=tmp_path,
        )
        restart_fn.assert_not_called()

    def test_error_no_restart_flag(self, tmp_path):
        """Error: restart 플래그 없음 (conflict/test_failed/error) → 재시작 없음"""
        plan_content = "- [ ] 작업1\n"
        restart_fn = self._simulate_restart_decision(
            redis_restart_value=None,  # 플래그 없음
            plan_file_content=plan_content,
            tmp_path=tmp_path,
        )
        restart_fn.assert_not_called()

    def test_error_conflict_status(self, tmp_path):
        """Error: conflict 시 restart 플래그가 설정되지 않음 → 재시작 없음

        (conflict 분기에서는 redis set하지 않으므로 None으로 시뮬레이션)
        """
        plan_content = "- [ ] 작업1\n"
        restart_fn = self._simulate_restart_decision(
            redis_restart_value=None,  # conflict → 플래그 없음
            plan_file_content=plan_content,
            tmp_path=tmp_path,
        )
        restart_fn.assert_not_called()

    def test_boundary_no_plan_file(self, tmp_path):
        """Boundary: plan_file이 None → 재시작 없이 정상 종료"""
        restart_fn = self._simulate_restart_decision(
            redis_restart_value=None,
            plan_file_content=None,  # plan 파일 없음
            tmp_path=tmp_path,
        )
        restart_fn.assert_not_called()


# ============================================================
# Phase T1-9: Phase 2 진전 판정 — sync 활동 반영 TC
# ============================================================

class TestPhase2ProgressSyncActivity:
    """Phase 2 진전 판정에서 sync 활동을 진전으로 인정하는 로직 테스트.

    cli.py의 로직을 인라인으로 재현하여 _sync_had_activity 조건 검증.
    """

    def _simulate_phase2_progress(
        self,
        after_undone: int,
        before_undone: int,
        has_new_commits: bool,
        sync_had_activity: bool,
    ):
        """Phase 2 진전 판정 로직 재현 (cli.py:548-564 + 수정 후 로직).

        Returns:
            (no_progress: bool, failure_recorded: bool)
        """
        mock_scheduler = MagicMock()
        _no_progress = False

        if after_undone > 0 and after_undone >= before_undone:
            if has_new_commits:
                pass  # 경고만, no_progress = False 유지
            else:
                if sync_had_activity:
                    pass  # sync 활동 있음 → 진전 있음으로 처리, no_progress = False 유지
                else:
                    mock_scheduler.record_failure()
                    _no_progress = True
        elif after_undone > 0 and after_undone < before_undone:
            pass  # 체크박스 진전 있음

        return _no_progress, mock_scheduler.record_failure.called

    def test_no_progress_skipped_is_not_failure(self):
        """Right: sync skipped>0 + 체크박스 미변경 + 커밋 없음 → no_progress=False, 실패 기록 없음"""
        no_progress, failure_recorded = self._simulate_phase2_progress(
            after_undone=3,
            before_undone=3,  # 체크박스 미변경
            has_new_commits=False,
            sync_had_activity=True,  # skipped > 0
        )
        assert no_progress is False
        assert failure_recorded is False

    def test_no_progress_no_sync_is_failure(self):
        """Right: sync 없음 + 체크박스 미변경 + 커밋 없음 → no_progress=True, 실패 기록"""
        no_progress, failure_recorded = self._simulate_phase2_progress(
            after_undone=3,
            before_undone=3,  # 체크박스 미변경
            has_new_commits=False,
            sync_had_activity=False,  # 아무 활동 없음
        )
        assert no_progress is True
        assert failure_recorded is True

    def test_checkbox_progress_is_always_ok(self):
        """Cross: 체크박스 진전 있으면 sync 여부 무관하게 no_progress=False"""
        no_progress, failure_recorded = self._simulate_phase2_progress(
            after_undone=2,
            before_undone=3,  # 체크박스 1개 감소
            has_new_commits=False,
            sync_had_activity=False,
        )
        assert no_progress is False
        assert failure_recorded is False

    def test_new_commits_is_always_ok(self):
        """Cross: 새 git 커밋 있으면 체크박스/sync 없어도 no_progress=False"""
        no_progress, failure_recorded = self._simulate_phase2_progress(
            after_undone=3,
            before_undone=3,  # 체크박스 미변경
            has_new_commits=True,
            sync_had_activity=False,
        )
        assert no_progress is False
        assert failure_recorded is False
