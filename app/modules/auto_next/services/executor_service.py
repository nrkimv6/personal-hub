"""subprocess 실행 서비스"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from fastapi import HTTPException

from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import RunRequest, RunStatusResponse
from app.modules.auto_next.services.state import get_state


class ExecutorService:
    """auto-next CLI 실행 서비스"""

    def start_auto_next(self, request: RunRequest) -> RunStatusResponse:
        """auto-next 실행 시작"""
        state = get_state()

        # 이미 실행 중이면 에러
        if state.is_running():
            raise HTTPException(status_code=409, detail="Already running")

        # 명령어 구성
        cmd = [
            sys.executable,  # python 실행 파일 경로
            "-m",
            "auto_next",
            "run",
            "--plan-file",
            request.plan_file,
        ]

        if request.max_cycles and request.max_cycles > 0:
            cmd.extend(["--max-cycles", str(request.max_cycles)])

        if request.max_tokens and request.max_tokens > 0:
            cmd.extend(["--max-tokens", str(request.max_tokens)])

        if request.until:
            cmd.extend(["--until", request.until])

        if request.dry_run:
            cmd.append("--dry-run")

        if request.skip_plan:
            cmd.append("--skip-plan")

        # 로그 파일 경로
        log_dir = config.WTOOLS_BASE_DIR / config.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"auto-next-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

        # subprocess 실행
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                process = subprocess.Popen(
                    cmd,
                    cwd=str(config.AUTO_NEXT_MODULE_PATH),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True,
                )

            # 상태 저장
            state.process = process
            state.pid = process.pid
            state.start_time = datetime.now()
            state.plan_file = request.plan_file
            state.current_cycle = 0
            state.options = request.dict()

            return RunStatusResponse(
                running=True,
                pid=process.pid,
                plan_file=request.plan_file,
                start_time=state.start_time,
                current_cycle=0,
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")

    def stop_auto_next(self) -> Dict:
        """auto-next 실행 중지"""
        state = get_state()

        if not state.is_running():
            raise HTTPException(status_code=404, detail="Not running")

        # Windows: terminate() 호출 (SIGTERM 대신)
        state.process.terminate()

        # 5초 대기
        try:
            state.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 강제 종료
            state.process.kill()
            state.process.wait()

        # 상태 초기화
        state.reset()

        return {"message": "Stopped successfully"}

    def get_process_status(self) -> RunStatusResponse:
        """프로세스 상태 조회"""
        state = get_state()

        # 프로세스 종료 여부 확인
        if state.process and not state.is_running():
            # 자동 정리
            state.reset()

        return RunStatusResponse(
            running=state.is_running(),
            pid=state.pid,
            plan_file=state.plan_file,
            start_time=state.start_time,
            current_cycle=state.current_cycle,
        )


# 싱글톤 인스턴스
executor_service = ExecutorService()

__all__ = ['executor_service', 'ExecutorService']
