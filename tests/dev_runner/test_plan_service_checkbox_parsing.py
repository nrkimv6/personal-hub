"""체크박스 파싱 패턴 개선 테스트 (멀티레벨 지원, total==0 아카이브)

대상:
- get_plan_progress() — "1. - [x]", "  - [x]" 형식 파싱
- _can_done() — total==0 시 True
- verify_completion() — total==0 시 can_done=True

RIGHT-BICEP: R(정상), B(경계), E(에러)
"""

import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def svc(tmp_path, dev_runner_config_isolation):
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")
    return PlanService()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ─── get_plan_progress() ───────────────────────────────────────

class TestCheckboxParsing:

    def test_parse_multilevel_checkbox_done(self, svc, tmp_path):
        """R: '1. - [x]' 형식 파싱 → total=1, done=1"""
        f = _write(tmp_path, "plan.md", "# Plan\n\n1. - [x] **작업 제목**\n")
        result = svc.get_plan_progress(f)
        assert result.total == 1
        assert result.done == 1
        assert result.percent == 100

    def test_parse_multilevel_checkbox_pending(self, svc, tmp_path):
        """R: '1. - [ ]' 형식 파싱 → total=1, done=0"""
        f = _write(tmp_path, "plan.md", "# Plan\n\n1. - [ ] **미완료 작업**\n")
        result = svc.get_plan_progress(f)
        assert result.total == 1
        assert result.done == 0
        assert result.percent == 0

    def test_parse_indented_sub_checkbox(self, svc, tmp_path):
        """R: '   - [x]' 들여쓰기 형식 파싱"""
        f = _write(tmp_path, "plan.md", "# Plan\n\n1. - [x] 상위\n   - [x] 하위\n")
        result = svc.get_plan_progress(f)
        assert result.total == 2
        assert result.done == 2

    def test_parse_mixed_format(self, svc, tmp_path):
        """R: '- [x]' + '1. - [x]' 혼합 → 정확한 카운트"""
        content = "# Plan\n\n- [x] 항목A\n1. - [x] 항목B\n   - [ ] 항목C\n"
        f = _write(tmp_path, "plan.md", content)
        result = svc.get_plan_progress(f)
        assert result.total == 3
        assert result.done == 2

    def test_parse_no_checkbox(self, svc, tmp_path):
        """B: 체크박스 없는 문서 → total=0, done=0"""
        f = _write(tmp_path, "plan.md", "# 분석 문서\n\n내용만 있고 체크박스 없음.\n")
        result = svc.get_plan_progress(f)
        assert result.total == 0
        assert result.done == 0

    def test_checkbox_in_code_block_ignored(self, svc, tmp_path):
        """E: 코드블록 내 체크박스는 파싱에서 제외"""
        content = "# Plan\n\n```\n- [ ] 코드블록 내용\n```\n\n- [x] 실제 항목\n"
        f = _write(tmp_path, "plan.md", content)
        result = svc.get_plan_progress(f)
        assert result.total == 1
        assert result.done == 1


# ─── _can_done() ───────────────────────────────────────────────

class TestCanDone:

    def _make_plan_response(self, path: str, total: int, done: int, status: str = "unknown"):
        from app.modules.dev_runner.schemas import PlanFileResponse, PlanProgressResponse
        percent = int(done / total * 100) if total > 0 else 0
        return PlanFileResponse(
            path=path,
            filename=Path(path).name,
            status=status,
            progress=PlanProgressResponse(done=done, total=total, percent=percent),
            source="test",
            ignored=False,
            path_type="plan",
        )

    def test_can_done_with_zero_total(self, svc):
        """R: total=0 plan → _can_done()=True (체크박스 없는 문서 아카이브 허용)"""
        plan = self._make_plan_response("/project/docs/plan/analysis.md", total=0, done=0)
        assert svc._can_done(plan) is True

    def test_can_done_all_checked(self, svc):
        """R: 모든 체크박스 완료 → True"""
        plan = self._make_plan_response("/project/docs/plan/feat.md", total=3, done=3)
        assert svc._can_done(plan) is True

    def test_can_done_partial(self, svc):
        """B: 일부 미완료 → False"""
        plan = self._make_plan_response("/project/docs/plan/feat.md", total=3, done=2)
        assert svc._can_done(plan) is False

    def test_can_done_archived_path_excluded(self, svc):
        """E: archive 경로 파일은 total=0이어도 False"""
        plan = self._make_plan_response("/project/docs/archive/old.md", total=0, done=0)
        assert svc._can_done(plan) is False

    def test_can_done_done_status(self, svc):
        """R: 상태가 '구현완료'이면 total>0 미완료여도 True"""
        plan = self._make_plan_response("/project/docs/plan/feat.md", total=3, done=1, status="구현완료")
        assert svc._can_done(plan) is True


# ─── verify_completion() ───────────────────────────────────────

class TestVerifyCompletion:

    def test_verify_no_checkbox_can_done_true(self, svc, tmp_path):
        """R: 체크박스 없는 문서 → can_done=True, percent=100"""
        f = _write(tmp_path, "analysis.md", "# 분석 보고서\n\n체크박스 없는 일반 문서.\n")
        result = svc.verify_completion(f)
        assert result.can_done is True
        assert result.percent == 100.0
        assert result.total == 0

    def test_verify_archive_path_can_done_false(self, svc, tmp_path):
        """E: archive 경로 → can_done=False"""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        f = _write(archive_dir, "old.md", "# 아카이브 문서\n")
        result = svc.verify_completion(f)
        assert result.can_done is False

    def test_verify_all_checked_can_done_true(self, svc, tmp_path):
        """R: 모든 체크박스 완료 + 파일 존재 → can_done=True"""
        # 파일 경로 참조 없는 순수 체크박스 문서
        content = "# Plan\n\n## Phase 1\n\n- [x] 작업1\n- [x] 작업2\n"
        f = _write(tmp_path, "feat.md", content)
        result = svc.verify_completion(f)
        assert result.can_done is True
