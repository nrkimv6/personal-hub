"""Legacy filename: real-server `http_live` SSE/log history integration tests.

GET /api/v1/dev-runner/logs/stream?runner_id=X 엔드포인트 검증
(실행: /merge-test, localhost:8001 실서버 + Redis 필요)
"""

import json
import threading
import time

import pytest
import redis
import requests

pytestmark = pytest.mark.http_live

ADMIN_API = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0


@pytest.fixture
def r_live():
    """실서버 테스트용 Redis 클라이언트"""
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield client
    client.close()


# ---------------------------------------------------------------------------
# T5-21: 초기 event: connected 이벤트 수신
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_connected_event():
    """T5: GET /logs/stream → 첫 이벤트가 event: connected, data: ok"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id=t5-test"
    try:
        with requests.get(url, stream=True, timeout=5) as resp:
            assert resp.status_code == 200
            event_type = None
            data_value = None
            for raw_line in resp.iter_lines(decode_unicode=True):
                if raw_line.startswith("event:"):
                    event_type = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    data_value = raw_line[5:].strip()
                    break
            assert event_type == "connected", f"첫 이벤트가 connected가 아님: {event_type}"
            assert data_value == "ok", f"data가 ok가 아님: {data_value}"
    except requests.exceptions.Timeout:
        pytest.skip("API server not responding")


# ---------------------------------------------------------------------------
# T5-22: heartbeat 수신 (30초 이내)
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_heartbeat():
    """T5: SSE 연결 후 35초 이내 ': heartbeat' 라인 수신"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id=t5-heartbeat"
    deadline = time.monotonic() + 35
    found_heartbeat = False
    try:
        with requests.get(url, stream=True, timeout=36) as resp:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if raw_line.strip() == ": heartbeat" or raw_line.strip() == ":heartbeat":
                    found_heartbeat = True
                    break
    except requests.exceptions.Timeout:
        pass
    assert found_heartbeat, "35초 내 heartbeat 수신 없음"


# ---------------------------------------------------------------------------
# T5-23: pub/sub publish → SSE data 라인 수신
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_data_delivery(r_live):
    """T5: Redis publish → SSE data: hello 수신"""
    runner_id = "t5-data-delivery"
    channel = f"plan-runner:logs:{runner_id}"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    received = []

    def publish_after_delay():
        time.sleep(1.5)
        for _ in range(3):
            r_live.publish(channel, "hello-t5")
            time.sleep(0.3)

    t = threading.Thread(target=publish_after_delay, daemon=True)
    t.start()

    deadline = time.monotonic() + 10
    try:
        with requests.get(url, stream=True, timeout=12) as resp:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if raw_line.startswith("data:"):
                    data = raw_line[5:].strip()
                    if data and data != "ok":
                        received.append(data)
                if received:
                    break
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        pass
    t.join(timeout=5)

    assert any("hello-t5" in d for d in received), \
        f"publish 메시지가 SSE에 전달되지 않음: {received}"


# ---------------------------------------------------------------------------
# T5-24: 전체 T5 실행 확인 (별도 실행 확인용 placeholder)
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_stream_endpoint_accessible():
    """T5-24: /logs/stream 엔드포인트 접근 가능 확인"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id=t5-accessible"
    try:
        with requests.get(url, stream=True, timeout=3) as resp:
            assert resp.status_code == 200
            # Content-Type이 text/event-stream인지 확인
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type, \
                f"Content-Type이 text/event-stream이 아님: {content_type}"
    except requests.exceptions.Timeout:
        pytest.skip("API server not responding")


# ---------------------------------------------------------------------------
# T5-30~33: 로그 이력/전체로그/recent HTTP 통합 (레거시 파일명 포함)
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_history_returns_valid_structure():
    """T5-30: GET /logs/history → 200 + runs 배열 포함 유효한 구조"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/history"
    try:
        resp = requests.get(url, timeout=5)
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}"
        data = resp.json()
        assert "runs" in data, f"runs 키 없음: {data.keys()}"
        assert isinstance(data["runs"], list), f"runs가 list가 아님"
        # lg- 접두사 pseudo runner_id가 있으면 유효한 형식인지 확인
        for run in data["runs"]:
            if run.get("runner_id", "").startswith("lg-"):
                assert len(run["runner_id"]) > 3, f"pseudo runner_id 형식 이상: {run['runner_id']}"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")


@pytest.mark.http_live
def test_http_log_full_legacy_pseudo_id():
    """T5-31: /history에 lg- pseudo runner_id 있으면 /full로 내용 읽기 성공"""
    try:
        history_resp = requests.get(f"{ADMIN_API}/api/v1/dev-runner/logs/history", timeout=5)
        if history_resp.status_code != 200:
            pytest.skip("history 엔드포인트 응답 없음")
        runs = history_resp.json().get("runs", [])
        lg_runs = [r for r in runs if r.get("runner_id", "").startswith("lg-")]
        if not lg_runs:
            pytest.skip("레거시 파일(lg- pseudo_id) 없음 — 스킵")

        pseudo_id = lg_runs[0]["runner_id"]
        full_resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/full",
            params={"runner_id": pseudo_id},
            timeout=5,
        )
        assert full_resp.status_code == 200, f"기대 200, 실제 {full_resp.status_code}"
        data = full_resp.json()
        assert "lines" in data, f"lines 키 없음"
        assert isinstance(data["lines"], list), f"lines가 list가 아님"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")


@pytest.mark.http_live
def test_http_log_recent_legacy_pseudo_id():
    """T5-32: /history에 lg- pseudo runner_id 있으면 /recent로 tail 성공"""
    try:
        history_resp = requests.get(f"{ADMIN_API}/api/v1/dev-runner/logs/history", timeout=5)
        if history_resp.status_code != 200:
            pytest.skip("history 엔드포인트 응답 없음")
        runs = history_resp.json().get("runs", [])
        lg_runs = [r for r in runs if r.get("runner_id", "").startswith("lg-")]
        if not lg_runs:
            pytest.skip("레거시 파일(lg- pseudo_id) 없음 — 스킵")

        pseudo_id = lg_runs[0]["runner_id"]
        recent_resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/recent",
            params={"runner_id": pseudo_id},
            timeout=5,
        )
        assert recent_resp.status_code == 200, f"기대 200, 실제 {recent_resp.status_code}"
        data = recent_resp.json()
        assert "lines" in data, f"lines 키 없음"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")


@pytest.mark.http_live
def test_http_log_full_nonexist_runner():
    """T5-33: GET /full?runner_id=nonexist → 200 + 빈 lines"""
    try:
        resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/full",
            params={"runner_id": "nonexist"},
            timeout=5,
        )
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}"
        data = resp.json()
        assert data.get("lines") == [], f"빈 lines가 아님: {data.get('lines')}"
        assert data.get("total_lines") == 0, f"total_lines가 0이 아님: {data.get('total_lines')}"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")


# ---------------------------------------------------------------------------
# T5 신규: from_line 필드 + since_line 파라미터 + small stream 파일
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_log_recent_returns_from_line():
    """T5: GET /logs/recent → 응답에 from_line 필드 포함"""
    import tempfile, os
    from pathlib import Path

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        r.ping()
    except Exception:
        pytest.skip("Redis not available")

    runner_id = "t5-from-line-test"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        for i in range(200):
            f.write(f"[12:00:00] [INFO] line {i}\n")
        log_path = f.name

    try:
        r.set(f"plan-runner:runners:{runner_id}:stream_log_path", log_path)
        resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/recent",
            params={"runner_id": runner_id, "lines": 100},
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "from_line" in data, f"from_line 필드 없음: {data.keys()}"
        assert data["from_line"] == 100, f"from_line 기대 100, 실제 {data['from_line']}"
        assert len(data["lines"]) == 100
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")
    finally:
        r.delete(f"plan-runner:runners:{runner_id}:stream_log_path")
        r.close()
        try:
            os.unlink(log_path)
        except Exception:
            pass


@pytest.mark.http_live
def test_http_log_stream_since_line_param():
    """T5: GET /logs/stream?since_line=N → SSE에서 N+1번째 줄부터 수신"""
    import tempfile, os

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        r.ping()
    except Exception:
        pytest.skip("Redis not available")

    runner_id = "t5-since-line-test"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        for i in range(100):
            f.write(f"[12:00:00] [INFO] line {i}\n")
        log_path = f.name

    try:
        r.set(f"plan-runner:runners:{runner_id}:stream_log_path", log_path)
        # since_line=95 → 95번 이후(96~99, 4줄)만 버퍼로 수신 후 completed 이벤트 기다림
        # 완료 신호가 없으므로 짧은 timeout으로 첫 줄만 확인
        resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/stream",
            params={"runner_id": runner_id, "since_line": 95},
            stream=True,
            timeout=5,
        )
        assert resp.status_code == 200
        lines_received = []
        current_event = None
        for raw_line in resp.iter_lines(decode_unicode=True):
            if raw_line.startswith("event:"):
                current_event = raw_line[6:].strip()
            elif raw_line.startswith("data:"):
                if current_event != "connected":  # connected 이벤트 data: ok 제외
                    lines_received.append(raw_line[5:].strip())
                current_event = None
            else:
                current_event = None
            if len(lines_received) >= 1:
                break
        resp.close()

        assert len(lines_received) >= 1, "since_line=95 이후 줄 수신 없음"
        # 첫 수신 줄은 line 95부터
        assert "line 95" in lines_received[0], f"첫 줄이 line 95가 아님: {lines_received[0]}"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")
    finally:
        r.delete(f"plan-runner:runners:{runner_id}:stream_log_path")
        r.close()
        try:
            os.unlink(log_path)
        except Exception:
            pass


@pytest.mark.http_live
def test_http_log_recent_small_stream_file():
    """T5: stream_log_path 50B여도 해당 파일 내용 반환 (200B 기준 제거 검증)"""
    import tempfile, os

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        r.ping()
    except Exception:
        pytest.skip("Redis not available")

    runner_id = "t5-small-stream-test"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as sf:
        sf.write("[START] marker\n")  # ~17B
        stream_path = sf.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as lf:
        for i in range(10):
            lf.write(f"[12:00:00] [INFO] old line {i}\n")
        log_path = lf.name

    try:
        r.set(f"plan-runner:runners:{runner_id}:stream_log_path", stream_path)
        r.set(f"plan-runner:runners:{runner_id}:log_file_path", log_path)

        resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/recent",
            params={"runner_id": runner_id, "lines": 10},
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        # stream 파일 내용만 반환돼야 함 (old line이 없어야 함)
        combined = " ".join(data.get("lines", []))
        assert "old line" not in combined, f"이전 실행 로그가 반환됨: {combined[:100]}"
        assert "START" in combined or len(data["lines"]) == 0, f"stream 파일 내용 아님: {combined[:100]}"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")
    finally:
        r.delete(f"plan-runner:runners:{runner_id}:stream_log_path")
        r.delete(f"plan-runner:runners:{runner_id}:log_file_path")
        r.close()
        try:
            os.unlink(stream_path)
            os.unlink(log_path)
        except Exception:
            pass


@pytest.mark.http_live
def test_http_log_recent_legacy_pseudo_id_after_size_removal():
    """T5: stream-filename-mismatch T5 재실행 — 200B 기준 제거 후 레거시 pseudo runner_id 동작 유지"""
    import tempfile, os, hashlib

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        r.ping()
    except Exception:
        pytest.skip("Redis not available")

    # 레거시 파일 생성 (runner_id 없는 형식) — log_service에서 직접 확인
    log_dir = None
    try:
        import sys, os as _os
        sys.path.insert(0, "D:/work/project/tools/monitor-page")
        _orig = _os.getcwd()
        _os.chdir("D:/work/project/tools/monitor-page")
        from app.modules.dev_runner.services.log_service import log_service as _ls
        log_dir = str(_ls._get_log_dir())
        _os.chdir(_orig)
    except Exception as e:
        pytest.skip(f"log_dir 확인 불가: {e}")

    if not log_dir:
        pytest.skip("log_dir 확인 불가")

    ts = "20260101_120000"
    legacy_filename = f"plan-runner-stream-{ts}.log"
    legacy_path = os.path.join(log_dir, legacy_filename)
    pseudo_id = f"lg-{hashlib.md5(ts.encode()).hexdigest()[:5]}"

    try:
        with open(legacy_path, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(f"[12:00:00] [INFO] legacy line {i}\n")

        # history에서 pseudo_id 확인
        hist_resp = requests.get(f"{ADMIN_API}/api/v1/dev-runner/logs/history", timeout=5)
        assert hist_resp.status_code == 200
        runs = hist_resp.json().get("runs", [])
        found = any(r_item["runner_id"] == pseudo_id for r_item in runs)
        assert found, f"레거시 파일 이력에 없음. pseudo_id={pseudo_id}, runs={[r['runner_id'] for r in runs[:5]]}"

        # recent로 조회
        recent_resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/recent",
            params={"runner_id": pseudo_id},
            timeout=5,
        )
        assert recent_resp.status_code == 200
        data = recent_resp.json()
        assert len(data["lines"]) > 0, "레거시 파일 recent 응답이 빈 lines"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")
    finally:
        try:
            os.unlink(legacy_path)
        except Exception:
            pass


@pytest.mark.http_live
def test_http_log_recent_codex_runtime_failure_signature():
    """T5: logs/recent가 codex runtime 실패 시그니처(xhigh/model_reasoning_effort)를 노출한다."""
    import tempfile
    import os

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        r.ping()
    except Exception:
        pytest.skip("Redis not available")

    runner_id = "t5-codex-runtime-failure"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("[09:50:53] [ERROR] Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`\n")
        f.write("[09:50:53] [ERROR] in `model_reasoning_effort`\n")
        log_path = f.name

    try:
        r.set(f"plan-runner:runners:{runner_id}:stream_log_path", log_path)
        resp = requests.get(
            f"{ADMIN_API}/api/v1/dev-runner/logs/recent",
            params={"runner_id": runner_id},
            timeout=5,
        )
        assert resp.status_code == 200
        lines = resp.json().get("lines", [])
        merged = "\n".join(lines)
        assert "unknown variant `xhigh`" in merged
        assert "model_reasoning_effort" in merged
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")
    finally:
        r.delete(f"plan-runner:runners:{runner_id}:stream_log_path")
        r.close()
        try:
            os.unlink(log_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# T5 신규: visible_only 파라미터 + /full 청크 응답 구조 검증
# ---------------------------------------------------------------------------

@pytest.mark.http_live
def test_http_logs_history_visible_only_true():
    """T5-40: GET /logs/history?visible_only=true → 200 + runs 배열 반환"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/history?visible_only=true"
    try:
        resp = requests.get(url, timeout=5)
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}"
        data = resp.json()
        assert "runs" in data, f"runs 키 없음: {data.keys()}"
        assert isinstance(data["runs"], list), "runs가 list가 아님"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")


@pytest.mark.http_live
def test_http_logs_history_visible_only_default_false():
    """T5-41: GET /logs/history (파라미터 없음) → 200 + runs 배열 반환 (visible_only=False 기본값)"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/history"
    try:
        resp = requests.get(url, timeout=5)
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}"
        data = resp.json()
        assert "runs" in data, f"runs 키 없음: {data.keys()}"
        assert isinstance(data["runs"], list), "runs가 list가 아님"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")


@pytest.mark.http_live
def test_http_logs_full_chunk_response():
    """T5-42: GET /logs/full?runner_id=test123 → 200 + lines, has_more, total_lines, offset 필드 존재"""
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/full?runner_id=nonexist-t5-42"
    try:
        resp = requests.get(url, timeout=5)
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}"
        data = resp.json()
        assert "lines" in data, f"lines 키 없음: {data.keys()}"
        assert "has_more" in data, f"has_more 키 없음: {data.keys()}"
        assert "total_lines" in data, f"total_lines 키 없음: {data.keys()}"
        assert "offset" in data, f"offset 키 없음: {data.keys()}"
    except requests.exceptions.ConnectionError:
        pytest.skip("API server not responding")
    except requests.exceptions.Timeout:
        pytest.skip("API server timeout")
