"""DiagnosticsService — 파이프라인 진단 (Redis 연결, heartbeat, 로그 파일, CLI 프로세스)"""

from pathlib import Path

import redis

from app.shared.redis.client import RedisClient

REDIS_HOST = "localhost"
REDIS_PORT = 6379
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"


class DiagnosticsService:
    """파이프라인 상태 진단 — 1회성 점검"""

    def __init__(self):
        sync_client = RedisClient.get_sync_client()
        self.redis_client = sync_client if sync_client is not None else redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=5,
        )

    def run_diagnostics(self) -> dict:
        """파이프라인 진단 (1회성) — 5단계 순차 점검"""
        steps = []

        # 1. Redis 연결
        try:
            self.redis_client.ping()
            steps.append({"step": 1, "name": "Redis 연결", "ok": True, "detail": "연결됨"})
        except Exception:
            steps.append({"step": 1, "name": "Redis 연결", "ok": False, "detail": "연결 실패"})
            return {"steps": steps}

        # 2. Redis 연결 수 확인
        try:
            info = self.redis_client.info("clients")
            clients = info.get("connected_clients", 0)
            ok = clients < 100
            steps.append({"step": 2, "name": "Redis 연결 수", "ok": ok,
                "detail": f"{clients}개 연결" + ("" if ok else " — 좀비 연결 의심 (redis-cleanup 실행 권장)")})
        except Exception:
            steps.append({"step": 2, "name": "Redis 연결 수", "ok": False, "detail": "조회 실패"})

        # 3. Listener heartbeat
        hb = self.redis_client.get("plan-runner:listener:heartbeat")
        steps.append({
            "step": 3, "name": "Listener heartbeat", "ok": hb is not None,
            "detail": "활성" if hb else "heartbeat 키 없음 (리스너 꺼짐)"
        })

        # 4. 로그 파일 — 첫 번째 active runner 기준
        log_path = None
        runner_ids = self.redis_client.smembers(ACTIVE_RUNNERS_KEY)
        if runner_ids:
            first_id = next(iter(runner_ids))
            log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{first_id}:stream_log_path")
            if not log_path:
                log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{first_id}:log_file_path")

        if log_path and Path(log_path).exists():
            size = Path(log_path).stat().st_size
            steps.append({
                "step": 4, "name": "로그 파일", "ok": True,
                "detail": f"{Path(log_path).name} ({size:,}B)"
            })
        elif log_path:
            steps.append({
                "step": 4, "name": "로그 파일", "ok": False,
                "detail": f"경로 있으나 파일 없음: {log_path}"
            })
        else:
            steps.append({
                "step": 4, "name": "로그 파일", "ok": False,
                "detail": "stream_log_path / log_file_path 키 없음"
            })

        # 5. CLI 프로세스 — active runners 수 기준
        if runner_ids:
            steps.append({"step": 5, "name": "CLI 프로세스", "ok": True, "detail": f"{len(runner_ids)} runner(s) active"})
        else:
            steps.append({
                "step": 5, "name": "CLI 프로세스", "ok": False,
                "detail": "미실행"
            })

        return {"steps": steps}


diagnostics_service = DiagnosticsService()

__all__ = ["diagnostics_service", "DiagnosticsService"]
