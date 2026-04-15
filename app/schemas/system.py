"""
시스템 메모리 관련 Pydantic 스키마
"""

from enum import Enum
from pydantic import BaseModel
from typing import List, Optional


class MemoryDangerLevel(str, Enum):
    """메모리 위험도 레벨"""
    normal = "normal"
    warning = "warning"
    critical = "critical"


class MemoryPressureLevel(str, Enum):
    """메모리 압박 이벤트 레벨"""
    critical = "critical"
    emergency = "emergency"
    fatal = "fatal"
    fatal_recovered = "fatal_recovered"


class MemoryInfo(BaseModel):
    """RAM 또는 PageFile 정보"""
    total_mb: float
    used_mb: float
    available_mb: float
    percent: float


class PageFileInfo(BaseModel):
    """페이지 파일(스왑) 정보"""
    total_mb: float
    used_mb: float
    free_mb: float
    percent: float


class ProcessMemoryItem(BaseModel):
    """프로세스 메모리 항목 (그룹핑 포함)"""
    name: str
    pid: int  # 대표 PID (그룹 시 가장 큰 메모리의 PID)
    working_set_mb: float
    count: int  # 동일 이름 프로세스 수


class MemoryPressureProcessItem(BaseModel):
    """메모리 압박 히스토리의 상위 프로세스 항목"""
    pid: int
    name: str
    memory_mb: float
    script_path: Optional[str] = None
    ppid: Optional[int] = None
    parent_name: Optional[str] = None
    ppid_alive: Optional[bool] = None
    grandparent_pid: Optional[int] = None
    grandparent_name: Optional[str] = None
    is_orphan: Optional[bool] = None


class MemoryPressureHistoryItem(BaseModel):
    """메모리 압박 이벤트 히스토리 항목"""
    timestamp: str
    level: MemoryPressureLevel
    available_mb: float
    top_processes: List[MemoryPressureProcessItem]
    process_tree_excerpt: str


class MemoryPressureHistorySummary(BaseModel):
    """메모리 압박 히스토리 요약"""
    total: int
    critical: int = 0
    emergency: int = 0
    fatal: int = 0
    fatal_recovered: int = 0


class MemoryPressureHistoryResponse(BaseModel):
    """메모리 압박 히스토리 응답"""
    total: int
    summary: MemoryPressureHistorySummary
    items: List[MemoryPressureHistoryItem]


class MemoryResponse(BaseModel):
    """메모리 대시보드 전체 응답"""
    ram: MemoryInfo
    pagefile: PageFileInfo
    top_processes: List[ProcessMemoryItem]
    danger_level: MemoryDangerLevel
