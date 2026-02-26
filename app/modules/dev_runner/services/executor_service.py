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
COMMAND_TIMEOUT = 30  # 명령 결과 대기 타임아웃 (초) — worktree 생성 시간 고려


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
            socket_timeout=COMMAND_TIMEOUT + 5,  # BRPOP 무한 대기 방지
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
        """plan-runner 실행 시작 - Redis 명령 전송 (비동기, 멀티 runner 지원)"""
        # Redis + listener 사전 확인
        await self._check_redis_and_listener()

        # 동시 실행 개수 제한 확인
        count = await self.async_redis.scard(ACTIVE_RUNNERS_KEY)
        if count >= config.MAX_CONCURRENT_RUNNERS:
            raise HTTPException(
                status_code=429,
                detail=f"최대 {config.MAX_CONCURRENT_RUNNERS}개 동시 실행 가능 (현재 {count}개)"
            )

        # 새 runner_id 생성 (멀티 실행 지원 - 409 체크 없음)
        runner_id = uuid.uuid4().hex[:8]

        # per-command 결과 키 (레이스 컨디션 방지)
        command_id = uuid.uuid4().hex[:8]

        # Redis 명령 생성
        command = {
            "action": "run",
            "runner_id": runner_id,
            "command_id": command_id,
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(f"[dev-runner] Request engine: {request.engine}, runner_id: {runner_id}")

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

        # registered_paths에서 wtools 외부 경로 추출 (asyncio.to_thread로 이벤트 루프 블로킹 방지)
        if request.parallel:
            import asyncio
            from app.modules.dev_runner.services.plan_service import plan_service
            extra_dirs = await asyncio.to_thread(plan_service.get_extra_plan_dirs)
            if extra_dirs:
                command["extra_plan_dirs"] = ",".join(extra_dirs)
            ignored_paths = await asyncio.to_thread(plan_service.get_ignored_plan_paths)
            if ignored_paths:
                command["ignored_plans"] = ",".join(ignored_paths)

        result_key = f"{RESULTS_KEY}:{command_id}"

        try:
            # Redis LPUSH - 명령 전송
            await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기 (per-command 키, 레이스 컨디션 방지)
            result = await self.async_redis.brpop(result_key, timeout=COMMAND_TIMEOUT)

            if result is None:
                # cleanup
                await self.async_redis.delete(result_key)
                raise HTTPException(
                    status_code=504,
                    detail="Command timeout - listener may not be responding"
                )

            _, raw_result = result
            await self.async_redis.delete(result_key)
            result_data = json.loads(raw_result)

            if not result_data.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=result_data.get("message", "Failed to start")
                )

            # Redis에서 per-runner 상태 조회
            pid = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
            plan_file = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
            start_time_str = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")

            return RunStatusResponse(
                running=True,
                runner_id=runner_id,
                engine=request.engine,
                pid=int(pid) if pid else None,
                plan_file=plan_file,
                start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
                current_cycle=0,
                listener_alive=True,
                redis_connected=True,
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

    def _force_cleanup_state(self, runner_id: str = ""):
        """Redis 상태 강제 정리 (listener 무응답 시 fallback)"""
        try:
            if runner_id:
                self.redis_client.delete(
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:status",
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:pid",
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file",
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time",
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path",
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path",
                )
                self.redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
            else:
                # 모든 active runner 정리 (레거시 fallback)
                runner_ids = self.redis_client.smembers(ACTIVE_RUNNERS_KEY)
                for rid in runner_ids:
                    self.redis_client.delete(
                        f"{RUNNER_KEY_PREFIX}:{rid}:status",
                        f"{RUNNER_KEY_PREFIX}:{rid}:pid",
                        f"{RUNNER_KEY_PREFIX}:{rid}:plan_file",
                        f"{RUNNER_KEY_PREFIX}:{rid}:start_time",
                        f"{RUNNER_KEY_PREFIX}:{rid}:log_file_path",
                        f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path",
                    )
                self.redis_client.delete(ACTIVE_RUNNERS_KEY)
        except Exception:
            pass

    def _send_force_stop(self, runner_id: str = ""):
        """listener에 force-stop 명령 전송 (_running_processes 변수까지 정리)"""
        try:
            command_id = uuid.uuid4().hex[:8]
            command = {
                "action": "force-stop",
                "runner_id": runner_id,
                "command_id": command_id,
                "source": "monitor-page-api-reset",
                "timestamp": datetime.now().isoformat(),
            }
            result_key = f"{RESULTS_KEY}:{command_id}"
            self.redis_client.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
            # 결과 대기 (짧은 타임아웃)
            result = self.redis_client.brpop(result_key, timeout=5)
            self.redis_client.delete(result_key)
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
            # 0. listener에 force-stop 전송 (메모리 내 _running_processes 정리)
            self._send_force_stop()

            # 1. Redis 상태 정리 (모든 runner)
            self._force_cleanup_state()
            logger.info("[dev-runner] Redis 상태 정리 완료")

            return {"success": True, "reset_count": 0, "full_reset": full_reset}

        except Exception as e:
            logger.error(f"[dev-runner] reset_running_state 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to reset state: {str(e)}")

    async def stop_dev_runner(self, runner_id: str) -> Dict:
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

            # Redis를 통해 해당 runner 상태 확인
            status = await self.async_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
            if status != "running":
                raise HTTPException(status_code=404, detail="Not running")

            # per-command 결과 키
            command_id = uuid.uuid4().hex[:8]

            # Redis 명령 생성
            command = {
                "action": "stop",
                "runner_id": runner_id,
                "command_id": command_id,
                "source": "monitor-page-api",
                "timestamp": datetime.now().isoformat(),
            }
            result_key = f"{RESULTS_KEY}:{command_id}"

            # Redis LPUSH - 명령 전송
            await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))

            # BRPOP으로 결과 대기 (per-command 키)
            result = await self.async_redis.brpop(result_key, timeout=COMMAND_TIMEOUT)

            if result is None:
                # listener 무응답 → 프로세스가 죽었을 가능성 → 상태 강제 정리
                logger.warning("[dev-runner] listener 무응답, Redis 상태 강제 정리")
                await self.async_redis.delete(result_key)
                self._force_cleanup_state(runner_id)
                return {"message": "Force cleaned (listener not responding)"}

            _, raw_result = result
            await self.async_redis.delete(result_key)
            result_data = json.loads(raw_result)

            if not result_data.get("success"):
                # stop 실패해도 상태 정리
                self._force_cleanup_state(runner_id)
                return {"message": f"Force cleaned: {result_data.get('message', '')}"}

            return {"message": "Stopped successfully"}

        except redis.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="Redis connection failed - command listener may not be running"
            )
        except json.JSONDecodeError:
            self._force_cleanup_state(runner_id)
            return {"message": "Force cleaned (invalid listener response)"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[dev-runner] stop 실패: {traceback.format_exc()}")
            self._force_cleanup_state(runner_id)
            raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")

    def get_runner_status(self, runner_id: str) -> RunStatusResponse:
        """특정 runner 상태 조회 (per-runner Redis 키 기반)"""
        status = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
        pid_str = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        plan_file = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        start_time_str = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")
        engine = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine") or "claude"
        running = status == "running"

        # PID stale 감지
        if running and pid_str and not self._is_pid_alive(int(pid_str)):
            logger.warning(f"[dev-runner] runner {runner_id} PID {pid_str} 종료됨 → stale 정리")
            self._force_cleanup_state(runner_id)
            running = False
            pid_str = None

        current_cycle_str = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:current_cycle")
        current_cycle = int(current_cycle_str) if current_cycle_str is not None else None

        return RunStatusResponse(
            runner_id=runner_id,
            running=running,
            engine=engine,
            pid=int(pid_str) if pid_str else None,
            plan_file=plan_file,
            start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
            current_cycle=current_cycle,
            listener_alive=True,
            redis_connected=True,
        )

    def get_all_runners(self) -> list:
        """활성 runner 목록 조회"""
        from app.modules.dev_runner.schemas import RunnerListItem
        try:
            runner_ids = self.redis_client.smembers(ACTIVE_RUNNERS_KEY)
            result = []
            for rid in runner_ids:
                status = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:status")
                pid_str = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid")
                plan_file = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file")
                engine = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:engine")
                start_time_str = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:start_time")
                worktree_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:worktree_path")
                merge_status = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:merge_status")
                branch = f"runner/{rid}" if worktree_path else None
                start_time = None
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str)
                    except ValueError:
                        pass
                result.append(RunnerListItem(
                    runner_id=rid,
                    running=status == "running",
                    plan_file=plan_file,
                    engine=engine,
                    start_time=start_time,
                    pid=int(pid_str) if pid_str else None,
                    worktree_path=worktree_path,
                    branch=branch,
                    merge_status=merge_status,
                ))
            return result
        except redis.ConnectionError:
            return []

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
        """프로세스 상태 조회 - 하위호환 (첫 번째 active runner 반환)"""
        try:
            # Redis 연결 확인
            try:
                self.redis_client.ping()
            except (redis.ConnectionError, ConnectionRefusedError, OSError):
                return RunStatusResponse(running=False, listener_alive=False, redis_connected=False, pid=None, plan_file=None)

            heartbeat = self.redis_client.get("plan-runner:listener:heartbeat")
            listener_alive = heartbeat is not None

            runner_ids = self.redis_client.smembers(ACTIVE_RUNNERS_KEY)
            if runner_ids:
                first_id = next(iter(runner_ids))
                r = self.get_runner_status(first_id)
                r.listener_alive = listener_alive
                return r

            # 실행 중인 runner 없음
            return RunStatusResponse(running=False, engine="claude", listener_alive=listener_alive, redis_connected=True, pid=None, plan_file=None)

        except redis.ConnectionError:
            return RunStatusResponse(running=False, listener_alive=False, redis_connected=False, pid=None, plan_file=None)
        except Exception as e:
            logger.error(f"[dev-runner] status 조회 실패: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


    async def get_merge_queue(self) -> list:
        """Redis merge-queue 조회 → list[MergeQueueItem]"""
        try:
            raw_items = await self.async_redis.lrange("plan-runner:merge-queue", 0, -1)
            result = []
            for raw in raw_items:
                try:
                    item = json.loads(raw)
                    result.append(item)
                except Exception:
                    pass
            return result
        except Exception:
            return []

    async def get_merge_status(self, runner_id: str) -> dict | None:
        """Redis merge:{runner_id}:status 조회"""
        try:
            status = await self.async_redis.get(f"plan-runner:merge:{runner_id}:status")
            if status is None:
                return None
            return {"runner_id": runner_id, "status": status, "fix_attempts": 0, "message": ""}
        except Exception:
            return None

    async def send_runner_command(self, runner_id: str, action: str) -> dict:
        """runner에 명령 전송 (retry-merge, cleanup-worktree 등)"""
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(status_code=503, detail="Redis에 연결할 수 없습니다.")

        command_id = uuid.uuid4().hex[:8]
        command = {
            "action": action,
            "runner_id": runner_id,
            "command_id": command_id,
            "source": "monitor-page-api",
            "timestamp": datetime.now().isoformat(),
        }
        result_key = f"{RESULTS_KEY}:{command_id}"
        await self.async_redis.lpush(COMMANDS_KEY, json.dumps(command, ensure_ascii=False))
        result = await self.async_redis.brpop(result_key, timeout=COMMAND_TIMEOUT)
        if result is None:
            await self.async_redis.delete(result_key)
            return {"success": False, "message": "Command timeout"}
        _, raw = result
        await self.async_redis.delete(result_key)
        return json.loads(raw)

    async def stop_all_runners(self) -> dict:
        """모든 active runner 일괄 중지 - asyncio.gather 병렬 호출"""
        import asyncio

        runners = self.get_all_runners()
        runner_ids = [r.runner_id for r in runners if r.running]

        if not runner_ids:
            return {"stopped": 0}

        async def _stop_one(runner_id: str):
            try:
                await self.stop_dev_runner(runner_id)
                return True
            except Exception as e:
                logger.warning(f"[dev-runner] stop_all: runner {runner_id} 중지 실패: {e}")
                return False

        results = await asyncio.gather(*[_stop_one(rid) for rid in runner_ids], return_exceptions=False)
        stopped = sum(1 for r in results if r)
        return {"stopped": stopped}

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

__all__ = ['executor_service', 'ExecutorService', 'ACTIVE_RUNNERS_KEY', 'RUNNER_KEY_PREFIX']
