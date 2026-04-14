"""
Heartbeat Redis 키 불일치 수정 TC

Phase T1 / T3: RIGHT-BICEP 원칙 적용
- 수정 전: self.name("naver_monitor", "scheduled_worker", "ondemand_worker")로 publish
- 수정 후: API check 키("naver", "scheduled", "ondemand")로 publish
"""
import sys
import pytest
import fakeredis
from pathlib import Path
from unittest.mock import patch, MagicMock

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.shared.worker.health_redis import WorkerHealthRedis, HEALTH_KEY_PREFIX


# ============================================================
# 공통 픽스처
# ============================================================

@pytest.fixture
def fake_redis():
    """fakeredis 인스턴스를 WorkerHealthRedis에 주입한다."""
    client = fakeredis.FakeRedis(decode_responses=False)
    with patch("app.shared.worker.health_redis.RedisClient.get_sync_client", return_value=client):
        yield client
    client.flushall()


# ============================================================
# Phase T1: NaverMonitor heartbeat 키 검증
# ============================================================

class TestNaverMonitorHeartbeatKey:
    """NaverMonitorWorker._update_heartbeat() → "naver" 키 publish 검증"""

    def test_naver_monitor_publishes_naver_key_right(self, fake_redis):
        """[Right] NaverMonitorWorker._update_heartbeat() 호출 → "naver" 키 publish됨."""
        from app.worker.naver_monitor_worker import NaverMonitorWorker

        worker = NaverMonitorWorker(browser_manager=None)
        worker._update_heartbeat()

        result = WorkerHealthRedis.check("naver")
        assert result is not None, '"naver" 키가 Redis에 없음 — publish 키 불일치'
        assert result["source"] == "redis"
        assert result["pid"] == worker.pid

    def test_naver_monitor_does_not_publish_naver_monitor_key_boundary(self, fake_redis):
        """[Boundary] NaverMonitorWorker._update_heartbeat() 호출 후 "naver_monitor" 키는 없어야 함."""
        from app.worker.naver_monitor_worker import NaverMonitorWorker

        worker = NaverMonitorWorker(browser_manager=None)
        worker._update_heartbeat()

        # "naver_monitor" 키는 publish되면 안 됨 (수정 전 버그 키)
        stale_key = f"{HEALTH_KEY_PREFIX}naver_monitor"
        assert fake_redis.get(stale_key) is None, \
            '"naver_monitor" 키가 Redis에 남아 있음 — self.name 사용이 제거되지 않았음'


# ============================================================
# Phase T1: CrawlWorker heartbeat 키 검증
# ============================================================

class TestCrawlWorkerHeartbeatKey:
    """CrawlWorkerBase 서브클래스의 _update_heartbeat() → worker_type 키 publish 검증"""

    def test_scheduled_worker_publishes_scheduled_key_right(self, fake_redis):
        """[Right] ScheduledCrawlWorker._update_heartbeat() → "scheduled" 키 publish됨."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker(browser_manager=None)
        worker._update_heartbeat()

        result = WorkerHealthRedis.check("scheduled")
        assert result is not None, '"scheduled" 키가 Redis에 없음 — publish 키 불일치'
        assert result["source"] == "redis"
        assert result["pid"] == worker.pid

    def test_scheduled_worker_does_not_publish_scheduled_worker_key(self, fake_redis):
        """[Boundary] ScheduledCrawlWorker 호출 후 "scheduled_worker" 키는 없어야 함."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker(browser_manager=None)
        worker._update_heartbeat()

        stale_key = f"{HEALTH_KEY_PREFIX}scheduled_worker"
        assert fake_redis.get(stale_key) is None, \
            '"scheduled_worker" 키가 Redis에 남아 있음'

    def test_ondemand_worker_publishes_ondemand_key_right(self, fake_redis):
        """[Right] OnDemandCrawlWorker._update_heartbeat() → "ondemand" 키 publish됨."""
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        worker = OnDemandCrawlWorker(browser_manager=None)
        worker._update_heartbeat()

        result = WorkerHealthRedis.check("ondemand")
        assert result is not None, '"ondemand" 키가 Redis에 없음 — publish 키 불일치'
        assert result["source"] == "redis"
        assert result["pid"] == worker.pid

    def test_ondemand_worker_does_not_publish_ondemand_worker_key(self, fake_redis):
        """[Boundary] OnDemandCrawlWorker 호출 후 "ondemand_worker" 키는 없어야 함."""
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        worker = OnDemandCrawlWorker(browser_manager=None)
        worker._update_heartbeat()

        stale_key = f"{HEALTH_KEY_PREFIX}ondemand_worker"
        assert fake_redis.get(stale_key) is None, \
            '"ondemand_worker" 키가 Redis에 남아 있음'

    def test_activity_worker_publishes_activity_key_boundary(self, fake_redis):
        """[Boundary] ActivityWorker._update_heartbeat() → "activity" 키 publish됨.

        ActivityWorker.worker_type = "activity" (KNOWN_WORKER_TYPES 외)이지만
        publish 자체는 정상 동작해야 한다.
        """
        from app.worker.activity_worker import ActivityWorker

        worker = ActivityWorker(browser_manager=None)
        worker._update_heartbeat()

        result = WorkerHealthRedis.check("activity")
        assert result is not None, '"activity" 키가 Redis에 없음'
        assert result["source"] == "redis"
        assert result["pid"] == worker.pid


# ============================================================
# Phase T3: 재현/통합 TC (키 불일치 재현 + 수정 확인)
# ============================================================

class TestHeartbeatKeyIntegration:
    """키 불일치 재현 통합 TC — fakeredis + 실제 워커 인스턴스"""

    def test_worker_publish_key_matches_api_check_key_integration(self, fake_redis):
        """[Integration] NaverMonitorWorker publish 키 == API check 키.

        "naver" 키 존재 + "naver_monitor" 키 없음 동시 확인.
        """
        from app.worker.naver_monitor_worker import NaverMonitorWorker

        worker = NaverMonitorWorker(browser_manager=None)
        worker._update_heartbeat()

        # "naver" 키 있어야 함
        good = WorkerHealthRedis.check("naver")
        assert good is not None
        assert good["source"] == "redis"

        # "naver_monitor" 키 없어야 함
        bad = WorkerHealthRedis.check("naver_monitor")
        assert bad is None, "수정 전 버그 키 naver_monitor 가 여전히 publish되고 있음"

    def test_crawl_worker_publish_key_matches_api_check_key_integration(self, fake_redis):
        """[Integration] ScheduledCrawlWorker publish 키 == API check 키."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker(browser_manager=None)
        worker._update_heartbeat()

        good = WorkerHealthRedis.check("scheduled")
        assert good is not None
        assert good["source"] == "redis"

        bad = WorkerHealthRedis.check("scheduled_worker")
        assert bad is None, "수정 전 버그 키 scheduled_worker 가 여전히 publish되고 있음"

    def test_ondemand_worker_publish_key_integration(self, fake_redis):
        """[Integration] OnDemandCrawlWorker publish 키 == API check 키."""
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        worker = OnDemandCrawlWorker(browser_manager=None)
        worker._update_heartbeat()

        good = WorkerHealthRedis.check("ondemand")
        assert good is not None
        assert good["source"] == "redis"

        bad = WorkerHealthRedis.check("ondemand_worker")
        assert bad is None, "수정 전 버그 키 ondemand_worker 가 여전히 publish되고 있음"
