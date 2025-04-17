from datetime import datetime
from typing import List, Optional, Union, Tuple
from pydantic import BaseModel

class MonitorTarget(BaseModel):
    id: int
    url: str
    base_url: str
    label: str
    date: str
    times: List[str]
    category: str
    service_type: str
    is_active: bool = True  # 논리적인 활성화 상태 (오류 시에도 유지됨)
    is_enabled: bool = True  # 사용자 활성화/비활성화 설정 (관리자 제어)
    run_status: str = "idle"  # 실행 상태 (idle, running, error, stopped)
    last_error: Optional[str] = None  # 마지막 오류 메시지
    error_count: int = 0  # 오류 발생 횟수
    interval: Optional[float] = None  # 모니터링 간격 (초)
    custom_interval: bool = False  # 사용자 정의 간격 여부
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 