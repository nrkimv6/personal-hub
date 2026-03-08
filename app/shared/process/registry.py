"""Redis 기반 프로세스 레지스트리.

프로세스 트리 정보를 Redis HASH/SET으로 관리합니다.
Redis 미연결 시 graceful degradation (에러 대신 경고 로그).
"""
import logging
from datetime import datetime
from typing import Optional

from app.shared.redis.client import RedisClient

logger = logging.getLogger(__name__)


class ProcessRegistry:
    """Redis HASH/SET으로 프로세스 등록/조회/해제를 관리하는 클래스."""

    async def register(
        self,
        pid: int,
        ppid: int,
        name: str,
        exe: str,
        role: str,
    ) -> bool:
        """프로세스를 Redis에 등록한다.

        Args:
            pid: 프로세스 ID
            ppid: 부모 프로세스 ID
            name: 프로세스 이름
            exe: 실행 파일 경로
            role: 역할 (worker, watchdog 등)

        Returns:
            True: 성공, False: Redis 미연결
        """
        try:
            client = await RedisClient.get_client()
            if client is None:
                logger.warning(
                    "ProcessRegistry.register: Redis 미연결 — pid=%s 등록 스킵", pid
                )
                return False

            mapping = {
                "pid": str(pid),
                "ppid": str(ppid),
                "name": name,
                "exe": exe,
                "role": role,
                "registered_at": datetime.now().isoformat(),
                "memory_mb": "0",
            }
            await client.hset(f"proc:tree:{pid}", mapping=mapping)
            await client.sadd(f"proc:children:{ppid}", pid)
            return True
        except Exception as exc:
            logger.warning("ProcessRegistry.register 오류 (pid=%s): %s", pid, exc)
            return False

    async def unregister(self, pid: int) -> bool:
        """프로세스 등록을 해제한다.

        Args:
            pid: 해제할 프로세스 ID

        Returns:
            True: 성공 (미등록 pid도 True), False: Redis 미연결
        """
        try:
            client = await RedisClient.get_client()
            if client is None:
                logger.warning(
                    "ProcessRegistry.unregister: Redis 미연결 — pid=%s 해제 스킵", pid
                )
                return False

            entry = await client.hgetall(f"proc:tree:{pid}")
            ppid = entry.get(b"ppid") or entry.get("ppid")
            if ppid is not None:
                ppid_int = int(ppid)
                await client.srem(f"proc:children:{ppid_int}", pid)

            await client.delete(f"proc:tree:{pid}")
            return True
        except Exception as exc:
            logger.warning("ProcessRegistry.unregister 오류 (pid=%s): %s", pid, exc)
            return False

    async def get_all(self) -> dict[int, dict]:
        """등록된 모든 프로세스 정보를 반환한다.

        Returns:
            {pid: {ppid, name, exe, role, registered_at, memory_mb}} dict
        """
        try:
            client = await RedisClient.get_client()
            if client is None:
                return {}

            keys = await client.keys("proc:tree:*")
            result: dict[int, dict] = {}
            for key in keys:
                entry = await client.hgetall(key)
                if not entry:
                    continue
                decoded = {
                    (k.decode() if isinstance(k, bytes) else k): (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in entry.items()
                }
                try:
                    pid = int(decoded.get("pid", 0))
                    result[pid] = decoded
                except (ValueError, TypeError):
                    pass
            return result
        except Exception as exc:
            logger.warning("ProcessRegistry.get_all 오류: %s", exc)
            return {}

    async def get_children(self, ppid: int) -> set[int]:
        """특정 부모 프로세스의 자식 PID 집합을 반환한다.

        Args:
            ppid: 부모 프로세스 ID

        Returns:
            자식 PID set
        """
        try:
            client = await RedisClient.get_client()
            if client is None:
                return set()

            members = await client.smembers(f"proc:children:{ppid}")
            return {int(m) for m in members}
        except Exception as exc:
            logger.warning("ProcessRegistry.get_children 오류 (ppid=%s): %s", ppid, exc)
            return set()

    async def update_memory(self, pid: int, memory_mb: float) -> None:
        """프로세스의 메모리 사용량을 갱신한다.

        Args:
            pid: 프로세스 ID
            memory_mb: 메모리 사용량 (MB)
        """
        try:
            client = await RedisClient.get_client()
            if client is None:
                return

            await client.hset(f"proc:tree:{pid}", "memory_mb", str(memory_mb))
        except Exception as exc:
            logger.warning("ProcessRegistry.update_memory 오류 (pid=%s): %s", pid, exc)
