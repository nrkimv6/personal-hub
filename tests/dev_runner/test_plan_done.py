"""PlanService done 처리 유닛테스트 - RIGHT-BICEP 원칙 적용

대상 소스: app/modules/dev_runner/services/plan_service.py
- _resolve_project_dir
- _remove_code_blocks
- _extract_plan_title
- _update_plan_headers
- _archive_plan
- _update_todo_done
- _archive_done_if_needed
- run_done (통합)
"""

import asyncio
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.dev_runner.services.plan_service import PlanService
from app.models.plan_record import PlanRecord, PlanEvent


# ========== Fixtures ==========

@pytest.fixture
def svc(dev_runner_config_isolation, test_db_session):
    """PlanService 인스턴스 — test_db_session으로 SessionLocal 글로벌 패치 활성화"""
    return PlanService()


@pytest.fixture
def today():
    return date.today().isoformat()


# ========== _resolve_project_dir ==========

class TestResolveProjectDir:
    """RIGHT: 올바른 경로 추론"""

    def test_docs_plan_pattern(self, tmp_path):
        """docs/plan 패턴 → 2단계 위가 project_root"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "2026-01-01-test.md"
        plan_file.touch()

        result = PlanService._resolve_project_dir(str(plan_file))
        assert result == tmp_path.resolve()

    def test_nested_docs_plan(self, tmp_path):
        """중첩 경로에서도 docs/plan 패턴 감지"""
        project = tmp_path / "my-project"
        plan_dir = project / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "plan.md"
        plan_file.touch()

        result = PlanService._resolve_project_dir(str(plan_file))
        assert result == project.resolve()

    def test_fallback_3_levels_up(self, tmp_path):
        """docs/plan 패턴 없는 경우 파일 기준 상위 3단계 fallback"""
        deep_dir = tmp_path / "a" / "b" / "c"
        deep_dir.mkdir(parents=True)
        plan_file = deep_dir / "plan.md"
        plan_file.touch()

        result = PlanService._resolve_project_dir(str(plan_file))
        # file → c → b → a: parent.parent.parent = tmp_path/a
        assert result == (tmp_path / "a").resolve()


# ========== _remove_code_blocks ==========

class TestRemoveCodeBlocks:
    """RIGHT: 코드블록 제거 후 체크박스 오인식 방지"""

    def test_fenced_code_block_removed(self):
        content = "text\n```\n- [ ] 가짜 체크박스\n```\nend"
        result = PlanService._remove_code_blocks(content)
        assert "- [ ] 가짜 체크박스" not in result

    def test_inline_code_removed(self):
        content = "use `- [ ] inline` here"
        result = PlanService._remove_code_blocks(content)
        assert "- [ ] inline" not in result

    def test_real_checkbox_preserved(self):
        content = "- [ ] 진짜 체크박스\n- [x] 완료 항목"
        result = PlanService._remove_code_blocks(content)
        assert "- [ ] 진짜 체크박스" in result
        assert "- [x] 완료 항목" in result

    def test_multiline_fenced_block(self):
        content = "```python\ndef foo():\n    pass\n```"
        result = PlanService._remove_code_blocks(content)
        assert "def foo" not in result


# ========== _extract_plan_title ==========

class TestExtractPlanTitle:
    """RIGHT: 제목 추출"""

    def test_first_h1_extracted(self):
        content = "# 나의 플랜 제목\n\n내용"
        assert PlanService._extract_plan_title(content) == "나의 플랜 제목"

    def test_no_h1_returns_unknown(self):
        content = "## 부제목\n내용"
        assert PlanService._extract_plan_title(content) == "Unknown Plan"

    def test_title_with_extra_spaces(self):
        content = "#   제목   \n내용"
        assert PlanService._extract_plan_title(content) == "제목"


# ========== _update_plan_headers ==========

class TestUpdatePlanHeaders:
    """RIGHT: 헤더/푸터/체크박스 치환"""

    def test_status_updated_to_done(self):
        content = "> 상태: 구현중\n내용"
        result = PlanService._update_plan_headers(content, 5)
        assert "> 상태: 구현완료" in result

    def test_progress_updated_to_100(self):
        content = "> 진행률: 3/5 (60%)\n내용"
        result = PlanService._update_plan_headers(content, 5)
        assert "> 진행률: 5/5 (100%)" in result

    def test_arrow_id_converted_to_x(self):
        content = "1. [→TODO] 항목 1\n2. [→P1] 항목 2"
        result = PlanService._update_plan_headers(content, 2)
        assert "[→TODO]" not in result
        assert "[→P1]" not in result
        assert result.count("[x]") == 2

    def test_footer_updated(self):
        content = "내용\n*상태: 구현중 | 진행률: 3/5 (60%)*"
        result = PlanService._update_plan_headers(content, 5)
        assert "*상태: 구현완료 | 진행률: 5/5 (100%)*" in result

    def test_zero_total_handled(self):
        content = "> 상태: 초안\n> 진행률: 0/0 (0%)"
        result = PlanService._update_plan_headers(content, 0)
        assert "> 상태: 구현완료" in result
        assert "> 진행률: 0/0 (100%)" in result


# ========== _archive_plan ==========

class TestArchivePlan:
    """RIGHT: 아카이브 이동 + 원본 삭제"""

    @pytest.mark.asyncio
    async def test_archive_file_created(self, tmp_path, today, svc):
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "2026-01-01-test.md"
        plan_file.write_text("# 테스트\n> 상태: 구현완료\n", encoding="utf-8")

        archive_path, _ = await svc._archive_plan(str(plan_file), plan_file.read_text(encoding="utf-8"))

        assert archive_path.exists()
        assert archive_path.parent.name == "archive"

    @pytest.mark.asyncio
    async def test_original_deleted(self, tmp_path, svc):
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "2026-01-01-test.md"
        plan_file.write_text("# 테스트\n", encoding="utf-8")

        await svc._archive_plan(str(plan_file), plan_file.read_text(encoding="utf-8"))

        assert not plan_file.exists()

    @pytest.mark.asyncio
    async def test_completion_date_inserted(self, tmp_path, today, svc):
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text("# 테스트\n> 상태: 구현완료\n", encoding="utf-8")

        archive_path, _ = await svc._archive_plan(str(plan_file), plan_file.read_text(encoding="utf-8"))

        archived_content = archive_path.read_text(encoding="utf-8")
        assert f"> 완료일: {today}" in archived_content

    @pytest.mark.asyncio
    async def test_archive_dir_auto_created(self, tmp_path, svc):
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text("# 테스트\n", encoding="utf-8")

        await svc._archive_plan(str(plan_file), plan_file.read_text(encoding="utf-8"))

        assert (tmp_path / "docs" / "archive").exists()


# ========== _update_todo_done ==========

class TestUpdateTodoDone:
    """RIGHT: TODO.md 제거 + DONE.md 추가"""

    def test_todo_item_removed(self, tmp_path):
        todo_path = tmp_path / "TODO.md"
        todo_path.write_text(
            "# TODO\n\n- [ ] 내 플랜 제목 (from: plan/xxx)\n- [ ] 다른 항목\n",
            encoding="utf-8"
        )

        PlanService._update_todo_done(tmp_path, "내 플랜 제목")

        content = todo_path.read_text(encoding="utf-8")
        assert "내 플랜 제목" not in content
        assert "다른 항목" in content

    def test_done_entry_added(self, tmp_path, today):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        PlanService._update_todo_done(tmp_path, "테스트 플랜")

        done_path = tmp_path / "docs" / "DONE.md"
        assert done_path.exists()
        content = done_path.read_text(encoding="utf-8")
        assert f"- [x] {today}: 테스트 플랜" in content

    def test_done_md_created_if_not_exists(self, tmp_path):
        PlanService._update_todo_done(tmp_path, "새 플랜")
        done_path = tmp_path / "docs" / "DONE.md"
        assert done_path.exists()

    def test_done_entry_prepended(self, tmp_path, today):
        done_path = tmp_path / "docs" / "DONE.md"
        done_path.parent.mkdir(parents=True)
        done_path.write_text("# DONE (최근 20개)\n\n- [x] 2026-01-01: 이전 항목\n", encoding="utf-8")

        PlanService._update_todo_done(tmp_path, "새 플랜")

        lines = done_path.read_text(encoding="utf-8").splitlines()
        # 헤더 다음이 새 항목
        new_idx = next(i for i, l in enumerate(lines) if "새 플랜" in l)
        old_idx = next(i for i, l in enumerate(lines) if "이전 항목" in l)
        assert new_idx < old_idx


# ========== _archive_done_if_needed ==========

class TestArchiveDoneIfNeeded:
    """RIGHT: 5개 이하 noop, 6개 이상 아카이브"""

    def _make_done_md(self, done_path: Path, count: int):
        items = "".join(f"- [x] 2026-01-{i:02d}: 항목{i}\n" for i in range(1, count + 1))
        done_path.parent.mkdir(parents=True, exist_ok=True)
        done_path.write_text(f"# DONE\n\n{items}", encoding="utf-8")

    def test_5_items_no_archive(self, tmp_path):
        done_path = tmp_path / "docs" / "DONE.md"
        self._make_done_md(done_path, 5)

        PlanService._archive_done_if_needed(done_path)

        history_dir = tmp_path / "docs" / "history"
        assert not history_dir.exists()

    def test_6_items_creates_archive(self, tmp_path):
        done_path = tmp_path / "docs" / "DONE.md"
        self._make_done_md(done_path, 6)

        PlanService._archive_done_if_needed(done_path)

        history_dir = tmp_path / "docs" / "history"
        assert history_dir.exists()
        archives = list(history_dir.glob("DONE-*.md"))
        assert len(archives) == 1

    def test_done_md_keeps_only_5(self, tmp_path):
        done_path = tmp_path / "docs" / "DONE.md"
        self._make_done_md(done_path, 8)

        PlanService._archive_done_if_needed(done_path)

        content = done_path.read_text(encoding="utf-8")
        items = [l for l in content.splitlines() if l.startswith("- [x]")]
        assert len(items) == 5

    def test_nonexistent_done_md_noop(self, tmp_path):
        done_path = tmp_path / "docs" / "DONE.md"
        # no exception, no file creation
        PlanService._archive_done_if_needed(done_path)
        assert not (tmp_path / "docs" / "history").exists()


# ========== run_done 통합 TC ==========

class TestRunDone:
    """통합: 전체 흐름 + 실패 케이스"""

    @pytest.fixture
    def plan_setup(self, tmp_path):
        """plan 파일 + 프로젝트 구조 설정"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (tmp_path / "docs").mkdir(exist_ok=True)

        plan_content = (
            "# 테스트 플랜\n\n"
            "> 상태: 구현중\n"
            "> 진행률: 2/2 (100%)\n\n"
            "1. [x] 항목1\n"
            "2. [x] 항목2\n\n"
            "*상태: 구현중 | 진행률: 2/2 (100%)*\n"
        )
        plan_file = plan_dir / "2026-01-01-test-plan.md"
        plan_file.write_text(plan_content, encoding="utf-8")
        return plan_file, tmp_path

    @pytest.mark.asyncio
    async def test_run_done_success_flow(self, plan_setup, svc):
        plan_file, project_dir = plan_setup

        with patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")):
            result = await svc.run_done(str(plan_file))

        assert result["success"] is True
        assert not plan_file.exists()  # 원본 삭제
        archive_dir = project_dir / "docs" / "archive"
        assert archive_dir.exists()
        archives = list(archive_dir.glob("*.md"))
        assert len(archives) == 1

    @pytest.mark.asyncio
    async def test_run_done_file_not_found(self, svc):
        result = await svc.run_done("/nonexistent/path/plan.md")
        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_run_done_done_md_updated(self, plan_setup, svc, today):
        plan_file, project_dir = plan_setup

        with patch.object(svc, "_git_commit", new=AsyncMock(return_value="")):
            await svc.run_done(str(plan_file))

        done_path = project_dir / "docs" / "DONE.md"
        assert done_path.exists()
        content = done_path.read_text(encoding="utf-8")
        assert "테스트 플랜" in content
        assert today in content


# ========== run_done DB 연동 Cross-check ==========

class TestRunDoneDBIntegration:
    """Cross-check: run_done 완료 후 plan_records DB에 기록되는지 검증"""

    @pytest.fixture
    def plan_setup_with_db(self, tmp_path):
        """plan 파일 + 프로젝트 구조 + in-memory DB 설정"""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models.plan_record import PlanRecord, PlanEvent

        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (tmp_path / "docs").mkdir(exist_ok=True)

        plan_content = (
            "# DB연동 테스트 플랜\n\n"
            "> 상태: 구현중\n"
            "> 진행률: 2/2 (100%)\n\n"
            "1. [x] 항목1\n"
            "2. [x] 항목2\n\n"
            "*상태: 구현중 | 진행률: 2/2 (100%)*\n"
        )
        plan_file = plan_dir / "2026-03-01-db-test.md"
        plan_file.write_text(plan_content, encoding="utf-8")

        # in-memory DB
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        PlanRecord.__table__.create(bind=engine, checkfirst=True)
        PlanEvent.__table__.create(bind=engine, checkfirst=True)
        TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        return plan_file, tmp_path, TestSession

    @pytest.mark.asyncio
    async def test_run_done_creates_plan_record(self, plan_setup_with_db, dev_runner_config_isolation):
        """done 완료 후 plan_records에 레코드 존재 (Cross-check)"""
        plan_file, project_dir, TestSession = plan_setup_with_db
        svc = PlanService()

        # SessionLocal을 in-memory DB로 mock
        with patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
             patch("app.database.SessionLocal", TestSession):
            result = await svc.run_done(str(plan_file))

        assert result["success"] is True

        # DB에 레코드 존재 확인
        with TestSession() as db:
            records = db.query(PlanRecord).all()
            assert len(records) == 1
            record = records[0]
            assert record.archived_at is not None
            assert "archive" in record.file_path

    @pytest.mark.asyncio
    async def test_run_done_archived_event(self, plan_setup_with_db, dev_runner_config_isolation):
        """done 완료 후 plan_events에 archived 이벤트 존재 (Cross-check)"""
        plan_file, project_dir, TestSession = plan_setup_with_db
        svc = PlanService()

        with patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
             patch("app.database.SessionLocal", TestSession):
            await svc.run_done(str(plan_file))

        with TestSession() as db:
            events = db.query(PlanEvent).all()
            archived_events = [e for e in events if e.event_type == "archived"]
            assert len(archived_events) == 1
            assert "archive" in archived_events[0].detail.get("archive_path", "")
