"""Phase 4: Error/Boundary 테스트 - 크로스커팅 경계값/에러 케이스

대상: PlanService (인코딩, 대용량), DBService (limit/offset), RunRequest (유효성), routes (base64)
"""

import base64
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from app.modules.auto_next.schemas import RunRequest, PlanProgressResponse


# ========== UTF-8 인코딩 에러 ==========

class TestUTF8Encoding:
    """Windows cp949 plan 파일 읽기 테스트"""

    def test_cp949_plan_file_no_crash(self, tmp_path, auto_next_config_isolation):
        """cp949 인코딩 파일 → errors='ignore'로 크래시 없이 처리"""
        from app.modules.auto_next.services.plan_service import PlanService

        plan_file = tmp_path / "plan" / "test.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        # cp949 인코딩으로 한글 내용 작성
        content = "> 상태: 구현중\n- [x] 한글 체크\n- [ ] 미완료 항목\n"
        plan_file.write_bytes(content.encode("cp949"))

        cfg = auto_next_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path
        cfg.PLAN_DIR = Path("plan")

        svc = PlanService()
        progress = svc.get_plan_progress(plan_file)
        # cp949 한글이 깨져도 체크박스 패턴은 ASCII이므로 인식됨
        assert progress.total == 2
        assert progress.done == 1

    def test_mixed_encoding_plan(self, tmp_path, auto_next_config_isolation):
        """혼합 인코딩(UTF-8 BOM + cp949) → 크래시 없음"""
        from app.modules.auto_next.services.plan_service import PlanService

        plan_file = tmp_path / "plan" / "mixed.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 BOM + 바이너리 섞인 내용
        raw = b"\xef\xbb\xbf> \xc0\xfc\xc5\xc2: \xb1\xb8\xc7\xf6\xc1\xdf\n- [x] done\n- [ ] todo\n"
        plan_file.write_bytes(raw)

        svc = PlanService()
        progress = svc.get_plan_progress(plan_file)
        assert progress.total == 2


# ========== 대용량 plan 파일 ==========

class TestLargePlanFile:

    def test_large_plan_many_checkboxes(self, tmp_path, auto_next_config_isolation):
        """수백 개 체크박스 plan → 정상 파싱"""
        from app.modules.auto_next.services.plan_service import PlanService

        plan_file = tmp_path / "plan" / "large.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)

        lines = ["> 상태: 구현중\n", "## Phase 1: Large\n"]
        for i in range(500):
            checked = "x" if i % 3 == 0 else " "
            lines.append(f"- [{checked}] Task {i}\n")

        plan_file.write_text("".join(lines), encoding="utf-8")

        svc = PlanService()
        progress = svc.get_plan_progress(plan_file)
        assert progress.total == 500
        assert progress.done == 167  # 0,3,6,...,498 → 500/3 = 166.67 → ceil = 167
        assert 0 < progress.percent < 100

    def test_large_plan_parse_items(self, tmp_path, auto_next_config_isolation):
        """대용량 parse_plan_items → Phase 구조 정상"""
        from app.modules.auto_next.services.plan_service import PlanService

        plan_file = tmp_path / "plan" / "large2.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)

        lines = ["> 상태: 구현중\n"]
        for phase in range(5):
            lines.append(f"## Phase {phase + 1}: Section {phase}\n")
            for i in range(50):
                lines.append(f"{i + 1}. [ ] Item {phase}-{i}\n")

        plan_file.write_text("".join(lines), encoding="utf-8")

        svc = PlanService()
        detail = svc.parse_plan_items(plan_file)
        assert len(detail.phases) == 5
        assert detail.phases[0].total_count == 50


# ========== DBService limit/offset 경계값 ==========

class TestDBServiceBoundary:

    @pytest.fixture
    def db_svc(self, tmp_path, auto_next_config_isolation):
        """격리된 DBService"""
        import sqlite3
        from app.modules.auto_next.services.db_service import DBService

        cfg = auto_next_config_isolation
        db_path = cfg.AUTO_NEXT_DB_PATH
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, type TEXT, source_path TEXT, text TEXT,
            priority INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
            created_at TEXT, started_at TEXT, finished_at TEXT,
            duration_seconds REAL, output_tokens INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0,
            cache_create_tokens INTEGER DEFAULT 0,
            error_message TEXT, model_used TEXT
        )""")
        # 10개 레코드 삽입
        for i in range(10):
            conn.execute(
                "INSERT INTO tasks (id, type, source_path, text, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f"t{i}", "implement", "proj/plan.md", f"Task {i}", "success", "2026-02-18T10:00:00")
            )
        conn.commit()
        conn.close()
        return DBService()

    def test_limit_zero(self, db_svc):
        """limit=0 → 빈 리스트 (또는 전체)"""
        result = db_svc.get_tasks(limit=0)
        assert isinstance(result.tasks, list)

    def test_limit_one(self, db_svc):
        """limit=1 → 정확히 1개"""
        result = db_svc.get_tasks(limit=1)
        assert len(result.tasks) == 1

    def test_limit_large(self, db_svc):
        """limit=200 (전체보다 큼) → 전체 반환"""
        result = db_svc.get_tasks(limit=200)
        assert len(result.tasks) == 10
        assert result.total == 10

    def test_offset_beyond_total(self, db_svc):
        """offset > total → 빈 리스트"""
        result = db_svc.get_tasks(limit=10, offset=100)
        assert len(result.tasks) == 0


# ========== RunRequest 유효성 ==========

class TestRunRequestValidation:

    def test_max_cycles_zero_is_valid(self):
        """max_cycles=0 → 유효 (무제한)"""
        req = RunRequest(max_cycles=0)
        assert req.max_cycles == 0

    def test_max_cycles_negative_is_valid_schema(self):
        """음수 max_cycles → Pydantic은 허용 (비즈니스 로직에서 처리)"""
        req = RunRequest(max_cycles=-1)
        assert req.max_cycles == -1

    def test_max_tokens_zero(self):
        """max_tokens=0 → 유효"""
        req = RunRequest(max_tokens=0)
        assert req.max_tokens == 0

    def test_max_tokens_negative(self):
        """음수 max_tokens → Pydantic 허용"""
        req = RunRequest(max_tokens=-100)
        assert req.max_tokens == -100

    def test_all_defaults(self):
        """기본값 전부 확인"""
        req = RunRequest()
        assert req.plan_file is None
        assert req.max_cycles == 0
        assert req.max_tokens == 0
        assert req.until is None
        assert req.dry_run is False
        assert req.skip_plan is False
        assert req.parallel is False
        assert req.projects is None


# ========== Base64 인코딩/디코딩 ==========

class TestBase64Decoding:

    def test_standard_base64_path(self):
        """정상 base64 경로 디코딩"""
        from app.modules.auto_next.routes.plans import _decode_path

        path = r"D:\work\project\tools\monitor-page\docs\plan\test.md"
        encoded = base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii")
        assert _decode_path(encoded) == path

    def test_base64_no_padding(self):
        """패딩 없는 base64 → 자동 복원"""
        from app.modules.auto_next.routes.plans import _decode_path

        path = "common/docs/plan/test.md"
        encoded = base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii")
        # 패딩 제거
        stripped = encoded.rstrip("=")
        assert _decode_path(stripped) == path

    def test_base64_with_special_chars(self):
        """특수문자 포함 경로"""
        from app.modules.auto_next.routes.plans import _decode_path

        path = r"D:\work\project\2026-02-18_한글-plan.md"
        encoded = base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii")
        assert _decode_path(encoded) == path

    def test_invalid_base64_raises(self):
        """유효하지 않은 base64 → 예외"""
        from app.modules.auto_next.routes.plans import _decode_path

        with pytest.raises(Exception):
            _decode_path("!!!not-valid-base64!!!")

    def test_empty_string_decodes(self):
        """빈 문자열 → 빈 결과"""
        from app.modules.auto_next.routes.plans import _decode_path

        result = _decode_path("")
        assert result == ""
