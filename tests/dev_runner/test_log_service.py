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
        """R: START-only stream + 본로그 정상 → 본로그 반환"""
        svc = _make_log_service()

        stream_file = tmp_path / "stream.log"
        stream_file.write_text("[2026-05-04T16:48:10] START | log_path=log.log\n", encoding="utf-8")
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


class TestLogFileResolverDisplayPlanName:
    """log header 기반 display_plan_name fallback 계약."""

    def test_display_plan_name_from_trigger_plan(self, tmp_path):
        from app.modules.dev_runner.services.log_file_resolver import LogFileResolver

        log_file = tmp_path / "runner.log"
        log_file.write_text(
            "[TRIGGER] user | plan=docs/plan/2026-05-05_fix-dev-runner.md\n",
            encoding="utf-8",
        )

        meta = LogFileResolver.parse_meta_from_log(str(log_file))

        assert LogFileResolver.display_plan_name_from_meta(meta) == "2026-05-05_fix-dev-runner.md"

    def test_display_plan_name_from_run_meta_plan_key(self, tmp_path):
        from app.modules.dev_runner.services.log_file_resolver import LogFileResolver

        log_file = tmp_path / "runner.log"
        log_file.write_text(
            "[RUN_META] started_at=2026-05-05T16:00:00 | execution_count=2 | plan_key=docs/plan/runtime-plan.md\n",
            encoding="utf-8",
        )

        meta = LogFileResolver.parse_meta_from_log(str(log_file))

        assert LogFileResolver.display_plan_name_from_meta(meta) == "runtime-plan.md"

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
    """tail_log_file E2E 흐름 — START-only stream은 본로그를 가리지 않는다."""

    def test_tail_log_file_e2e_returns_main_log_when_stream_is_start_marker_only(self, tmp_path):
        """T3 E2E: START-only stream + log_file 정상 → 본로그 tail 반환"""
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
        assert result.from_line == 0
        assert "PLAN-RUNNER" in result.lines[0]
        assert "START" not in "\n".join(result.lines)


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
            result = svc.get_run_history(visible_only=False)

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
            result = svc.get_run_history(visible_only=False)

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
            result1 = svc.get_run_history(visible_only=False)
        LogService._legacy_map.clear()
        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result2 = svc.get_run_history(visible_only=False)

        ids1 = [r.runner_id for r in result1.runs]
        ids2 = [r.runner_id for r in result2.runs]
        assert ids1 == ids2

    def test_get_run_history_legacy_pseudo_id_no_collision(self, tmp_path):
        """B(Boundary): pseudo runner_id가 lg- 접두사이므로 [0-9a-f]{8} 실제 ID와 충돌 불가"""
        svc = _make_svc_no_redis()
        ts = "20260328_215641"
        (tmp_path / f"plan-runner-stream-{ts}.log").write_text("log\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc.get_run_history(visible_only=False)

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
            result = svc.get_run_history(visible_only=False)

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
            result = svc.get_run_history(visible_only=False)

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
            svc.get_run_history(visible_only=False)

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
            history = svc.get_run_history(visible_only=False)

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
        """R: START-only stream + log_file_path 1KB → 본로그 반환"""
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
        assert result == log_file

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

    def test_find_current_log_keeps_stream_when_stream_has_real_output_right(self, tmp_path):
        """R: stream 파일에 실제 출력이 있으면 stream 우선 계약 유지"""
        svc = _make_log_service()
        stream_file = tmp_path / "stream.log"
        stream_file.write_text(
            "[16:48:10] [PLAN-RUNNER#feat@abcd] [INFO] 실행 환경\n",
            encoding="utf-8",
        )
        log_file = tmp_path / "log.log"
        log_file.write_text("[16:48:10] [INFO] 본로그\n", encoding="utf-8")

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc._find_current_log("test-runner")
        assert result == stream_file


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

    def test_tail_log_file_from_line_uses_selected_main_log_correct(self, tmp_path):
        """CORRECT: paired resolver가 본로그를 선택하면 from_line도 본로그 기준으로 계산"""
        svc = _make_log_service()
        stream_file = tmp_path / "stream.log"
        stream_file.write_text("[START] marker only\n", encoding="utf-8")
        log_file = tmp_path / "log.log"
        log_file.write_text("\n".join(f"[INFO] main line {i}" for i in range(12)) + "\n", encoding="utf-8")

        svc.redis_client.get.side_effect = lambda key: (
            str(stream_file) if "stream_log_path" in key else
            str(log_file) if "log_file_path" in key else None
        )

        result = svc.tail_log_file("test-runner", n_lines=5)

        assert result.from_line == 7
        assert result.total_lines == 5
        assert result.lines[0] == "[INFO] main line 7"


# ─── Phase 1: stream_log_file() since_line TC ────────────────────────────────

import asyncio as _asyncio


def _run_async(coro):
    return _asyncio.run(coro)


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


# ─── Phase T1 (todo-2): 채널 상수·구독·fallback EOF 초기화 TC ─────────────────

class TestSystemLogChannelConstant:
    """SYSTEM_LOG_CHANNEL 상수 회귀 방지 TC"""

    def test_system_log_channel_value(self):
        """SYSTEM_LOG_CHANNEL == 'plan-runner:system' 단언 (상수 드리프트 방지)"""
        from app.modules.dev_runner.services.log_service import SYSTEM_LOG_CHANNEL
        assert SYSTEM_LOG_CHANNEL == "plan-runner:system", (
            f"SYSTEM_LOG_CHANNEL이 'plan-runner:system'이 아님: {SYSTEM_LOG_CHANNEL!r}\n"
            "bare 'plan-runner:logs' 채널과 다른 전용 채널을 사용해야 합니다."
        )

    def test_log_channel_prefix_unchanged(self):
        """LOG_CHANNEL_PREFIX == 'plan-runner:logs' 유지 (per-runner 구독 형식 계약)"""
        from app.modules.dev_runner.services.log_service import LOG_CHANNEL_PREFIX
        assert LOG_CHANNEL_PREFIX == "plan-runner:logs"

    def test_per_runner_channel_format(self):
        """per-runner 채널 = LOG_CHANNEL_PREFIX + ':' + runner_id 형식 확인"""
        from app.modules.dev_runner.services.log_service import LOG_CHANNEL_PREFIX
        runner_id = "abc12345"
        expected = f"plan-runner:logs:{runner_id}"
        assert LOG_CHANNEL_PREFIX + ":" + runner_id == expected


class TestStreamLogFileSubscribesPerRunnerChannel:
    """stream_log_file() 채널 구독 계약 TC"""

    def _make(self):
        svc = _make_log_service()
        return svc

    def test_stream_log_file_subscribes_per_runner_channel(self):
        """stream_log_file('runner123') → pubsub.subscribe('plan-runner:logs:runner123') 확인"""
        import asyncio
        from unittest.mock import AsyncMock, call

        svc = self._make()
        runner_id = "runner123"
        expected_channel = f"plan-runner:logs:{runner_id}"

        subscribed_channels = []

        mock_pubsub = MagicMock()

        async def mock_subscribe(ch):
            subscribed_channels.append(ch)

        async def mock_get_message(**kwargs):
            # 즉시 __COMPLETED__ 반환하여 스트림 종료
            if not subscribed_channels:
                return None
            return {"type": "message", "data": "__COMPLETED__"}

        async def mock_aclose(): pass

        mock_pubsub.subscribe = mock_subscribe
        mock_pubsub.get_message = mock_get_message
        mock_pubsub.aclose = mock_aclose

        async def mock_ping(): return True
        svc.async_redis.ping = AsyncMock(return_value=True)
        svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
        svc._find_current_log = MagicMock(return_value=None)
        svc._sync_resolver = MagicMock()

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file(runner_id, since_line=0):
                chunks.append(chunk)
            return chunks

        asyncio.run(collect())

        assert expected_channel in subscribed_channels, (
            f"subscribe 채널이 '{expected_channel}'이 아님. 실제: {subscribed_channels}\n"
            "bare 'plan-runner:logs'가 아닌 per-runner 채널을 구독해야 합니다."
        )

    def test_stream_log_file_does_not_subscribe_bare_channel(self):
        """stream_log_file은 bare 'plan-runner:logs' 채널을 구독하지 않아야 함"""
        import asyncio
        from unittest.mock import AsyncMock

        svc = self._make()
        subscribed_channels = []
        mock_pubsub = MagicMock()

        async def mock_subscribe(ch):
            subscribed_channels.append(ch)

        async def mock_get_message(**kwargs):
            if not subscribed_channels:
                return None
            return {"type": "message", "data": "__COMPLETED__"}

        async def mock_aclose(): pass

        mock_pubsub.subscribe = mock_subscribe
        mock_pubsub.get_message = mock_get_message
        mock_pubsub.aclose = mock_aclose

        svc.async_redis.ping = AsyncMock(return_value=True)
        svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
        svc._find_current_log = MagicMock(return_value=None)
        svc._sync_resolver = MagicMock()

        async def collect():
            chunks = []
            async for chunk in svc.stream_log_file("any_runner", since_line=0):
                chunks.append(chunk)
            return chunks

        asyncio.run(collect())

        assert "plan-runner:logs" not in subscribed_channels, (
            "bare 'plan-runner:logs' 채널을 구독 중 — 채널 불일치 버그 재발"
        )


def _make_log_service_with_resolver_mock():
    """LogService 인스턴스 생성 (Redis + resolver 모두 mock).
    resolver.find_current_log()가 None을 반환하므로 shim의 파일시스템 fallback으로 진입.
    """
    from app.modules.dev_runner.services.log_service import LogService
    from app.modules.dev_runner.services.log_file_resolver import LogFileResolver

    svc = LogService.__new__(LogService)
    svc.redis_client = MagicMock()
    svc.async_redis = MagicMock()
    # resolver mock (isinstance 체크 통과를 위해 spec 사용)
    svc.resolver = MagicMock(spec=LogFileResolver)
    svc.resolver.find_current_log.return_value = None
    # _sync_resolver가 resolver를 교체하지 않도록 mock
    svc._sync_resolver = MagicMock()
    return svc


class TestFindCurrentLogMtimeLatest:
    """_find_current_log() mtime 최신 파일 반환 TC"""

    def test_find_current_log_returns_latest_by_mtime(self, tmp_path):
        """동일 runner_id 파일 2개 (mtime 다름) → mtime 최신 반환"""
        import time as _time

        svc = _make_log_service_with_resolver_mock()

        runner_id = "testrunner"
        old_file = tmp_path / f"plan-runner-stream-{runner_id}-20260401_100000.log"
        new_file = tmp_path / f"plan-runner-stream-{runner_id}-20260401_120000.log"
        old_file.write_text("old content\n", encoding="utf-8")
        _time.sleep(0.05)  # mtime 차이 보장
        new_file.write_text("new content\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc._find_current_log(runner_id)

        assert result == new_file, (
            f"mtime 최신 파일({new_file.name})이 아닌 {result.name if result else None} 반환됨"
        )

    def test_find_current_log_with_runner_id_glob_match(self, tmp_path):
        """plan-runner-stream-{runner_id}-{timestamp}.log 패턴 매칭 확인"""
        svc = _make_log_service_with_resolver_mock()

        runner_id = "715f9881"
        matched_file = tmp_path / f"plan-runner-stream-{runner_id}-20260408_224528.log"
        matched_file.write_text("log content\n", encoding="utf-8")
        # 다른 runner_id 파일 (매칭 안 됨)
        (tmp_path / "plan-runner-stream-other-20260408_224528.log").write_text("x\n", encoding="utf-8")

        with patch.object(svc, "_get_log_dir", return_value=tmp_path):
            result = svc._find_current_log(runner_id)

        assert result == matched_file


class TestFilePosEofInitialization:
    """_file_pos 초기화: since_line=0 파일 폴링 fallback 진입 시 파일 처음부터 읽기 TC"""

    def test_file_pos_init_sends_existing_content_when_since_line_zero(self, tmp_path):
        """since_line=0 + 파일 기존 내용 존재 + 폴링 fallback → 기존 내용을 1회 전송해야 함."""
        import asyncio as _asyncio
        from unittest.mock import AsyncMock, patch as _patch

        svc = _make_log_service()

        log_file = tmp_path / "plan-runner-stream-runner1-20260408.log"
        log_file.write_text("existing line 1\nexisting line 2\n", encoding="utf-8")

        pubsub_call = [0]
        mock_pubsub = MagicMock()

        async def mock_get_message(**kwargs):
            pubsub_call[0] += 1
            if pubsub_call[0] > 5:
                return {"type": "message", "data": "__COMPLETED__"}
            return None

        async def mock_subscribe(ch): pass
        async def mock_aclose(): pass

        mock_pubsub.get_message = mock_get_message
        mock_pubsub.subscribe = mock_subscribe
        mock_pubsub.aclose = mock_aclose

        svc.async_redis.ping = AsyncMock(return_value=True)
        svc.async_redis.pubsub = MagicMock(return_value=mock_pubsub)
        svc._find_current_log = MagicMock(return_value=log_file)
        svc._sync_resolver = MagicMock()

        _monotonic_calls = [0]
        _T0 = 100.0

        def mock_monotonic():
            """처음 2회=T0 (last_heartbeat, _no_msg_since 초기화), 이후=T0+10 (timeout 초과)"""
            _monotonic_calls[0] += 1
            if _monotonic_calls[0] <= 2:
                return _T0
            return _T0 + 10.0

        async def instant_sleep(delay=0, result=None, **kwargs):
            """asyncio.sleep 즉시 반환 (실제 I/O wait 방지)"""
            pass

        async def collect():
            chunks = []
            with _patch(
                "app.modules.dev_runner.services.log_service.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with _patch.object(_asyncio, "sleep", instant_sleep):
                    async for chunk in svc.stream_log_file("runner1", since_line=0):
                        chunks.append(chunk)
            return chunks

        chunks = _asyncio.run(collect())

        # since_line=0은 클라이언트가 아직 파일 내용을 받지 못한 초기 연결로 보고 1회 전송한다.
        data_chunks = [c for c in chunks if "existing line" in c]
        assert len(data_chunks) >= 1, (
            f"기존 내용이 전송되지 않음: {chunks}\n"
            "fallback 첫 진입에서 since_line=0이면 파일 처음부터 읽어야 합니다."
        )
        # 스트림이 정상 완료됨 확인
        completed = [c for c in chunks if "event: completed" in c]
        assert len(completed) >= 1, f"event: completed 미수신. chunks={chunks}"


class TestPlanServicePublishChannel:
    """plan_service._publish_log() SYSTEM_LOG_CHANNEL 사용 확인 TC"""

    def test_publish_log_uses_system_log_channel(self):
        """_publish_log가 'plan-runner:system' 채널로 publish (bare 'plan-runner:logs' 아님)"""
        import fakeredis
        from app.modules.dev_runner.services.log_service import SYSTEM_LOG_CHANNEL

        fr = fakeredis.FakeRedis(decode_responses=True)

        # plan_service 모듈의 _redis_client를 fakeredis로 교체
        import app.modules.dev_runner.services.plan_service as ps
        original = ps._redis_client
        ps._redis_client = fr

        sub = fr.pubsub()
        sub.subscribe(SYSTEM_LOG_CHANNEL)
        sub.get_message()  # subscribe 확인 메시지 소비

        try:
            ps._publish_log("TEST", "hello system channel")
        finally:
            ps._redis_client = original

        msg = sub.get_message()
        assert msg is not None, "SYSTEM_LOG_CHANNEL에서 메시지 수신 안 됨"
        assert msg["channel"] == SYSTEM_LOG_CHANNEL, (
            f"publish 채널이 '{SYSTEM_LOG_CHANNEL}'이 아님: {msg['channel']!r}"
        )
        assert "hello system channel" in msg["data"], (
            f"메시지 내용 불일치: {msg['data']!r}"
        )

    def test_publish_log_not_on_bare_logs_channel(self):
        """_publish_log가 bare 'plan-runner:logs' 채널로 publish하지 않음 (채널 불일치 방지)"""
        import fakeredis

        fr = fakeredis.FakeRedis(decode_responses=True)
        import app.modules.dev_runner.services.plan_service as ps
        original = ps._redis_client
        ps._redis_client = fr

        bare_channel = "plan-runner:logs"
        sub = fr.pubsub()
        sub.subscribe(bare_channel)
        sub.get_message()  # subscribe 확인 메시지 소비

        try:
            ps._publish_log("TEST", "should not appear on bare channel")
        finally:
            ps._redis_client = original

        msg = sub.get_message()
        assert msg is None, (
            f"bare 'plan-runner:logs' 채널에 메시지 publish됨 — 채널 불일치 버그 재발: {msg!r}"
        )


# =============================================================================
# FAILURE/HOLD 태그 Telegram 알림 TC
# =============================================================================

class TestTelegramNotificationOnFailureTag:
    """FAILURE/HOLD tag Telegram notification TC"""

    def test_failure_tag_triggers_telegram_R(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch as _patch
        from app.modules.dev_runner.services.log_service import _send_failure_telegram, _telegram_debounce
        _telegram_debounce.clear()
        send_calls = []
        async def run():
            with _patch('app.shared.notification.notification_service.NotificationService') as mock_cls:
                mock_inst = MagicMock()
                mock_inst.send_telegram = AsyncMock(side_effect=lambda msg: send_calls.append(msg))
                mock_cls.return_value = mock_inst
                await _send_failure_telegram('runner#abc', 'FAILURE', 'rate_limit: AI 한도 소진')
        asyncio.run(run())
        assert len(send_calls) == 1

    def test_hold_tag_triggers_telegram_R(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch as _patch
        from app.modules.dev_runner.services.log_service import _send_failure_telegram, _telegram_debounce
        _telegram_debounce.clear()
        send_calls = []
        async def run():
            with _patch('app.shared.notification.notification_service.NotificationService') as mock_cls:
                mock_inst = MagicMock()
                mock_inst.send_telegram = AsyncMock(side_effect=lambda msg: send_calls.append(msg))
                mock_cls.return_value = mock_inst
                await _send_failure_telegram('runner#abc', 'HOLD', 'P0 예약 수정 후 진행')
        asyncio.run(run())
        assert len(send_calls) == 1

    def test_failure_telegram_debounce_B(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch as _patch
        from app.modules.dev_runner.services.log_service import _send_failure_telegram, _telegram_debounce
        _telegram_debounce.clear()
        send_calls = []
        async def run():
            with _patch('app.shared.notification.notification_service.NotificationService') as mock_cls:
                mock_inst = MagicMock()
                mock_inst.send_telegram = AsyncMock(side_effect=lambda msg: send_calls.append(msg))
                mock_cls.return_value = mock_inst
                detail = 'rate_limit: AI 한도 소진'
                await _send_failure_telegram('runner#abc', 'FAILURE', detail)
                await _send_failure_telegram('runner#abc', 'FAILURE', detail)
        asyncio.run(run())
        assert len(send_calls) == 1, f'debounce 실패: {len(send_calls)}회 호출됨'


class TestTelegramNotificationT3:
    """T3: 실물 Redis pub/sub 통합 검증 — Telegram API (_send_failure_telegram)만 mock"""

    def test_failure_tag_telegram_integration_T3(self):
        """T3-01: 실물 Redis pub/sub에 [FAILURE] 태그 메시지 publish → _send_failure_telegram 호출 검증"""
        import asyncio
        import pytest
        from unittest.mock import MagicMock, patch as _patch
        import redis.asyncio as aioredis
        from app.modules.dev_runner.services.log_service import LogService, LOG_CHANNEL_PREFIX
        from app.modules.dev_runner.services.completion_reason import LOG_COMPLETED_SENTINEL

        runner_id = "t3-test-failure-runner-x1"
        channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        send_failure_calls: list[tuple] = []

        async def fake_send(rid: str, tag: str, detail: str) -> None:
            send_failure_calls.append((rid, tag, detail))

        async def run():
            r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
            try:
                await r.ping()
            except Exception:
                return "skip"

            svc = LogService.__new__(LogService)
            svc.async_redis = r
            svc.redis_client = MagicMock()
            svc._find_current_log = MagicMock(return_value=None)

            collected: list[str] = []

            async def consume():
                async for item in svc.stream_log_file(runner_id, since_line=0):
                    collected.append(item)
                    if "event: completed" in item:
                        break

            with _patch(
                "app.modules.dev_runner.services.log_service._send_failure_telegram",
                side_effect=fake_send,
            ):
                task = asyncio.create_task(consume())
                await asyncio.sleep(0.3)  # 구독 대기
                await r.publish(channel, "[FAILURE] rate_limit: AI 한도 소진")
                await asyncio.sleep(0.5)  # 태그 감지 + create_task 실행 대기
                await r.publish(channel, LOG_COMPLETED_SENTINEL)
                try:
                    await asyncio.wait_for(task, timeout=4.0)
                except asyncio.TimeoutError:
                    task.cancel()

            await r.aclose()
            return send_failure_calls

        result = asyncio.run(run())
        if result == "skip":
            return  # Redis 미연결 — 로컬 환경 skip

        assert len(result) >= 1, f"_send_failure_telegram 미호출 — pubsub 감지 실패 (calls={result})"
        assert result[0][1] == "FAILURE", f"tag 불일치: {result[0][1]!r}"
        assert "rate_limit" in result[0][2], f"detail 불일치: {result[0][2]!r}"

    def test_hold_tag_telegram_integration_T3(self):
        """T3-02: 실물 Redis pub/sub에 [HOLD] 태그 메시지 publish → _send_failure_telegram 호출 검증"""
        import asyncio
        from unittest.mock import MagicMock, patch as _patch
        import redis.asyncio as aioredis
        from app.modules.dev_runner.services.log_service import LogService, LOG_CHANNEL_PREFIX
        from app.modules.dev_runner.services.completion_reason import LOG_COMPLETED_SENTINEL

        runner_id = "t3-test-hold-runner-x1"
        channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        send_failure_calls: list[tuple] = []

        async def fake_send(rid: str, tag: str, detail: str) -> None:
            send_failure_calls.append((rid, tag, detail))

        async def run():
            r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
            try:
                await r.ping()
            except Exception:
                return "skip"

            svc = LogService.__new__(LogService)
            svc.async_redis = r
            svc.redis_client = MagicMock()
            svc._find_current_log = MagicMock(return_value=None)

            collected: list[str] = []

            async def consume():
                async for item in svc.stream_log_file(runner_id, since_line=0):
                    collected.append(item)
                    if "event: completed" in item:
                        break

            with _patch(
                "app.modules.dev_runner.services.log_service._send_failure_telegram",
                side_effect=fake_send,
            ):
                task = asyncio.create_task(consume())
                await asyncio.sleep(0.3)
                await r.publish(channel, "[HOLD] P0 예약 완료 후 수동 진행 필요")
                await asyncio.sleep(0.5)
                await r.publish(channel, LOG_COMPLETED_SENTINEL)
                try:
                    await asyncio.wait_for(task, timeout=4.0)
                except asyncio.TimeoutError:
                    task.cancel()

            await r.aclose()
            return send_failure_calls

        result = asyncio.run(run())
        if result == "skip":
            return  # Redis 미연결 — 로컬 환경 skip

        assert len(result) >= 1, f"_send_failure_telegram 미호출 — pubsub 감지 실패 (calls={result})"
        assert result[0][1] == "HOLD", f"tag 불일치: {result[0][1]!r}"
        assert "P0" in result[0][2], f"detail 불일치: {result[0][2]!r}"
