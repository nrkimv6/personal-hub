from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from app.database import Base

class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_time = Column(DateTime(timezone=True), server_default=func.now())
    url = Column(String(500))
    label = Column(String(100))
    date = Column(String(50))  # 모니터링 날짜
    times = Column(String)  # 모니터링 시간대 (JSON 문자열)
    category = Column(String(50))
    service_type = Column(String(50))
    response_hash = Column(String(32))  # 응답 내용의 해시값
    is_valid = Column(Boolean, default=True)  # 응답이 유효한지 여부
    is_full = Column(Boolean, default=False)  # 예약 마감 여부
    is_available = Column(Boolean, default=True)  # 페이지 이용 가능 여부
    error_message = Column(String(500), nullable=True)  # 에러 메시지
    created_at = Column(DateTime(timezone=True), server_default=func.now()) 