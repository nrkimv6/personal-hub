"""tests/dev_runner/test_log_service.py — LogService 파일명 패턴 매칭 및 fallback 테스트"""
import hashlib
import re
import redis
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
        """R: stream_log_path 200B 이하 + log_file_path 정상 → stream_file 반환 (200B 기준 제거됨)"""
        svc = _make_log_service()

        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[START] " + b"x" * 100)  # 108B — 200B 이하지만 크기 체크 없음
        log_file = tmp_path / "log.log"
        log_file.write_text("[20:00:00] [INFO] 실제 로그\n" * 10, encoding="utf-8")

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == stream_file

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
        """B: stream_log_path 200B 이하 + log_file_path 없음 → stream_file 반환 (200B 기준 제거)"""
        svc = _make_log_service()

        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[START] marker only")  # 소형이지만 존재하므로 반환

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(tmp_path / "nonexistent.log") if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == stream_file


class TestTailLogFileE2E:
    """tail_log_file E2E 흐름 — stream_log_path 소형이어도 stream 내용 반환 (200B 기준 제거)"""

    def test_tail_log_file_e2e_returns_stream_even_when_small(self, tmp_path):
        """T3 E2E: stream_log 200B 이하 + log_file 정상 → 200B 기준 제거 후 stream 파일 내용 반환"""
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

        # 200B 기준 제거 → stream 파일(1줄) 내용 반환
        assert len(result.lines) == 1
        assert "START" in result.lines[0]


# ─── Phase 1: get_run_history() 정규식 이중 매칭 ──────────────────────────────

def _make_svc_no_redis():
    """LogService 인스턴스 생성 (Redis 완전 mock, active_runners=빈 집합)"""
    from app.modules.dev_runner.services.log_service import LogService
    svc = LogService.__new__(LogService)
    svc.redis_client = MagicMock()
    svc.redis_client.smembers.return_value = set()
    svc.async_redis = MagicMock()
    return svc


class TestGetRunHistoryRegexMatch:
    """get_run_history() 정규식 이중 매칭 테스트"""

    def setup_method(self):
        from app.modules.dev_runner.services.log_service import LogService
        LogService._legacy_map.clear()

    def test_get_run_history_new_filename(self, tmp_path):
        """R(Right): runner_id 포함 신규 파일명 정상 매칭 → runner_id 추출, status=completed"""
        svc = _make_svc_no_redis()
        runner_id = "a1b2c3d4"
        (tmp_path / f"plan-runner-stream-{runner_id}-20260328.log").write_text(
            "log content\n", encoding="utf-8"
        )

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_run_history()

        assert any(r.runner_id == runner_id for r in result.runs)
        run = next(r for r in result.runs if r.runner_id == runner_id)
        assert run.status == "completed"

    def test_get_run_history_legacy_filename(self, tmp_path):
        """R(Right): 레거시 파일명 → lg- 접두사 pseudo runner_id 생성, 이력에 표시"""
        svc = _make_svc_no_redis()
        ts = "20260328_215641"
        (tmp_path / f"plan-runner-stream-{ts}.log").write_text(
            "legacy log\n", encoding="utf-8"
        )
        expected_pseudo = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_run_history()

        assert any(r.runner_id == expected_pseudo for r in result.runs)
        run = next(r for r in result.runs if r.runner_id == expected_pseudo)
        assert run.status == "completed"

    def test_get_run_history_legacy_pseudo_id_deterministic(self, tmp_path):
        """B(Boundary): 동일 timestamp 레거시 파일 → 동일 pseudo runner_id 반환 (결정적)"""
        from app.modules.dev_runner.services.log_service import LogService
        svc = _make_svc_no_redis()
        ts = "20260328_215641"
        (tmp_path / f"plan-runner-stream-{ts}.log").write_text("log\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result1 = svc.get_run_history()
        LogService._legacy_map.clear()
        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result2 = svc.get_run_history()

        ids1 = [r.runner_id for r in result1.runs]
        ids2 = [r.runner_id for r in result2.runs]
        assert ids1 == ids2

    def test_get_run_history_legacy_pseudo_id_no_collision(self, tmp_path):
        """B(Boundary): pseudo runner_id가 lg- 접두사이므로 [0-9a-f]{8} 실제 ID와 충돌 불가"""
        svc = _make_svc_no_redis()
        ts = "20260328_215641"
        (tmp_path / f"plan-runner-stream-{ts}.log").write_text("log\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_run_history()

        for run in result.runs:
            if run.runner_id.startswith("lg-"):
                assert not re.match(r"^[0-9a-f]{8}$", run.runner_id)

    def test_get_run_history_mixed_files(self, tmp_path):
        """R(Right): 신규+레거시 파일 혼재 시 모두 이력에 표시, 총 2개"""
        svc = _make_svc_no_redis()
        new_id = "a1b2c3d4"
        (tmp_path / f"plan-runner-stream-{new_id}-20260328.log").write_text("new\n", encoding="utf-8")
        ts = "20260328_215641"
        (tmp_path / f"plan-runner-stream-{ts}.log").write_text("legacy\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_run_history()

        assert len(result.runs) == 2
        runner_ids = [r.runner_id for r in result.runs]
        assert new_id in runner_ids
        pseudo_id = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"
        assert pseudo_id in runner_ids

    def test_get_run_history_non_matching_filename_skipped(self, tmp_path):
        """B(Boundary): plan-runner-stream-.log / plan-runner-stream-abc.log → 무시"""
        svc = _make_svc_no_redis()
        (tmp_path / "plan-runner-stream-.log").write_text("bad\n", encoding="utf-8")
        (tmp_path / "plan-runner-stream-abc.log").write_text("bad2\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_run_history()

        assert len(result.runs) == 0

    def test_get_run_history_populates_legacy_map(self, tmp_path):
        """R(Right): 레거시 파일 매칭 시 _legacy_map에 pseudo_id → Path 저장"""
        from app.modules.dev_runner.services.log_service import LogService
        svc = _make_svc_no_redis()
        ts = "20260328_215641"
        log_file = tmp_path / f"plan-runner-stream-{ts}.log"
        log_file.write_text("log\n", encoding="utf-8")
        expected_pseudo = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            svc.get_run_history()

        assert expected_pseudo in LogService._legacy_map
        assert LogService._legacy_map[expected_pseudo] == log_file


# ─── Phase 2a: get_full_log() 레거시 fallback ─────────────────────────────────

class TestGetFullLogLegacyFallback:
    """get_full_log() 레거시 fallback 테스트"""

    def setup_method(self):
        from app.modules.dev_runner.services.log_service import LogService
        LogService._legacy_map.clear()

    def _make(self):
        return _make_log_service()

    def test_get_full_log_legacy_from_cache(self, tmp_path):
        """R(Right): _legacy_map 캐시 히트 → 레거시 파일 로그 읽기 성공"""
        from app.modules.dev_runner.services.log_service import LogService
        svc = self._make()
        log_file = tmp_path / "plan-runner-stream-20260328_215641.log"
        log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
        pseudo_id = "lg-abc12"
        LogService._legacy_map[pseudo_id] = log_file

        with patch.object(svc, "_find_current_log", return_value=None):
            result = svc.get_full_log(runner_id=pseudo_id, offset=0, limit=500)

        assert result.total_lines == 3
        assert result.lines[0] == "line1"

    def test_get_full_log_legacy_cache_miss_scan(self, tmp_path):
        """R(Right): 캐시 미스 시 전체 스캔으로 레거시 파일 탐지 + _legacy_map 갱신"""
        from app.modules.dev_runner.services.log_service import LogService
        svc = self._make()
        ts = "20260328_220000"
        log_file = tmp_path / f"plan-runner-stream-{ts}.log"
        log_file.write_text("scanned line\n", encoding="utf-8")
        pseudo_id = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"

        with patch.object(svc, "_find_current_log", return_value=None), \
             patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_full_log(runner_id=pseudo_id, offset=0, limit=500)

        assert result.total_lines == 1
        assert result.lines[0] == "scanned line"
        assert pseudo_id in LogService._legacy_map

    def test_get_full_log_no_match_empty(self, tmp_path):
        """E(Error): 존재하지 않는 runner_id → 빈 결과 반환"""
        svc = self._make()

        with patch.object(svc, "_find_current_log", return_value=None), \
             patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_full_log(runner_id="nonexist", offset=0, limit=10)

        assert result.lines == []
        assert result.total_lines == 0


# ─── Phase 2b: tail_log_file() 레거시 fallback ────────────────────────────────

class TestTailLogFileLegacyFallback:
    """tail_log_file() 레거시 fallback 테스트"""

    def setup_method(self):
        from app.modules.dev_runner.services.log_service import LogService
        LogService._legacy_map.clear()

    def _make(self):
        return _make_log_service()

    def test_tail_log_file_legacy_from_cache(self, tmp_path):
        """R(Right): lg- 접두사 runner_id + _legacy_map 캐시 히트 → 레거시 파일 tail 성공"""
        from app.modules.dev_runner.services.log_service import LogService
        svc = self._make()
        log_file = tmp_path / "plan-runner-stream-20260328_215641.log"
        log_file.write_text("tail line 1\ntail line 2\n", encoding="utf-8")
        pseudo_id = "lg-abc12"
        LogService._legacy_map[pseudo_id] = log_file

        with patch.object(svc, "_find_current_log", return_value=None):
            result = svc.tail_log_file(runner_id=pseudo_id, n_lines=100)

        assert len(result.lines) == 2
        assert "tail line 1" in result.lines[0]

    def test_tail_log_file_legacy_no_cache_no_file(self, tmp_path):
        """B(Boundary): lg- runner_id + 캐시 미스 + 파일 없음 → 빈 응답"""
        svc = self._make()
        svc.redis_client.lrange.return_value = []

        with patch.object(svc, "_find_current_log", return_value=None), \
             patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.tail_log_file(runner_id="lg-00000", n_lines=100)

        assert result.lines == []
        assert result.total_lines == 0


# ─── Phase 3: _find_current_log() 파일시스템 fallback ────────────────────────

class TestFindCurrentLogFilesystemFallback:
    """_find_current_log() 파일시스템 fallback 테스트"""

    def _make(self):
        return _make_log_service()

    def test_find_current_log_redis_hit(self, tmp_path):
        """R(Right): Redis stream_log_path 유효 → 해당 Path 반환 (기존 동작 유지)"""
        svc = self._make()
        stream_file = tmp_path / "plan-runner-stream-a1b2c3d4-20260328.log"
        stream_file.write_bytes(b"x" * 500)  # 200B 초과

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else None
        )

        result = svc._find_current_log("a1b2c3d4")
        assert result == stream_file

    def test_find_current_log_filesystem_fallback_stream(self, tmp_path):
        """R(Right): Redis ConnectionError 시 plan-runner-stream-{runner_id}-*.log 탐지"""
        svc = self._make()
        svc.redis_client.get.side_effect = redis.ConnectionError

        runner_id = "a1b2c3d4"
        log_file = tmp_path / f"plan-runner-stream-{runner_id}-20260328.log"
        log_file.write_text("content\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc._find_current_log(runner_id)

        assert result == log_file

    def test_find_current_log_filesystem_fallback_listener(self, tmp_path):
        """R(Right): stream 파일 없으면 plan-runner-{runner_id}-*.log 탐지"""
        svc = self._make()
        svc.redis_client.get.side_effect = redis.ConnectionError

        runner_id = "a1b2c3d4"
        log_file = tmp_path / f"plan-runner-{runner_id}-20260328.log"
        log_file.write_text("listener content\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc._find_current_log(runner_id)

        assert result == log_file

    def test_find_current_log_no_file_returns_none(self, tmp_path):
        """B(Boundary): Redis 미탐지 + 파일 없음 → None"""
        svc = self._make()
        svc.redis_client.get.side_effect = redis.ConnectionError

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc._find_current_log("a1b2c3d4")

        assert result is None

    def test_find_current_log_legacy_id_skipped(self, tmp_path):
        """B(Boundary): lg- 접두사 runner_id → 파일시스템 fallback 건너뜀, None 반환"""
        svc = self._make()
        svc.redis_client.get.side_effect = redis.ConnectionError

        # lg- 파일이 있어도 반환하지 않음
        (tmp_path / "plan-runner-stream-20260328_215641.log").write_text(
            "legacy\n", encoding="utf-8"
        )

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc._find_current_log("lg-abc12")

        assert result is None


# ─── Phase T3: 통합 TC ────────────────────────────────────────────────────────

class TestLegacyFullPipelineIntegration:
    """Phase T3: 레거시/신규 파일 혼재 파이프라인 통합 검증"""

    def setup_method(self):
        from app.modules.dev_runner.services.log_service import LogService
        LogService._legacy_map.clear()

    def _make(self):
        return _make_svc_no_redis()

    def test_legacy_full_pipeline_integration(self, tmp_path):
        """레거시 3개 + 신규 2개 → history 5개 → get_full_log/tail 성공 (파일시스템 실물)"""
        svc = self._make()

        legacy_timestamps = ["20260328_100000", "20260328_110000", "20260328_120000"]
        for ts in legacy_timestamps:
            (tmp_path / f"plan-runner-stream-{ts}.log").write_text(
                f"legacy log {ts}\n", encoding="utf-8"
            )

        new_ids = ["a1b2c3d4", "e5f6a7b8"]
        for nid in new_ids:
            (tmp_path / f"plan-runner-stream-{nid}-20260328.log").write_text(
                f"new log {nid}\n", encoding="utf-8"
            )

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            history = svc.get_run_history()

        assert len(history.runs) == 5

        # pseudo ID로 get_full_log 호출 (cache hit: get_run_history가 이미 채움)
        ts0 = legacy_timestamps[0]
        pseudo_id = f"lg-{hashlib.md5(ts0.encode()).hexdigest()[:5]}"

        with patch.object(svc, "_find_current_log", return_value=None), \
             patch.object(svc, "_get_log_dir", return_value=tmp_path):
            full_log = svc.get_full_log(runner_id=pseudo_id, offset=0, limit=500)

        assert full_log.total_lines == 1
        assert ts0 in full_log.lines[0]

        # pseudo ID로 tail_log_file 호출 (cache hit)
        with patch.object(svc, "_find_current_log", return_value=None):
            tail = svc.tail_log_file(runner_id=pseudo_id, n_lines=100)

        assert len(tail.lines) == 1

    def test_find_current_log_fallback_chain_integration(self, tmp_path):
        """Redis 키 없는 신규 형식: stream → listener 순서로 fallback (실물 파일시스템)"""
        svc = self._make()
        svc.redis_client.get.side_effect = redis.ConnectionError

        runner_id = "a1b2c3d4"

        # 1. listener만 있는 경우 → listener 반환
        listener_file = tmp_path / f"plan-runner-{runner_id}-20260328.log"
        listener_file.write_text("listener content\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc._find_current_log(runner_id)
        assert result == listener_file

        # 2. stream도 있으면 stream 우선
        stream_file = tmp_path / f"plan-runner-stream-{runner_id}-20260328.log"
        stream_file.write_text("stream content\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result2 = svc._find_current_log(runner_id)
        assert result2 == stream_file


# ─── Phase 1: _find_current_log() 200B 기준 제거 TC ───────────────────────────

class TestFindCurrentLogNoBytesCheck:
    """_find_current_log() 크기 체크 제거 후 동작 검증"""

    def test_find_current_log_small_stream_file_returned(self, tmp_path):
        """R: stream_log_path 50B(START 마커만)여도 해당 파일 반환"""
        svc = _make_log_service()
        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[START] marker")  # ~14B

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == stream_file

    def test_find_current_log_stream_exists_log_file_ignored(self, tmp_path):
        """R: stream_log_path 50B 존재 + log_file_path 1KB → stream 반환"""
        svc = _make_log_service()
        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[START] " + b"x" * 50)  # 58B
        log_file = tmp_path / "log.log"
        log_file.write_text("[INFO] 실제 로그\n" * 50, encoding="utf-8")

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == stream_file

    def test_find_current_log_stream_absent_uses_log_file(self, tmp_path):
        """R: stream_log_path 키는 있으나 파일 미존재 → log_file_path 반환"""
        svc = _make_log_service()
        log_file = tmp_path / "log.log"
        log_file.write_text("[INFO] fallback log\n", encoding="utf-8")

        svc.redis_client.get.side_effect = lambda key: (
            str(tmp_path / "nonexistent_stream.log") if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == log_file


# ─── Phase 1: tail_log_file() from_line 필드 TC ───────────────────────────────

class TestTailLogFileFromLine:
    """tail_log_file() from_line 필드 정확성 검증"""

    def test_tail_log_file_from_line_correct(self, tmp_path):
        """R: 파일 200줄, n_lines=100 → from_line=100, len(lines)=100"""
        svc = _make_log_service()
        log_file = tmp_path / "test.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(200)) + "\n", encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        result = svc.tail_log_file("runner", n_lines=100)

        assert result.from_line == 100
        assert len(result.lines) == 100
        assert result.lines[0] == "line 100"

    def test_tail_log_file_from_line_zero_when_file_short(self, tmp_path):
        """B: 파일 50줄, n_lines=100 → from_line=0 (전체 반환)"""
        svc = _make_log_service()
        log_file = tmp_path / "short.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(50)) + "\n", encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        result = svc.tail_log_file("runner", n_lines=100)

        assert result.from_line == 0
        assert len(result.lines) == 50


# ─── Phase 1: stream_log_file() since_line TC ────────────────────────────────

import asyncio as _asyncio


def _run_async(coro):
    return _asyncio.get_event_loop().run_until_complete(coro)


def _make_mock_pubsub_completed():
    """__COMPLETED__ 즉시 반환하는 mock pubsub"""
    mock_pubsub = MagicMock()
    call_count = [0]

    async def mock_get_message(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"type": "message", "data": "__COMPLETED__"}
        return None

    async def mock_subscribe(ch): pass
    async def mock_aclose(): pass

    mock_pubsub.get_message = mock_get_message
    mock_pubsub.subscribe = mock_subscribe
    mock_pubsub.aclose = mock_aclose
    return mock_pubsub


def _make_mock_pubsub_completed_with_reason(reason: str):
    """__COMPLETED::{reason}__ 1회 반환하는 mock pubsub"""
    mock_pubsub = MagicMock()
    call_count = [0]

    async def mock_get_message(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"type": "message", "data": f"__COMPLETED::{reason}__"}
        return None

    async def mock_subscribe(ch): pass
    async def mock_aclose(): pass

    mock_pubsub.get_message = mock_get_message
    mock_pubsub.subscribe = mock_subscribe
    mock_pubsub.aclose = mock_aclose
    return mock_pubsub


class TestStreamLogFileSinceLine:
    """stream_log_file() since_line 파라미터 동작 검증"""

    def test_stream_log_file_since_line_sends_buffered_lines(self, tmp_path):
        """R: 100줄 파일, since_line=50 → 인덱스 50(line 50)부터 yield"""
        svc = _make_log_service()
        log_file = tmp_path / "stream.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(100)) + "\n", encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        async def mock_ping(): return True
        svc.async_redis.ping = mock_ping
        svc.async_redis.pubsub = MagicMock(return_value=_make_mock_pubsub_completed())

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file("runner", since_line=50):
                chunks.append(chunk)
            return chunks

        chunks = _run_async(collect())
        data_chunks = [c for c in chunks if c.startswith("data: ")]
        assert len(data_chunks) >= 1
        assert "line 50" in data_chunks[0]

    def test_stream_log_file_since_line_zero_no_buffered(self, tmp_path):
        """B: since_line=0 → _find_current_log 호출 없이 바로 pub/sub 대기"""
        svc = _make_log_service()
        log_file = tmp_path / "stream.log"
        log_file.write_text("line 0\nline 1\n", encoding="utf-8")
        find_call_count = [0]

        def tracking_find(runner_id):
            find_call_count[0] += 1
            return log_file

        svc._find_current_log = tracking_find

        async def mock_ping(): return True
        svc.async_redis.ping = mock_ping
        svc.async_redis.pubsub = MagicMock(return_value=_make_mock_pubsub_completed())

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file("runner", since_line=0):
                chunks.append(chunk)
            return chunks

        _run_async(collect())
        assert find_call_count[0] == 0

    def test_stream_log_file_since_line_file_pos_set(self, tmp_path):
        """R: since_line=50 후 gap fill이 파일 50줄 이후를 읽음을 검증"""
        svc = _make_log_service()
        log_file = tmp_path / "stream.log"
        content = "\n".join(f"line {i}" for i in range(100)) + "\n"
        log_file.write_text(content, encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        async def mock_ping(): return True
        svc.async_redis.ping = mock_ping
        svc.async_redis.pubsub = MagicMock(return_value=_make_mock_pubsub_completed())

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file("runner", since_line=50):
                chunks.append(chunk)
            return chunks

        chunks = _run_async(collect())
        # 멀티라인 프레임 ON/OFF 모두 허용: 전송 단위(chunk)가 아니라 실제 data line 기준으로 검증
        data_lines = []
        for chunk in chunks:
            for row in chunk.splitlines():
                if row.startswith("data: line "):
                    data_lines.append(row.replace("data: ", "", 1))

        assert len(data_lines) == 50
        assert data_lines[0] == "line 50"
        assert data_lines[-1] == "line 99"

    def test_stream_log_file_completed_reason_rate_limited_normalized(self, tmp_path):
        """R: __COMPLETED::rate_limited__ 수신 시 completed reason=rate_limit 정규화"""
        svc = _make_log_service()
        log_file = tmp_path / "stream.log"
        log_file.write_text("", encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        async def mock_ping(): return True
        svc.async_redis.ping = mock_ping
        svc.async_redis.pubsub = MagicMock(return_value=_make_mock_pubsub_completed_with_reason("rate_limited"))

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file("runner", since_line=0):
                chunks.append(chunk)
            return chunks

        chunks = _run_async(collect())
        assert "event: completed\ndata: rate_limit\n\n" in chunks


# ─── Phase T3: 통합 TC ────────────────────────────────────────────────────────

class TestSinceLineIntegration:
    """since_line + from_line 통합 TC"""

    def test_tail_log_file_from_line_chain_integration(self, tmp_path):
        """T3: 300줄 파일, tail(100) → from_line=200. since_line=300 → 파일 버퍼 0줄"""
        svc = _make_log_service()
        log_file = tmp_path / "chain.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(300)) + "\n", encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        tail_result = svc.tail_log_file("runner", n_lines=100)
        assert tail_result.from_line == 200
        assert len(tail_result.lines) == 100

        since_line = tail_result.from_line + len(tail_result.lines)  # = 300
        assert since_line == 300

        async def mock_ping(): return True
        svc.async_redis.ping = mock_ping
        svc.async_redis.pubsub = MagicMock(return_value=_make_mock_pubsub_completed())

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file("runner", since_line=since_line):
                chunks.append(chunk)
            return chunks

        chunks = _run_async(collect())
        buffered_data = [c for c in chunks if c.startswith("data: line")]
        assert len(buffered_data) == 0  # 파일에서 300줄 이후 없음

    def test_since_line_gap_fill_integration(self, tmp_path):
        """T3: 200줄 파일 + pub/sub 10줄, since_line=200 → 파일 버퍼 0줄 + pub/sub 10줄"""
        svc = _make_log_service()
        log_file = tmp_path / "gap.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(200)) + "\n", encoding="utf-8")
        svc._find_current_log = MagicMock(return_value=log_file)

        pubsub_lines = [f"line {i}" for i in range(200, 210)]

        mock_pubsub = MagicMock()
        call_count = [0]

        async def mock_get_message(**kwargs):
            call_count[0] += 1
            idx = call_count[0] - 1
            if idx < len(pubsub_lines):
                return {"type": "message", "data": pubsub_lines[idx]}
            return {"type": "message", "data": "__COMPLETED__"}

        async def mock_subscribe(ch): pass
        async def mock_aclose(): pass

        mock_pubsub.get_message = mock_get_message
        mock_pubsub.subscribe = mock_subscribe
        mock_pubsub.aclose = mock_aclose

        async def mock_ping(): return True
        svc.async_redis.ping = mock_ping
        svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file("runner", since_line=200):
                chunks.append(chunk)
            return chunks

        chunks = _run_async(collect())
        data_chunks = [c for c in chunks if c.startswith("data: line")]
        # pub/sub 10줄만 (파일 버퍼 0)
        assert len(data_chunks) == 10
        assert "line 200" in data_chunks[0]
        assert "line 209" in data_chunks[9]
