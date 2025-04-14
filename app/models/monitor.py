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
    is_active: bool = True
    interval: Optional[float] = None  # 모니터링 간격 (초)
    custom_interval: bool = False  # 사용자 정의 간격 여부
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 