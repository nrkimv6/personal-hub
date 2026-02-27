"""
시스템 메모리 관련 Pydantic 스키마
"""

from enum import Enum
from pydantic import BaseModel
from typing import List


class MemoryDangerLevel(str, Enum):
    """메모리 위험도 레벨"""
    normal = "normal"
    warning = "warning"
    critical = "critical"


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


class MemoryResponse(BaseModel):
    """메모리 대시보드 전체 응답"""
    ram: MemoryInfo
    pagefile: PageFileInfo
    top_processes: List[ProcessMemoryItem]
    danger_level: MemoryDangerLevel
