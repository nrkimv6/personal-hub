"""refactor: main.py 인라인 좀비 정리 중복 제거 TC

Phase T1: RIGHT-BICEP 기반 정적 검증
- R(Right): 인라인 블록 완전 제거 확인
- B(Boundary): 동기 Redis 클라이언트 직접 생성 금지 확인
- R(Right): browser_workers.py pubsub 플래그 판정 수정 확인
"""
import re


def _read_main_py() -> str:
    """app/main.py 소스 반환."""
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "app", "main.py")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_browser_workers_py() -> str:
    """scripts/services/browser_worker_runtime/manager.py 소스 반환."""
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "scripts", "services", "browser_worker_runtime", "manager.py")
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestMainNoInlineZombieCleanup:
    """main.py 인라인 좀비 정리 블록 제거 검증."""

    def test_main_no_inline_zombie_cleanup(self):
        """R(Right): lifespan에 _redis_sync 인라인 블록 없음."""
        src = _read_main_py()
        assert "_redis_sync" not in src, (
            "main.py에 인라인 좀비 정리 블록(_redis_sync)이 남아 있음. "
            "RedisCleanupScheduler로 대체되어야 함."
        )

    def test_main_no_inline_zombie_cleanup_no_sync_redis_import(self):
        """B(Boundary): main.py에서 redis.Redis(host= 직접 생성 패턴 없음."""
        src = _read_main_py()
        # 인라인 블록의 동기 Redis 직접 생성 패턴
        assert not re.search(r'redis\.Redis\(host=', src), (
            "main.py에 redis.Redis(host=... 직접 생성 코드가 남아 있음. "
            "RedisClient 싱글톤 또는 RedisCleanupScheduler를 사용해야 함."
        )


class TestBrowserWorkersPubsubFlagCheck:
    """browser_workers.py pubsub 플래그 판정 수정 검증."""

    def test_browser_workers_pubsub_flag_check(self):
        """R(Right): 'S' in flags 패턴 존재, startswith('S') 패턴 없음."""
        src = _read_browser_workers_py()

        # 수정된 패턴이 있어야 함
        assert '"S" in c.get("flags"' in src or '"S" in c.get(' in src, (
            "browser_worker_runtime/manager.py에 '\"S\" in flags' 패턴이 없음. "
            "pubsub_count 판정이 수정되지 않음."
        )

        # 구버전 패턴이 없어야 함
        assert 'startswith("S")' not in src, (
            "browser_worker_runtime/manager.py에 flags.startswith('S') 패턴이 남아 있음. "
            "'\"S\" in flags'로 변경되어야 함."
        )
