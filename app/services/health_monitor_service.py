"""
서비스 헬스 모니터링 서비스

PID+포트 체크 (10초 간격)와 HTTP 헬스체크 (60초 간격)를 수행하여
서비스 상태를 모니터링하고 장애 발생 시 텔레그램 알림을 발송합니다.
"""

import asyncio
import time
import logging
from enum import Enum
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
import psutil

from app.core.config import settings

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """서비스 상태"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class CheckType(Enum):
    """체크 유형"""
    PID_PORT = "pid_port"
    HTTP = "http"


@dataclass
class ServiceHealth:
    """서비스 헬스 상태 정보"""
    name: str
    status: ServiceStatus
    last_check: datetime
    failure_count: int
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    # PID 체크용 추가 필드
    pid: Optional[int] = None
    expected_port: Optional[int] = None
    actual_port_owner: Optional[int] = None

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "name": self.name,
            "status": self.status.value,
            "last_check": self.last_check.isoformat(),
            "failure_count": self.failure_count,
            "response_time_ms": self.response_time_ms,
            "error_message": self.error_message,
            "pid": self.pid,
            "expected_port": self.expected_port,
            "actual_port_owner": self.actual_port_owner,
        }


@dataclass
class RecentAlert:
    """최근 알림 정보"""
    timestamp: datetime
    alert_type: str  # "failure" | "recovery"
    service: str
    message: str
    check_type: str  # "PID" | "HTTP"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.alert_type,
            "service": self.service,
            "message": self.message,
            "check_type": self.check_type,
        }


# 서비스별 PID 파일과 예상 포트 매핑
# process_name이 있으면 PID 파일 대신 프로세스 이름으로 직접 찾음 (Windows 서비스용)
# expected_process: PID 파일의 프로세스가 이 이름인지 검증 (잘못된 PID 감지용)
SERVICE_CONFIG = {
    "api": {"pid_file": "api.pid", "port": 8000, "expected_process": "python"},
    "api_dev": {"pid_file": "api_dev.pid", "port": 8001, "expected_process": "python"},
    "frontend": {"pid_file": "frontend.pid", "port": 5173, "expected_process": "node"},
    "frontend_dev": {"pid_file": "frontend_dev.pid", "port": 5174, "expected_process": "node"},
    "worker": {"pid_file": "unified_worker.pid", "port": None, "expected_process": "python"},
    "worker_dev": {"pid_file": "unified_worker_dev.pid", "port": None, "expected_process": "python"},
    "cloudflared": {"process_name": "cloudflared", "port": None},  # Windows 서비스로 관리됨
}


class HealthMonitorService:
    """서비스 헬스 모니터링 서비스"""

    def __init__(self, notification_service=None):
        """
        Args:
            notification_service: NotificationService 인스턴스 (알림 발송용)
        """
        self.pid_dir = Path(settings.PID_DIR)
        self.services: dict[str, ServiceHealth] = {}
        self.notification_service = notification_service
        self.recent_alerts: list[RecentAlert] = []
        self._max_alerts = 50  # 최근 알림 최대 저장 개수

    def read_pid_file(self, service_name: str) -> Optional[int]:
        """PID 파일에서 PID 읽기"""
        config = SERVICE_CONFIG.get(service_name)
        if not config:
            return None

        pid_file = self.pid_dir / config["pid_file"]
        if not pid_file.exists():
            return None

        try:
            return int(pid_file.read_text().strip())
        except (ValueError, IOError) as e:
            logger.debug(f"PID 파일 읽기 실패 ({service_name}): {e}")
            return None

    def check_process_exists(self, pid: int, expected_name: str = None) -> bool:
        """PID가 실제로 실행 중인지 확인

        Args:
            pid: 확인할 프로세스 ID
            expected_name: 예상 프로세스 이름 (예: 'python'). None이면 이름 검증 생략
        """
        try:
            process = psutil.Process(pid)
            if not process.is_running():
                return False

            # 프로세스 이름 검증 (worker가 실제 python인지 확인)
            if expected_name:
                proc_name = process.name().lower()
                # python.exe 또는 python3.exe 등
                if expected_name.lower() not in proc_name:
                    logger.debug(f"PID {pid} is {proc_name}, expected {expected_name}")
                    return False

            return True
        except psutil.NoSuchProcess:
            return False

    def find_process_by_name(self, process_name: str) -> Optional[int]:
        """프로세스 이름으로 PID 찾기 (Windows 서비스용)"""
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and proc.info['name'].lower() == f"{process_name}.exe".lower():
                    return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return None

    def get_port_owner(self, port: int) -> Optional[int]:
        """특정 포트를 점유하고 있는 PID 반환"""
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port == port and conn.status == 'LISTEN':
                    return conn.pid
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        return None

    def is_descendant_of(self, child_pid: int, ancestor_pid: int) -> bool:
        """child_pid가 ancestor_pid의 자식/자손인지 확인 (핫 리로드 감지용)"""
        try:
            process = psutil.Process(child_pid)
            # 최대 5단계까지 부모 추적 (무한 루프 방지)
            for _ in range(5):
                parent_pid = process.ppid()
                if parent_pid == 0:
                    break
                if parent_pid == ancestor_pid:
                    return True
                process = psutil.Process(parent_pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return False

    def check_pid_and_port(self, service_name: str) -> ServiceHealth:
        """PID 파일과 포트 점유 상태 확인"""
        config = SERVICE_CONFIG.get(service_name)
        if not config:
            return ServiceHealth(
                name=service_name,
                status=ServiceStatus.UNKNOWN,
                last_check=datetime.now(),
                failure_count=0,
                error_message="Unknown service"
            )

        expected_port = config.get("port")

        # process_name이 설정된 경우 (Windows 서비스): 프로세스 이름으로 직접 찾기
        if "process_name" in config:
            process_name = config["process_name"]
            found_pid = self.find_process_by_name(process_name)
            if found_pid:
                return ServiceHealth(
                    name=service_name,
                    status=ServiceStatus.HEALTHY,
                    last_check=datetime.now(),
                    failure_count=0,
                    error_message=None,
                    pid=found_pid,
                    expected_port=expected_port
                )
            else:
                return ServiceHealth(
                    name=service_name,
                    status=ServiceStatus.UNHEALTHY,
                    last_check=datetime.now(),
                    failure_count=self._get_failure_count(service_name) + 1,
                    error_message=f"Process '{process_name}' not running",
                    pid=None,
                    expected_port=expected_port
                )

        # PID 파일 기반 체크
        saved_pid = self.read_pid_file(service_name)
        expected_process = config.get("expected_process")

        # 1. PID 파일 없음
        if saved_pid is None:
            return ServiceHealth(
                name=service_name,
                status=ServiceStatus.UNHEALTHY,
                last_check=datetime.now(),
                failure_count=self._get_failure_count(service_name) + 1,
                error_message="PID file not found",
                pid=None,
                expected_port=expected_port
            )

        # 2. 프로세스 존재 및 이름 확인 (잘못된 PID 감지)
        process_name_matches = self.check_process_exists(saved_pid, expected_process)
        process_exists = self.check_process_exists(saved_pid, None)  # 이름 무관하게 존재 여부만

        # 프로세스가 아예 없으면 실패
        if not process_exists:
            return ServiceHealth(
                name=service_name,
                status=ServiceStatus.UNHEALTHY,
                last_check=datetime.now(),
                failure_count=self._get_failure_count(service_name) + 1,
                error_message=f"Process {saved_pid} not running",
                pid=saved_pid,
                expected_port=expected_port
            )

        # 3. 포트가 있는 서비스면 포트 점유 확인
        if expected_port:
            actual_owner = self.get_port_owner(expected_port)

            if actual_owner is None:
                return ServiceHealth(
                    name=service_name,
                    status=ServiceStatus.UNHEALTHY,
                    last_check=datetime.now(),
                    failure_count=self._get_failure_count(service_name) + 1,
                    error_message=f"Port {expected_port} not in use",
                    pid=saved_pid,
                    expected_port=expected_port,
                    actual_port_owner=None
                )

            # 포트가 LISTENING 상태면 서비스 정상으로 판단
            # (PID 파일과 실제 프로세스가 다를 수 있음 - 서비스 재시작 등)
            if actual_owner == saved_pid or self.is_descendant_of(actual_owner, saved_pid):
                # PID 일치 또는 자식 프로세스
                logger.debug(
                    f"{service_name}: port {expected_port} owned by PID {actual_owner} "
                    f"(saved: {saved_pid}, match or descendant)"
                )
            else:
                # PID 불일치지만 포트가 열려있음 - 서비스는 동작 중
                logger.debug(
                    f"{service_name}: port {expected_port} owned by PID {actual_owner} "
                    f"(saved: {saved_pid}, different but service running)"
                )

            # 포트가 열려있으면 정상
            return ServiceHealth(
                name=service_name,
                status=ServiceStatus.HEALTHY,
                last_check=datetime.now(),
                failure_count=0,
                error_message=None,
                pid=saved_pid,
                expected_port=expected_port,
                actual_port_owner=actual_owner
            )

        # 모든 체크 통과
        return ServiceHealth(
            name=service_name,
            status=ServiceStatus.HEALTHY,
            last_check=datetime.now(),
            failure_count=0,
            error_message=None,
            pid=saved_pid,
            expected_port=expected_port,
            actual_port_owner=saved_pid if expected_port else None
        )

    async def check_all_pid_ports(self) -> list[ServiceHealth]:
        """모든 서비스의 PID+포트 체크"""
        results = []
        for service_name in SERVICE_CONFIG:
            # 현재 모드에 따라 체크 대상 필터링
            if settings.APP_MODE == "development":
                if not service_name.endswith("_dev") and service_name not in ["cloudflared"]:
                    continue
            else:
                if service_name.endswith("_dev"):
                    continue

            health = self.check_pid_and_port(service_name)
            results.append(health)
        return results

    def _get_failure_count(self, name: str) -> int:
        """서비스의 현재 실패 횟수 조회"""
        if name in self.services:
            return self.services[name].failure_count
        return 0

    async def check_http_endpoint(
        self,
        name: str,
        url: str,
        expected_status: int = 200
    ) -> ServiceHealth:
        """HTTP 엔드포인트 헬스 체크"""
        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=settings.HEALTH_CHECK_TIMEOUT)
                ) as response:
                    elapsed = (time.time() - start) * 1000

                    if response.status == expected_status:
                        return ServiceHealth(
                            name=name,
                            status=ServiceStatus.HEALTHY,
                            last_check=datetime.now(),
                            failure_count=0,
                            response_time_ms=elapsed,
                            error_message=None
                        )
                    else:
                        return ServiceHealth(
                            name=name,
                            status=ServiceStatus.UNHEALTHY,
                            last_check=datetime.now(),
                            failure_count=self._get_failure_count(name) + 1,
                            response_time_ms=elapsed,
                            error_message=f"HTTP {response.status}"
                        )
        except asyncio.TimeoutError:
            return ServiceHealth(
                name=name,
                status=ServiceStatus.UNHEALTHY,
                last_check=datetime.now(),
                failure_count=self._get_failure_count(name) + 1,
                response_time_ms=None,
                error_message="Connection timeout"
            )
        except Exception as e:
            return ServiceHealth(
                name=name,
                status=ServiceStatus.UNHEALTHY,
                last_check=datetime.now(),
                failure_count=self._get_failure_count(name) + 1,
                response_time_ms=None,
                error_message=str(e)
            )

    async def check_worker_health(self) -> ServiceHealth:
        """워커 헬스 체크 (API 경유)"""
        port = 8001 if settings.APP_MODE == "development" else 8000
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://localhost:{port}/api/v1/worker/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    data = await response.json()
                    is_healthy = data.get("is_healthy", False)

                    if is_healthy:
                        return ServiceHealth(
                            name="worker_http",
                            status=ServiceStatus.HEALTHY,
                            last_check=datetime.now(),
                            failure_count=0,
                            error_message=None
                        )
                    else:
                        return ServiceHealth(
                            name="worker_http",
                            status=ServiceStatus.UNHEALTHY,
                            last_check=datetime.now(),
                            failure_count=self._get_failure_count("worker_http") + 1,
                            error_message=data.get("details", {}).get("error", "Worker unhealthy")
                        )
        except Exception as e:
            return ServiceHealth(
                name="worker_http",
                status=ServiceStatus.UNHEALTHY,
                last_check=datetime.now(),
                failure_count=self._get_failure_count("worker_http") + 1,
                error_message=str(e)
            )

    async def check_all_http_endpoints(self) -> list[ServiceHealth]:
        """모든 서비스 HTTP 헬스 체크"""
        port = 8001 if settings.APP_MODE == "development" else 8000
        frontend_port = 5174 if settings.APP_MODE == "development" else 5173

        checks = [
            self.check_http_endpoint("api_internal", f"http://localhost:{port}/api/v1/system/status"),
            self.check_http_endpoint("frontend_internal", f"http://localhost:{frontend_port}/"),
            self.check_worker_health(),
        ]

        # 외부 URL이 설정된 경우만 체크
        if settings.EXTERNAL_API_URL:
            checks.append(
                self.check_http_endpoint("api_external", f"{settings.EXTERNAL_API_URL}/api/v1/system/status")
            )
        if settings.EXTERNAL_FRONTEND_URL:
            checks.append(
                self.check_http_endpoint("frontend_external", settings.EXTERNAL_FRONTEND_URL)
            )

        results = await asyncio.gather(*checks, return_exceptions=True)
        return [r for r in results if isinstance(r, ServiceHealth)]

    def _add_alert(self, alert: RecentAlert):
        """최근 알림 목록에 추가"""
        self.recent_alerts.insert(0, alert)
        if len(self.recent_alerts) > self._max_alerts:
            self.recent_alerts = self.recent_alerts[:self._max_alerts]

    async def _send_pid_failure_alert(self, health: ServiceHealth):
        """PID/포트 장애 알림 발송"""
        message = f"""🔴 <b>프로세스 장애 감지</b>

<b>서비스:</b> {health.name}
<b>오류:</b> {health.error_message}
<b>저장된 PID:</b> {health.pid or 'N/A'}
<b>예상 포트:</b> {health.expected_port or 'N/A'}
<b>실제 포트 점유:</b> {health.actual_port_owner or 'N/A'}
<b>시간:</b> {health.last_check.strftime('%Y-%m-%d %H:%M:%S')}"""

        self._add_alert(RecentAlert(
            timestamp=datetime.now(),
            alert_type="failure",
            service=health.name,
            message=health.error_message or "Unknown error",
            check_type="PID"
        ))

        if self.notification_service:
            await self.notification_service.send_telegram(message, force_send=True)
        else:
            logger.warning(f"PID 장애 감지 (알림 서비스 없음): {health.name} - {health.error_message}")

    async def _send_http_failure_alert(self, health: ServiceHealth):
        """HTTP 장애 알림 발송"""
        message = f"""🟠 <b>서비스 응답 없음</b>

<b>서비스:</b> {health.name}
<b>오류:</b> {health.error_message}
<b>연속 실패:</b> {health.failure_count}회
<b>시간:</b> {health.last_check.strftime('%Y-%m-%d %H:%M:%S')}"""

        self._add_alert(RecentAlert(
            timestamp=datetime.now(),
            alert_type="failure",
            service=health.name,
            message=health.error_message or "Unknown error",
            check_type="HTTP"
        ))

        if self.notification_service:
            await self.notification_service.send_telegram(message, force_send=True)
        else:
            logger.warning(f"HTTP 장애 감지 (알림 서비스 없음): {health.name} - {health.error_message}")

    async def _send_recovery_alert(self, health: ServiceHealth, check_type: str):
        """복구 알림 발송"""
        if not settings.HEALTH_RECOVERY_NOTIFY:
            return

        response_info = ""
        if health.response_time_ms:
            response_info = f"\n<b>응답 시간:</b> {health.response_time_ms:.0f}ms"

        message = f"""🟢 <b>서비스 복구</b>

<b>서비스:</b> {health.name}
<b>체크 유형:</b> {check_type}{response_info}
<b>시간:</b> {health.last_check.strftime('%Y-%m-%d %H:%M:%S')}"""

        self._add_alert(RecentAlert(
            timestamp=datetime.now(),
            alert_type="recovery",
            service=health.name,
            message="서비스 복구",
            check_type=check_type
        ))

        if self.notification_service:
            await self.notification_service.send_telegram(message, force_send=True)
        else:
            logger.info(f"서비스 복구 (알림 서비스 없음): {health.name}")

    async def run_monitor_loop(self):
        """메인 모니터링 루프 (2단계 체크)"""
        loop_count = 0
        http_check_every = settings.HEALTH_HTTP_CHECK_INTERVAL // settings.HEALTH_PID_CHECK_INTERVAL

        logger.info(f"헬스 모니터 시작 (PID 체크: {settings.HEALTH_PID_CHECK_INTERVAL}초, HTTP 체크: {settings.HEALTH_HTTP_CHECK_INTERVAL}초)")

        while True:
            try:
                loop_count += 1

                # 1차: PID + 포트 체크 (매 루프)
                pid_results = await self.check_all_pid_ports()
                for health in pid_results:
                    prev = self.services.get(health.name)
                    self.services[health.name] = health

                    # PID 체크도 threshold 적용 (연속 N회 실패 시 알림)
                    if (health.status == ServiceStatus.UNHEALTHY
                        and health.failure_count == settings.HEALTH_FAILURE_THRESHOLD):
                        await self._send_pid_failure_alert(health)

                    # 복구 알림
                    if (prev and prev.status == ServiceStatus.UNHEALTHY
                        and health.status == ServiceStatus.HEALTHY):
                        await self._send_recovery_alert(health, "PID")

                # 2차: HTTP 체크 (N번째 루프마다)
                if loop_count % http_check_every == 0:
                    http_results = await self.check_all_http_endpoints()
                    for health in http_results:
                        prev = self.services.get(health.name)
                        self.services[health.name] = health

                        # HTTP 체크는 threshold 적용
                        if (health.status == ServiceStatus.UNHEALTHY
                            and health.failure_count == settings.HEALTH_FAILURE_THRESHOLD):
                            await self._send_http_failure_alert(health)

                        # 복구 알림
                        if (prev and prev.status == ServiceStatus.UNHEALTHY
                            and health.status == ServiceStatus.HEALTHY):
                            await self._send_recovery_alert(health, "HTTP")

            except Exception as e:
                logger.error(f"Health monitor error: {e}")

            await asyncio.sleep(settings.HEALTH_PID_CHECK_INTERVAL)

    def get_all_services_status(self) -> dict:
        """모든 서비스 상태 반환 (API용)"""
        return {
            name: health.to_dict()
            for name, health in self.services.items()
        }

    def get_recent_alerts(self, limit: int = 10) -> list[dict]:
        """최근 알림 목록 반환 (API용)"""
        return [alert.to_dict() for alert in self.recent_alerts[:limit]]
