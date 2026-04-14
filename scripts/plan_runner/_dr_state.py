"""_dr_state.py — dev-runner-command-listener 전역 상태 모듈"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

from typing import Optional

# WorkflowManager는 런타임에 set_wf_manager()로 주입됨 (순환 임포트 방지)
_wf_manager = None


def get_wf_manager():
    return _wf_manager


def set_wf_manager(wm) -> None:
    global _wf_manager
    _wf_manager = wm


# 전역 프로세스 관리 dict — getter는 dict 참조를 반환하므로 호출자가 직접 수정 가능
_running_processes: dict = {}
_running_log_files: dict = {}
_stream_threads: dict = {}
# cleanup 완료 플래그: rid → cleanup 완료 timestamp (dict). 이중 cleanup 방지 + TTL 기반 자동 소거 (5분 후 heartbeat에서 제거)
_cleanup_done: dict = {}
# 프로세스 종료 최초 감지 시각: heartbeat stale merge flag / stream thread 타임아웃 추적용
_dead_process_first_seen: dict = {}
# 좀비 최초 감지 시각: subprocess_heartbeat 만료 최초 발견 시각 (rid → float timestamp)
_zombie_first_seen: dict = {}


def get_running_processes() -> dict:
    return _running_processes


def get_running_log_files() -> dict:
    return _running_log_files


def get_stream_threads() -> dict:
    return _stream_threads


def get_cleanup_done() -> dict:
    return _cleanup_done


def get_dead_process_first_seen() -> dict:
    return _dead_process_first_seen


def get_zombie_first_seen() -> dict:
    return _zombie_first_seen
