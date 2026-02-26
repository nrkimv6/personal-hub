"""subprocess 실행 서비스 - Redis 기반 크로스 세션 실행"""

import json
import os
import signal
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict

import redis
import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config import logger
from app.modules.dev_runner.config import config
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from app.modules.dev_runner.services.state import get_state

# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
COMMAND_TIMEOUT = 10  # 명령 결과 대기 타임아웃 (초)


class ExecutorService:
    """plan-runner CLI 실행 서비스 - Redis 기반 크로스 세션"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # 비동기 클라이언트 (brpop 등 블로킹 호출용)
        self.async_redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    async def _check_redis_and_listener(self):
        """Redis 연결 + command listener 존재 여부 사전 확인"""
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(
                status_code=503,
                detail="Redis에 연결할 수 없습니다. Redis 서버가 실행 중인지 확인하세요."
            )

        # listener 프로세스 존재 확인: listener가 주기적으로 갱신하는 heartbeat 키 체크
        heartbeat = await self.async_redis.get("plan-runner:listener:heartbeat")
        if heartbeat is None:
            raise HTTPException(
                status_code=503,
                detail="dev-runner command listener가 실행 중이지 않습니다. 워커를 시작하세요."
            )

    async def start_dev_runner(self, request: RunRequest) -> RunStatusResponse:
        """plan-runner 실행 시작 - Redis 명령 전송 (비동기)"""
        # Redis + listener 사전 확인
        await self._check_redis_and_listener()

        # Redis를 통해 상태 확인
        try:
            status = await self.async_redis.get(STATE_KEY + ":status")
            if status == "running":
                # heartbeat가 없으면 stale → 자동 정리 후 시작 진행
                heartbeat = await self.async_redis.get("plan-runner:listener:heartbeat")
                if heartbeat is None:
                    logger.warning("[dev-runner] running 상태이지만 heartbeat 없음 → stale 정리 후 시작")
                    self._force_cleanup_state()
                else:
                    raise HTTPException(
                        status_code=409,
                        detail="Already running"
                    )
        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis에 연결할 수 없습니다. Redis 서버가 실행 중인지 확인하세요."
            )

        # Redis 명령 생성
        command = {
            "action": "run",
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(f"[dev-runner] Request engine: {request.engine}")

        if request.plan_file:
            command["plan_file"] = request.plan_file

        if request.engine:
            command["engine"] = request.engine

        # 옵션 추가
        if request.max_cycles is not None:
            command["max_cycles"] = request.max_cycles

        if request.max_tokens is not None:
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

        # registered_paths에서 wtools 외부 경로 추출
        if request.parallel:
            from app.modules.dev_runner.services.plan_service import plan_service
            extra_dirs = plan_service.get_extra_plan_dirs()
            if extra_dirs:
                command["extra_plan_dirs"] = ",".join(extra_dirs)
            ignored_paths = plan_service.get_ignored_plan_paths()
            if ignored_paths:
                command["ignored_plans"] = ",".join(ignored_paths)

        try:
            # Redis LPUSH - 명령 전송
            await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기 (비동기, 이벤트 루프 블로킹 없음)
            result = await self.async_redis.brpop(RESULTS_KEY, timeout=COMMAND_TIMEOUT)

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
            pid = await self.async_redis.get(STATE_KEY + ":pid")
            plan_file = await self.async_redis.get(STATE_KEY + ":plan_file")
            start_time_str = await self.async_redis.get(STATE_KEY + ":start_time")

            return RunStatusResponse(
                running=True,
                engine=request.engine,
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
            logger.error(f"[dev-runner] start 실패: {traceback.format_exc()}")
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

    def _send_force_stop(self):
        """listener에 force-stop 명령 전송 (_current_process 변수까지 정리)"""
        try:
            command = {
                "action": "force-stop",
                "source": "monitor-page-api-reset",
                "timestamp": datetime.now().isoformat(),
            }
            self.redis_client.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
            # 결과 대기 (짧은 타임아웃)
            result = self.redis_client.brpop(RESULTS_KEY, timeout=5)
            if result:
                _, raw = result
                data = json.loads(raw)
                logger.info(f"[dev-runner] force-stop 결과: {data.get('message', '')}")
                return True
            else:
                logger.warning("[dev-runner] force-stop 타임아웃 (listener 무응답)")
                return False
        except Exception as e:
            logger.warning(f"[dev-runner] force-stop 전송 실패: {e}")
            return False

    def reset_running_state(self, full_reset: bool = False) -> Dict:
        """RUNNING 상태 강제 초기화 - Redis 정리만 수행"""
        try:
            # 0. listener에 force-stop 전송 (메모리 내 _current_process 정리)
            self._send_force_stop()

            # 1. Redis 상태 정리
            self._force_cleanup_state()
            logger.info("[dev-runner] Redis 상태 정리 완료")

            return {"success": True, "reset_count": 0, "full_reset": full_reset}

        except Exception as e:
            logger.error(f"[dev-runner] reset_running_state 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to reset state: {str(e)}")

    async def stop_dev_runner(self) -> Dict:
        """plan-runner 실행 중지 - Redis 명령 전송 (비동기)"""
        try:
            # Redis 사전 확인 (ping만 — listener는 stop 시에는 없을 수도 있음)
            try:
                await self.async_redis.ping()
            except (redis.ConnectionError, ConnectionRefusedError, OSError):
                raise HTTPException(
                    status_code=503,
                    detail="Redis에 연결할 수 없습니다."
                )

            # Redis를 통해 상태 확인
            status = await self.async_redis.get(STATE_KEY + ":status")
            if status != "running":
                raise HTTPException(status_code=404, detail="Not running")

            # Redis 명령 생성
            command = {
                "action": "stop",
                "source": "monitor-page-api",
                "timestamp": datetime.now().isoformat(),
            }

            # Redis LPUSH - 명령 전송
            await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기 (비동기, 이벤트 루프 블로킹 없음)
            result = await self.async_redis.brpop(RESULTS_KEY, timeout=COMMAND_TIMEOUT)

            if result is None:
                # listener 무응답 → 프로세스가 죽었을 가능성 → 상태 강제 정리
                logger.warning("[dev-runner] listener 무응답, Redis 상태 강제 정리")
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
            logger.error(f"[dev-runner] stop 실패: {traceback.format_exc()}")
            self._force_cleanup_state()
            raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")

    def _is_pid_alive(self, pid: int) -> bool:
        """PID가 실제로 살아있는지 확인 (Windows: GetExitCodeProcess로 검증)"""
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            # OpenProcess는 종료된 프로세스도 핸들을 반환할 수 있으므로
            # GetExitCodeProcess로 실제 생존 여부 확인
            STILL_ACTIVE = 259
            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return False

    def get_process_status(self) -> RunStatusResponse:
        """프로세스 상태 조회 - Redis에서 조회 + stale 상태 자동 정리"""
        try:
            # Redis 연결 확인
            redis_connected = False
            try:
                self.redis_client.ping()
                redis_connected = True
            except (redis.ConnectionError, ConnectionRefusedError, OSError):
                return RunStatusResponse(running=False, listener_alive=False, redis_connected=False, pid=None, plan_file=None)

            heartbeat = self.redis_client.get("plan-runner:listener:heartbeat")
            listener_alive = heartbeat is not None
            engine = self.redis_client.get(STATE_KEY + ":engine") or "claude"

            status = self.redis_client.get(STATE_KEY + ":status")

            if status == "running":
                pid_str = self.redis_client.get(STATE_KEY + ":pid")
                plan_file = self.redis_client.get(STATE_KEY + ":plan_file")
                start_time_str = self.redis_client.get(STATE_KEY + ":start_time")

                # PID 생존 확인 (프로세스가 에러 종료 후 상태가 stale로 남는 경우 대응)
                if pid_str:
                    try:
                        import psutil
                        if not psutil.pid_exists(int(pid_str)):
                            logger.warning(f"[dev-runner] PID {pid_str} 종료됨 → stale 상태 자동 정리")
                            self._force_cleanup_state()
                            return RunStatusResponse(running=False, engine=engine, listener_alive=listener_alive, redis_connected=True, pid=None, plan_file=None)
                    except (ValueError, ImportError):
                        pass

                if not listener_alive:
                    logger.warning("[dev-runner] heartbeat 없음 → stale 상태 자동 정리")
                    self._force_cleanup_state()
                    return RunStatusResponse(running=False, engine=engine, listener_alive=False, redis_connected=True, pid=None, plan_file=None)

                # 전체실행 시 현재 실행 중인 plan 이름 조회
                current_plan_name = None
                if plan_file == "ALL":
                    current_task_text = self.redis_client.get(STATE_KEY + ":current_task_text")
                    if current_task_text and current_task_text.startswith("[batch] "):
                        current_plan_name = current_task_text[len("[batch] "):]

                cycle_str = self.redis_client.get(STATE_KEY + ":current_cycle")
                current_cycle = int(cycle_str) if cycle_str else None

                return RunStatusResponse(
                    running=True,
                    engine=engine,
                    listener_alive=True,
                    redis_connected=True,
                    pid=int(pid_str) if pid_str else None,
                    plan_file=plan_file,
                    start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
                    current_cycle=current_cycle,
                    current_plan_name=current_plan_name,
                )
            else:
                return RunStatusResponse(running=False, engine=engine, listener_alive=listener_alive, redis_connected=True, pid=None, plan_file=None)

        except redis.ConnectionError:
            return RunStatusResponse(running=False, listener_alive=False, redis_connected=False, pid=None, plan_file=None)
        except Exception as e:
            logger.error(f"[dev-runner] status 조회 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


    def restart_listener(self) -> dict:
        """command-listener 프로세스를 재시작합니다.

        1. Redis에서 기존 PID 조회 → 존재 시 SIGTERM 전송
        2. 새 listener 프로세스 spawn
        3. 최대 10초 동안 heartbeat 키 감지 대기
        """
        LISTENER_SCRIPT = Path(__file__).parent.parent.parent.parent / "scripts" / "dev-runner-command-listener.py"
        HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
        PID_KEY = "plan-runner:listener:pid"

        # 기존 PID 종료
        old_pid_str = self.redis_client.get(PID_KEY)
        if old_pid_str:
            try:
                old_pid = int(old_pid_str)
                if sys.platform == "win32":
                    os.kill(old_pid, signal.SIGTERM)
                else:
                    os.kill(old_pid, signal.SIGTERM)
                self.redis_client.delete(PID_KEY)
            except (ProcessLookupError, PermissionError):
                pass
            time.sleep(1)

        # 새 프로세스 spawn
        python_exe = sys.executable
        proc = subprocess.Popen(
            [python_exe, str(LISTENER_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # heartbeat 감지 대기 (최대 10초)
        deadline = time.time() + 10
        while time.time() < deadline:
            hb = self.redis_client.get(HEARTBEAT_KEY)
            if hb:
                return {"success": True, "new_pid": proc.pid, "message": "listener restarted"}
            time.sleep(0.5)

        return {"success": False, "new_pid": proc.pid, "message": "heartbeat not detected within 10s"}


# 싱글톤 인스턴스
executor_service = ExecutorService()

__all__ = ['executor_service', 'ExecutorService']
