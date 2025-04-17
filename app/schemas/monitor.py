from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import List, Optional

class MonitorTargetBase(BaseModel):
    url: str
    base_url: str
    label: str
    date: str
    times: List[str]
    category: str
    service_type: str

class MonitorTargetCreate(BaseModel):
    url: HttpUrl
    label: str
    category: str
    service_type: str
    date: str
    times: List[str]
    base_url: HttpUrl
    interval: Optional[float] = None
    custom_interval: Optional[bool] = False
    is_enabled: Optional[bool] = True

class MonitorTargetUpdate(BaseModel):
    url: Optional[str] = None
    base_url: Optional[str] = None
    label: Optional[str] = None
    date: Optional[str] = None
    times: Optional[List[str]] = None
    category: Optional[str] = None
    service_type: Optional[str] = None
    is_active: Optional[bool] = None
    is_enabled: Optional[bool] = None
    run_status: Optional[str] = None
    last_error: Optional[str] = None
    error_count: Optional[int] = None
    interval: Optional[float] = None
    custom_interval: Optional[bool] = None

class MonitorTarget(MonitorTargetBase):
    id: int
    is_active: bool
    is_enabled: bool = True
    run_status: str = "idle"
    last_error: Optional[str] = None
    error_count: int = 0
    interval: Optional[float] = None
    custom_interval: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class NotificationSettings(BaseModel):
    enable_telegram: bool = True
    enable_desktop: bool = True
    notify_states: List[str] = [] 