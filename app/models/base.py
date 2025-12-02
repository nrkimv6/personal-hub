"""
SQLAlchemy Base 및 공통 Enum 정의
"""
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class ServiceType(str, enum.Enum):
    """모니터링 대상의 서비스 타입"""
    COUPANG = "coupang"
    NAVER = "naver"
