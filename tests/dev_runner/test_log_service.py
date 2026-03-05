"""tests/dev_runner/test_log_service.py — LogService.tail_log_file Redis list fallback 테스트"""
from unittest.mock import MagicMock, patch


def _make_log_service():
    """LogService 인스턴스 생성 (Redis mock)."""
    from app.modules.dev_runner.services.log_service import LogService

    svc = LogService.__new__(LogService)
    svc.redis_client = MagicMock()
    svc.async_redis = MagicMock()
    return svc


class TestTailLogFileRedisListFallback:
    """로그 파일 없을 때 Redis list fallback 검증"""

    def test_tail_log_file_redis_list_fallback_R(self):
        """R(Right): 로그 파일 없음 + Redis list에 3줄 → lines 길이 3"""
        svc = _make_log_service()
        # _find_current_log → None (로그 파일 없음)
        svc._find_current_log = MagicMock(return_value=None)
        # Redis list에 3줄 존재
        svc.redis_client.lrange.return_value = [
            "[MERGE] lock 획득",
            "[MERGE] merge 시작",
            "[MERGE] merge 완료",
        ]

        result = svc.tail_log_file("dm-test123", n_lines=100)

        assert len(result.lines) == 3
        assert result.total_lines == 3
        assert "[MERGE]" in result.lines[0]

    def test_tail_log_file_prefers_file_over_list_B(self, tmp_path):
        """B(Boundary): 로그 파일 존재 + Redis list 존재 → 파일 내용 우선 반환 (회귀)"""
        svc = _make_log_service()

        # 로그 파일 생성
        log_file = tmp_path / "test.log"
        log_file.write_text("file line 1\nfile line 2\n", encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        # Redis list에도 데이터 존재
        svc.redis_client.lrange.return_value = ["[MERGE] redis line"]

        result = svc.tail_log_file("test-runner", n_lines=100)

        assert len(result.lines) == 2
        assert result.lines[0] == "file line 1"
        # Redis lrange가 호출되지 않아야 함 (파일 우선)
        svc.redis_client.lrange.assert_not_called()

    def test_tail_log_file_empty_redis_list_returns_empty_B(self):
        """B(Boundary): 로그 파일 없음 + Redis list 빈 배열 → 빈 응답"""
        svc = _make_log_service()
        svc._find_current_log = MagicMock(return_value=None)
        svc.redis_client.lrange.return_value = []

        result = svc.tail_log_file("dm-empty", n_lines=100)

        assert result.lines == []
        assert result.total_lines == 0


class TestFindCurrentLog:
    """_find_current_log() stream_log_path 우선순위 + 유효성 검증 테스트"""

    def test_find_current_log_right_prefers_logfile_over_empty_stream(self, tmp_path):
        """R: stream_log_path 200B 이하(START 마커만) + log_file_path 정상 → log_file_path 반환"""
        svc = _make_log_service()

        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[START] " + b"x" * 100)  # 108B — 200B 이하
        log_file = tmp_path / "log.log"
        log_file.write_text("[20:00:00] [INFO] 실제 로그\n" * 10, encoding="utf-8")

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == log_file

    def test_find_current_log_right_returns_stream_when_valid(self, tmp_path):
        """R: stream_log_path 1KB 이상 → stream_log_path 반환 (기존 동작 유지)"""
        svc = _make_log_service()

        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[20:00:00] [INFO] log line\n" * 50)  # ~1.3KB
        log_file = tmp_path / "log.log"
        log_file.write_text("다른 로그\n", encoding="utf-8")

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == stream_file

    def test_find_current_log_boundary_empty_stream_no_logfile(self, tmp_path):
        """B: stream_log_path 200B 이하 + log_file_path 없음 → None 반환"""
        svc = _make_log_service()

        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[START] marker only")  # 소형

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(tmp_path / "nonexistent.log") if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result is None


class TestTailLogFileE2E:
    """tail_log_file E2E 흐름 — stream_log_path 소형일 때 log_file_path 내용 반환"""

    def test_tail_log_file_e2e_prefers_logfile_when_stream_empty(self, tmp_path):
        """T3 E2E: stream_log 200B 이하 + log_file 정상 → tail_log_file()이 log_file 내용 반환"""
        svc = _make_log_service()

        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[2026-03-05T20:18:13.479897] START | log_path=...\n")  # 50B

        log_file = tmp_path / "log.log"
        log_file.write_text(
            "[20:18:13] [PLAN-RUNNER] [INFO] Plan-Runner 시작\n"
            "[20:18:13] [PLAN-RUNNER] [WARN] Plan이 스킵 가능\n"
            "[20:18:13] [PLAN-RUNNER] [DONE] Plan-Runner 종료\n",
            encoding="utf-8",
        )

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc.tail_log_file("runner-abc123", n_lines=100)

        assert len(result.lines) == 3
        assert "Plan-Runner 시작" in result.lines[0]
        assert "Plan-Runner 종료" in result.lines[2]
