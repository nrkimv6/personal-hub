"""subprocess 실행 서비스 - Redis 기반 크로스 세션 실행"""

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict

import redis
from fastapi import HTTPException

from app.config import logger
from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import RunRequest, RunStatusResponse
from app.modules.auto_next.services.state import get_state

# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
COMMANDS_KEY = "auto-next:commands"
RESULTS_KEY = "auto-next:command_results"
STATE_KEY = "auto-next:state"
COMMAND_TIMEOUT = 10  # 명령 결과 대기 타임아웃 (초)


class ExecutorService:
    """auto-next CLI 실행 서비스 - Redis 기반 크로스 세션"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    def start_auto_next(self, request: RunRequest) -> RunStatusResponse:
        """auto-next 실행 시작 - Redis 명령 전송"""
        # Redis를 통해 상태 확인
        try:
            status = self.redis_client.get(STATE_KEY + ":status")
            if status == "running":
                pid = self.redis_client.get(STATE_KEY + ":pid")
                raise HTTPException(
                    status_code=409,
                    detail=f"Already running (PID: {pid})"
                )
        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis connection failed - command listener may not be running"
            )

        # Redis 명령 생성
        command = {
            "action": "run",
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }

        if request.plan_file:
            command["plan_file"] = request.plan_file

        # 옵션 추가
        if request.max_cycles and request.max_cycles > 0:
            command["max_cycles"] = request.max_cycles

        if request.max_tokens and request.max_tokens > 0:
            command["max_tokens"] = request.max_tokens

        if request.until:
            command["until"] = request.until

        if request.dry_run:
            command["dry_run"] = True

        if request.skip_plan:
            command["skip_plan"] = True

        if request.parallel:
            command["parallel"] = True

        if request.projects:
            command["projects"] = request.projects

        try:
            # Redis LPUSH - 명령 전송
            self.redis_client.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기 (블로킹, 타임아웃 설정)
            result = self.redis_client.brpop(RESULTS_KEY, timeout=COMMAND_TIMEOUT)

            if result is None:
                raise HTTPException(
                    status_code=504,
                    detail="Command timeout - listener may not be responding"
                )

            _, raw_result = result
            result_data = json.loads(raw_result)

            if not result_data.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=result_data.get("message", "Failed to start")
                )

            # Redis에서 상태 조회
            pid = self.redis_client.get(STATE_KEY + ":pid")
            plan_file = self.redis_client.get(STATE_KEY + ":plan_file")
            start_time_str = self.redis_client.get(STATE_KEY + ":start_time")

            return RunStatusResponse(
                running=True,
                pid=int(pid) if pid else None,
                plan_file=plan_file,
                start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
                current_cycle=0,
            )

        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis connection failed - command listener may not be running"
            )
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Invalid response from listener: {str(e)}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[auto-next] start 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")

    def _force_cleanup_state(self):
        """Redis 상태 강제 정리 (listener 무응답 시 fallback)"""
        try:
            self.redis_client.delete(STATE_KEY + ":status")
            self.redis_client.delete(STATE_KEY + ":pid")
            self.redis_client.delete(STATE_KEY + ":plan_file")
            self.redis_client.delete(STATE_KEY + ":start_time")
            self.redis_client.delete(STATE_KEY + ":log_file_path")
        except Exception:
            pass

    def reset_running_state(self) -> Dict:
        """RUNNING 상태 강제 초기화 - Redis + auto-next DB"""
        try:
            # 1. Redis 상태 정리
            self._force_cleanup_state()
            logger.info("[auto-next] Redis 상태 정리 완료")

            # 2. auto-next SQLite DB의 RUNNING 작업을 PENDING으로 변경
            import sqlite3

            # auto-next DB 경로 구성 (wtools 기준)
            db_path = Path(config.base_dir) / "common" / "tools" / "auto-next" / "data" / "tasks.db"

            if not db_path.exists():
                logger.warning(f"[auto-next] DB not found: {db_path}")
                return {"success": True, "reset_count": 0, "message": "auto-next DB not found"}

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            try:
                # RUNNING 작업 조회
                cursor.execute("SELECT COUNT(*) FROM tasks WHERE status='running'")
                reset_count = cursor.fetchone()[0]

                if reset_count > 0:
                    # RUNNING → PENDING 변경
                    cursor.execute(
                        "UPDATE tasks SET status='pending', started_at=NULL WHERE status='running'"
                    )
                    conn.commit()
                    logger.info(f"[auto-next] {reset_count}개 작업을 RUNNING → PENDING으로 변경")

                return {"success": True, "reset_count": reset_count}

            finally:
                conn.close()

        except Exception as e:
            logger.error(f"[auto-next] reset_running_state 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to reset state: {str(e)}")

    def stop_auto_next(self) -> Dict:
        """auto-next 실행 중지 - Redis 명령 전송"""
        try:
            # Redis를 통해 상태 확인
            status = self.redis_client.get(STATE_KEY + ":status")
            if status != "running":
                raise HTTPException(status_code=404, detail="Not running")

            # Redis 명령 생성
            command = {
                "action": "stop",
                "source": "monitor-page-api",
                "timestamp": datetime.now().isoformat(),
            }

            # Redis LPUSH - 명령 전송
            self.redis_client.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기
            result = self.redis_client.brpop(RESULTS_KEY, timeout=COMMAND_TIMEOUT)

            if result is None:
                # listener 무응답 → 프로세스가 죽었을 가능성 → 상태 강제 정리
                logger.warning("[auto-next] listener 무응답, Redis 상태 강제 정리")
                self._force_cleanup_state()
                return {"message": "Force cleaned (listener not responding)"}

            _, raw_result = result
            result_data = json.loads(raw_result)

            if not result_data.get("success"):
                # stop 실패해도 상태 정리
                self._force_cleanup_state()
                return {"message": f"Force cleaned: {result_data.get('message', '')}"}

            return {"message": "Stopped successfully"}

        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis connection failed - command listener may not be running"
            )
        except json.JSONDecodeError as e:
            self._force_cleanup_state()
            return {"message": "Force cleaned (invalid listener response)"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[auto-next] stop 실패: {traceback.format_exc()}")
            self._force_cleanup_state()
            raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")

    def _is_pid_alive(self, pid: int) -> bool:
        """PID가 실제로 살아있는지 확인"""
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False

    def get_process_status(self) -> RunStatusResponse:
        """프로세스 상태 조회 - Redis에서 조회 + stale 상태 자동 정리"""
        try:
            # Redis에서 상태 조회
            status = self.redis_client.get(STATE_KEY + ":status")

            if status == "running":
                pid_str = self.redis_client.get(STATE_KEY + ":pid")
                plan_file = self.redis_client.get(STATE_KEY + ":plan_file")
                start_time_str = self.redis_client.get(STATE_KEY + ":start_time")

                # PID 생존 확인 → 죽었으면 상태 자동 정리
                if pid_str and not self._is_pid_alive(int(pid_str)):
                    logger.warning(f"[auto-next] PID {pid_str} 죽음 감지, 상태 자동 정리")
                    self._force_cleanup_state()
                    return RunStatusResponse(
                        running=False,
                        pid=None,
                        plan_file=None,
                    )

                return RunStatusResponse(
                    running=True,
                    pid=int(pid_str) if pid_str else None,
                    plan_file=plan_file,
                    start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
                    current_cycle=0,
                )
            else:
                # 실행 중이 아님
                return RunStatusResponse(
                    running=False,
                    pid=None,
                    plan_file=None,
                )

        except redis.ConnectionError:
            # Redis 연결 실패 시 - 실행 중이 아닌 것으로 간주
            return RunStatusResponse(
                running=False,
                pid=None,
                plan_file=None,
            )
        except Exception as e:
            logger.error(f"[auto-next] status 조회 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


# 싱글톤 인스턴스
executor_service = ExecutorService()

__all__ = ['executor_service', 'ExecutorService']
