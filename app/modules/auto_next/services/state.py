"""실행 상태 관리"""

import subprocess
from datetime import datetime
from typing import Optional, IO
from dataclasses import dataclass, field


@dataclass
class RunState:
    """실행 상태"""
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None
    start_time: Optional[datetime] = None
    plan_file: Optional[str] = None
    current_cycle: int = 0
    options: dict = field(default_factory=dict)
    log_file_handle: Optional[IO] = None
    log_file_path: Optional[str] = None

    def is_running(self) -> bool:
        """프로세스가 실행 중인지 확인"""
        if self.process is None:
            return False
        return self.process.poll() is None

    def reset(self):
        """상태 초기화"""
        # 로그 파일 핸들 닫기
        if self.log_file_handle and not self.log_file_handle.closed:
            try:
                self.log_file_handle.close()
            except Exception:
                pass
        self.log_file_handle = None
        self.log_file_path = None
        self.process = None
        self.pid = None
        self.start_time = None
        self.plan_file = None
        self.current_cycle = 0
        self.options = {}


# 모듈 레벨 싱글톤
_run_state = RunState()


def get_state() -> RunState:
    """현재 실행 상태 반환"""
    return _run_state


__all__ = ['RunState', 'get_state']
