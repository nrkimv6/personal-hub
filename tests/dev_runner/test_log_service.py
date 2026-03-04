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
