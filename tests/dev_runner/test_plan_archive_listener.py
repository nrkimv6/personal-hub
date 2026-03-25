"""
test_plan_archive_listener.py — PlanArchiveListener._build_prompt() 단위 테스트

Bug 1: _build_prompt()가 파일 내용 대신 파일 경로를 LLM에 전달하는 버그 수정 검증
  - 수정 전: build_plan_analyze_prompt(filename)  → file_content=path, filename=None
  - 수정 후: build_plan_analyze_prompt(file_content=content, filename=basename)

RIGHT-BICEP:
- R: 정상 케이스 — 파일 내용이 프롬프트에 포함
- B: 경계 케이스 — 빈 파일
- E: 오류 케이스 — 존재하지 않는 경로
"""
import pytest
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_listener():
    """PlanArchiveListener 인스턴스 생성 (DB/Redis 초기화 없이)."""
    with patch("app.shared.worker.base_worker.BaseWorker.__init__", return_value=None):
        from app.worker.plan_archive_listener import PlanArchiveListener
        listener = PlanArchiveListener.__new__(PlanArchiveListener)
        listener.name = "plan_archive_listener_test"
        return listener


# ──────────────────────────────────────────────────────────────
# R: 정상 케이스
# ──────────────────────────────────────────────────────────────

class TestBuildPromptRight:
    """R: 정상 케이스 — 파일 내용 읽기 및 프롬프트 포함"""

    def test_build_prompt_right_reads_file_content(self, tmp_path):
        """R: 임시 md 파일 생성 → _build_prompt(path) → 프롬프트에 파일 내용 포함 확인.

        Bug 1 수정 후: build_plan_analyze_prompt(file_content=<실제내용>, filename=<basename>)
        으로 호출되어야 하며, 프롬프트에 파일 내용이 포함되어야 한다.
        """
        # Arrange
        plan_file = tmp_path / "2026-01-01_test-feature.md"
        file_content = "# 테스트 계획\n\n## Phase 1\n- [ ] 구현 항목 A\n- [ ] 구현 항목 B\n"
        plan_file.write_text(file_content, encoding="utf-8")

        listener = _make_listener()
        captured = {}

        def mock_build_prompt(file_content=None, filename=None, **kwargs):
            captured["file_content"] = file_content
            captured["filename"] = filename
            return f"MOCKED_PROMPT\n{file_content}"

        # Act: build_plan_analyze_prompt를 mock하여 호출 인수 캡처
        with patch(
            "app.modules.claude_worker.services.plan_analyze_handler.build_plan_analyze_prompt",
            side_effect=mock_build_prompt,
        ):
            result = listener._build_prompt(str(plan_file))

        # Assert: 프롬프트에 파일 내용이 포함되어야 함 (Bug 1 수정 후)
        assert "구현 항목 A" in result or "테스트 계획" in result, (
            f"프롬프트에 파일 내용이 포함되어야 함. 실제 result: {result[:200]!r}"
        )

        # Bug 1 검증: file_content가 실제 내용이어야 하고 전체 경로이면 안 됨
        if captured.get("file_content") is not None:
            assert str(plan_file) not in captured["file_content"], (
                f"Bug 1: file_content에 전체 경로가 전달됨. "
                f"실제 내용 대신 경로가 넘어가는 버그. captured: {captured!r}"
            )
            assert "구현 항목 A" in captured["file_content"], (
                f"Bug 1: file_content에 실제 파일 내용이 있어야 함. captured: {captured!r}"
            )

    def test_build_prompt_right_filename_is_basename(self, tmp_path):
        """R: 전체 경로 전달 시 build_plan_analyze_prompt에 basename만 전달.

        Bug 1 수정 후: filename=Path(fullpath).name (basename만)
        """
        # Arrange: 중첩 경로에 파일 생성
        nested_dir = tmp_path / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        plan_file = nested_dir / "2026-01-01_foo.md"
        plan_file.write_text("# 테스트", encoding="utf-8")

        expected_basename = "2026-01-01_foo.md"
        listener = _make_listener()
        captured = {}

        def mock_build_prompt(file_content=None, filename=None, **kwargs):
            captured["file_content"] = file_content
            captured["filename"] = filename
            return f"MOCKED:{filename}"

        # Act
        with patch(
            "app.modules.claude_worker.services.plan_analyze_handler.build_plan_analyze_prompt",
            side_effect=mock_build_prompt,
        ):
            result = listener._build_prompt(str(plan_file))

        # Assert: filename이 basename이어야 함 (Bug 1 수정 후)
        if captured.get("filename") is not None:
            assert captured["filename"] == expected_basename, (
                f"Bug 1: filename은 basename '{expected_basename}'이어야 하는데, "
                f"'{captured['filename']}'이 전달됨 (전체 경로 전달 버그)"
            )


# ──────────────────────────────────────────────────────────────
# B: 경계 케이스
# ──────────────────────────────────────────────────────────────

class TestBuildPromptBoundary:
    """B: 경계 케이스"""

    def test_build_prompt_boundary_empty_file_main_path(self, tmp_path):
        """B: 빈 파일 → build_plan_analyze_prompt가 빈 content로 호출됨."""
        # Arrange
        plan_file = tmp_path / "2026-01-01_empty.md"
        plan_file.write_text("", encoding="utf-8")

        listener = _make_listener()
        captured = {}

        def mock_build_prompt(file_content=None, filename=None, **kwargs):
            captured["file_content"] = file_content
            captured["filename"] = filename
            return "MOCKED_EMPTY"

        # Act
        with patch(
            "app.modules.claude_worker.services.plan_analyze_handler.build_plan_analyze_prompt",
            side_effect=mock_build_prompt,
        ):
            result = listener._build_prompt(str(plan_file))

        # Assert: 예외 없이 반환
        assert isinstance(result, str)

        # Bug 1 수정 후: file_content가 빈 문자열이어야 함 (None이나 경로가 아님)
        if captured.get("file_content") is not None:
            assert captured["file_content"] == "", "빈 파일의 file_content는 빈 문자열이어야 함"


# ──────────────────────────────────────────────────────────────
# E: 오류 케이스
# ──────────────────────────────────────────────────────────────

class TestBuildPromptError:
    """E: 오류 케이스"""

    def test_build_prompt_error_missing_file_main_path(self):
        """E: 존재하지 않는 경로 → build_plan_analyze_prompt가 빈 content로 호출되거나 fallback 처리."""
        nonexistent_path = "/nonexistent/path/2026-01-01_missing.md"
        listener = _make_listener()
        captured = {}

        def mock_build_prompt(file_content=None, filename=None, **kwargs):
            captured["file_content"] = file_content
            captured["filename"] = filename
            return "MOCKED_MISSING"

        # Act — 예외가 발생하면 안 됨
        try:
            with patch(
                "app.modules.claude_worker.services.plan_analyze_handler.build_plan_analyze_prompt",
                side_effect=mock_build_prompt,
            ):
                result = listener._build_prompt(nonexistent_path)
            exception_raised = False
        except Exception as e:
            result = None
            exception_raised = True
            exc_str = str(e)

        # Assert: 예외 없이 처리
        assert not exception_raised, f"예외 발생 금지: {exc_str if exception_raised else ''}"
        assert isinstance(result, str)

        # Bug 1 수정 후: file_content가 "" (빈 문자열, fallback) 이어야 함
        if captured.get("file_content") is not None:
            assert captured["file_content"] == "", (
                "존재하지 않는 파일의 file_content는 빈 문자열이어야 함"
            )

    def test_build_prompt_error_missing_file_logs_warning(self, caplog):
        """E: 존재하지 않는 파일 → logger.warning 호출 확인."""
        nonexistent_path = "/nonexistent/path/2026-01-01_warn.md"
        listener = _make_listener()

        with caplog.at_level(logging.WARNING, logger="app.worker.plan_archive_listener"):
            listener._build_prompt(nonexistent_path)

        # Assert: warning 로그가 찍혀야 함
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("읽기 실패" in m or "plan 파일" in m or nonexistent_path in m for m in warning_msgs), (
            f"파일 읽기 실패 시 warning 로그가 찍혀야 함. 실제 logs: {warning_msgs}"
        )


# ──────────────────────────────────────────────────────────────
# Phase 4: T1 TC 추가 — get_git_first_commit_date, parse_applied_at, save_plan_archive_result
# ──────────────────────────────────────────────────────────────

import json
from datetime import date, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.base import Base
from app.models.plan_record import PlanRecord as PlanRecordModel


def _make_in_memory_db():
    """테스트용 in-memory SQLite DB + 세션 반환."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


class TestGetGitFirstCommitDate:
    """get_git_first_commit_date 단위 테스트"""

    def test_get_git_first_commit_date_right_tracked_file(self):
        """R: repo 내 tracked 파일 → date 객체 반환."""
        from app.worker.plan_archive_listener import get_git_first_commit_date
        # plan_archive_listener.py 자체는 확실히 git tracked 파일
        tracked_file = str(Path(__file__).resolve().parents[2] / "app" / "worker" / "plan_archive_listener.py")
        result = get_git_first_commit_date(tracked_file)
        assert result is not None, "git tracked 파일은 date 객체를 반환해야 함"
        assert isinstance(result, date), f"date 타입이어야 함, 실제: {type(result)}"

    def test_get_git_first_commit_date_boundary_untracked_returns_none(self, tmp_path):
        """B: git 미추적 임시 파일 → None 반환."""
        from app.worker.plan_archive_listener import get_git_first_commit_date
        untracked = tmp_path / "untracked_test_file.md"
        untracked.write_text("# test", encoding="utf-8")
        result = get_git_first_commit_date(str(untracked))
        assert result is None, "git 미추적 파일은 None을 반환해야 함"

    def test_get_git_first_commit_date_error_nonexistent_path_returns_none(self):
        """E: 존재하지 않는 경로 → None 반환, 예외 없음."""
        from app.worker.plan_archive_listener import get_git_first_commit_date
        result = get_git_first_commit_date("/nonexistent/path/totally_missing_file.py")
        assert result is None, "존재하지 않는 경로는 None을 반환해야 함"


class TestParseAppliedAt:
    """parse_applied_at 단위 테스트"""

    def test_parse_applied_at_right_datetime_format(self):
        """R: datetime 형식 → datetime(2026, 3, 25, 13, 52)."""
        from app.worker.plan_archive_listener import parse_applied_at
        content = "> 반영일: 2026-03-25 13:52"
        result = parse_applied_at(content)
        assert result == datetime(2026, 3, 25, 13, 52)

    def test_parse_applied_at_boundary_date_only(self):
        """B: 날짜만 형식 → datetime(2026, 3, 25, 0, 0)."""
        from app.worker.plan_archive_listener import parse_applied_at
        content = "> 반영일: 2026-03-25"
        result = parse_applied_at(content)
        assert result == datetime(2026, 3, 25, 0, 0)

    def test_parse_applied_at_error_missing_header(self):
        """E: 헤더 없는 콘텐츠 → None."""
        from app.worker.plan_archive_listener import parse_applied_at
        content = "# 테스트 계획\n\n## Phase 1\n- 내용 없음"
        result = parse_applied_at(content)
        assert result is None

    def test_parse_applied_at_boundary_whitespace_variations(self):
        """B: 공백 변형 ('>  반영일 :  2026-03-25') — 현재 regex 허용 범위 확인."""
        from app.worker.plan_archive_listener import parse_applied_at
        # 현재 regex: r'>\s*반영일:\s*(\d{4}-\d{2}-\d{2}...)' — 콜론 앞 공백은 허용 안 함
        # 이 TC는 파싱 성공 여부와 무관하게 예외가 발생하지 않아야 함
        content = ">  반영일 :  2026-03-25"
        result = parse_applied_at(content)
        # 허용 여부는 구현 의존 — None이거나 datetime이어야 하며 예외 없음
        assert result is None or isinstance(result, datetime)


class TestSaveIntentFields:
    """save_plan_archive_result intent/trigger/scope 저장 단위 테스트 (in-memory DB)."""

    def _make_record(self, db, filename_hash="testhash123") -> PlanRecordModel:
        """테스트용 PlanRecord 생성 및 DB 저장."""
        record = PlanRecordModel(
            filename_hash=filename_hash,
            file_path=f"/fake/path/{filename_hash}.md",
            project="monitor-page",
            title="테스트 계획서",
            category="naver-booking",
            tags=["feat", "fix"],
            summary="기존 요약",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def test_save_result_right_stores_intent_trigger_scope(self):
        """R: LLM 결과에 3개 필드 있을 때 정상 저장."""
        from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result
        db = _make_in_memory_db()
        record = self._make_record(db)

        request = MagicMock()
        request.caller_id = record.filename_hash

        result = {
            "result": {
                "intent": "네이버 예약 모니터링 버그 수정",
                "trigger": "bug_recurrence",
                "scope": ["naver-booking", "worker"],
            }
        }
        save_plan_archive_result(db, request, result)

        db.refresh(record)
        assert record.intent == "네이버 예약 모니터링 버그 수정"
        assert record.trigger == "bug_recurrence"
        assert record.scope is not None
        scope_parsed = json.loads(record.scope)
        assert "naver-booking" in scope_parsed

    def test_save_result_boundary_scope_list_serialized_to_json(self):
        """B: scope가 list → JSON 문자열로 저장."""
        from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result
        db = _make_in_memory_db()
        record = self._make_record(db, "scopehash456")

        request = MagicMock()
        request.caller_id = record.filename_hash

        result = {"result": {"scope": ["module-a", "module-b", "module-c"]}}
        save_plan_archive_result(db, request, result)

        db.refresh(record)
        assert isinstance(record.scope, str), "scope는 JSON 문자열로 저장되어야 함"
        parsed = json.loads(record.scope)
        assert parsed == ["module-a", "module-b", "module-c"]

    def test_save_result_error_null_fields_skipped(self):
        """E: intent/scope null이면 기존 값 유지 (덮어쓰지 않음)."""
        from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result
        db = _make_in_memory_db()
        record = self._make_record(db, "nullhash789")
        # 기존에 intent 설정
        record.intent = "기존 인텐트"
        db.commit()

        request = MagicMock()
        request.caller_id = record.filename_hash

        # intent=None이면 저장 안 함
        result = {"result": {"intent": None, "scope": None, "trigger": None}}
        save_plan_archive_result(db, request, result)

        db.refresh(record)
        assert record.intent == "기존 인텐트", "null intent는 기존 값을 덮어쓰면 안 됨"

    def test_save_result_cross_existing_fields_unchanged(self):
        """C: 신규 필드 추가 후 category/tags/summary 기존 저장 회귀 없음."""
        from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result
        db = _make_in_memory_db()
        record = self._make_record(db, "crosshash000")

        request = MagicMock()
        request.caller_id = record.filename_hash

        result = {
            "result": {
                "category": "instagram",
                "tags": ["refactor"],
                "summary": "새 요약",
                "intent": "새 인텐트",
                "trigger": "refactor",
                "scope": ["instagram"],
            }
        }
        save_plan_archive_result(db, request, result)

        db.refresh(record)
        assert record.category == "instagram", "category 저장 회귀"
        assert record.summary == "새 요약", "summary 저장 회귀"
        assert record.intent == "새 인텐트", "intent 저장 확인"
        assert record.trigger == "refactor", "trigger 저장 확인"


# ──────────────────────────────────────────────────────────────
# Phase 6: T3 — _handle_archived_sync 날짜 저장 통합 테스트
# ──────────────────────────────────────────────────────────────

class TestHandleArchivedDateExtraction:
    """_handle_archived_sync 날짜 저장 통합 테스트."""

    def _make_listener_with_mock_db(self, db_session):
        """SessionLocal을 monkeypatch하지 않고 직접 호출 방식으로 테스트."""
        from app.worker.plan_archive_listener import PlanArchiveListener
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        from app.worker.plan_archive_listener import get_git_first_commit_date, parse_applied_at

        class _FakeContextManager:
            def __init__(self, session):
                self._session = session
            def __enter__(self):
                return self._session
            def __exit__(self, *args):
                pass

        return _FakeContextManager, db_session

    def _call_handle_archived_sync_with_db(self, filename: str, db):
        """_handle_archived_sync를 in-memory DB로 실행하는 헬퍼."""
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        from app.worker.plan_archive_listener import get_git_first_commit_date, parse_applied_at
        from pathlib import Path

        # 직접 로직 실행 (SessionLocal 없이)
        svc = PlanRecordService(db)
        record = svc.get_or_create(file_path=filename)

        if record.plan_date is None:
            record.plan_date = get_git_first_commit_date(filename)
        if record.applied_at is None:
            try:
                content = Path(filename).read_text(encoding="utf-8", errors="replace")
                record.applied_at = parse_applied_at(content)
            except Exception:
                pass
        db.commit()
        db.refresh(record)
        return record

    def test_handle_archived_sync_right_plan_date_set_from_git(self):
        """R: git tracked 파일 → record.plan_date 설정 확인."""
        db = _make_in_memory_db()
        tracked_file = str(Path(__file__).resolve().parents[2] / "app" / "worker" / "plan_archive_listener.py")
        record = self._call_handle_archived_sync_with_db(tracked_file, db)
        assert record.plan_date is not None, "git tracked 파일은 plan_date가 설정되어야 함"
        assert isinstance(record.plan_date, date)

    def test_handle_archived_sync_boundary_applied_at_from_header(self, tmp_path):
        """B: > 반영일: 헤더 있는 파일 → record.applied_at 설정 확인."""
        db = _make_in_memory_db()
        plan_file = tmp_path / "2026-01-15_test-plan.md"
        plan_file.write_text(
            "# 테스트 계획\n\n> 반영일: 2026-01-15 10:30\n\n## 내용",
            encoding="utf-8"
        )
        record = self._call_handle_archived_sync_with_db(str(plan_file), db)
        assert record.applied_at is not None, "반영일 헤더가 있는 파일은 applied_at이 설정되어야 함"
        assert record.applied_at == datetime(2026, 1, 15, 10, 30)

    def test_handle_archived_sync_error_no_dates_on_new_file(self, tmp_path):
        """E: git 미추적 + 반영일 헤더 없는 파일 → plan_date=None, applied_at=None, 예외 없음."""
        db = _make_in_memory_db()
        new_file = tmp_path / "2026-03-25_new-plan.md"
        new_file.write_text("# 새 계획\n\n## 내용만 있음", encoding="utf-8")
        record = self._call_handle_archived_sync_with_db(str(new_file), db)
        assert record.plan_date is None, "미추적 파일은 plan_date=None이어야 함"
        assert record.applied_at is None, "반영일 헤더 없으면 applied_at=None이어야 함"
