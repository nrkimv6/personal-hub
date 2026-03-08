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
