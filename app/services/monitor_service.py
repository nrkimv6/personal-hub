from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import HTTPException
import sqlite3
from pathlib import Path
import asyncio
import json
import random
from urllib.parse import urlparse, parse_qs
import pytz

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.config import settings
from app.models.monitor import MonitorTarget
from app.schemas.monitor import MonitorTargetCreate, MonitorTargetUpdate

# SQLite 데이터베이스 설정
DB_URL = settings.DATABASE_URL
engine = create_engine(DB_URL)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 데이터베이스 모델 정의
class DBMonitorTarget(Base):
    __tablename__ = "monitor_targets"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True)
    base_url = Column(String)
    label = Column(String)
    date = Column(String)
    times = Column(String)  # JSON 문자열로 저장
    category = Column(String)
    service_type = Column(String)
    is_active = Column(Boolean, default=True)
    interval = Column(Float, nullable=True)  # 모니터링 간격 (초)
    custom_interval = Column(Boolean, default=False)  # 사용자 정의 간격 여부
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# 테이블 생성
Base.metadata.create_all(bind=engine)

class MonitorService:
    def __init__(self):
        self.db_path = Path("monitor.db")
        self._init_db()

    def _init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 모니터링 대상 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitor_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                base_url TEXT NOT NULL,
                label TEXT NOT NULL,
                date TEXT NOT NULL,
                times TEXT NOT NULL,
                category TEXT NOT NULL,
                service_type TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()

    def _get_connection(self):
        """데이터베이스 연결 반환"""
        return sqlite3.connect(self.db_path)

    async def get_targets(self, 
                         filter_params: Optional[Dict[str, Any]] = None) -> List[MonitorTarget]:
        """모든 모니터링 대상을 조회합니다."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            query = "SELECT * FROM monitor_targets"
            params = []
            
            if filter_params:
                conditions = []
                for key, value in filter_params.items():
                    if value is not None:
                        conditions.append(f"{key} = ?")
                        params.append(value)
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            targets = []
            for row in cursor.fetchall():
                target_dict = {
                    "id": row[0],
                    "url": row[1],
                    "base_url": row[2],
                    "label": row[3],
                    "date": row[4],
                    "times": row[5].split(","),
                    "category": row[6],
                    "service_type": row[7],
                    "is_active": bool(row[8]),
                    "created_at": datetime.fromisoformat(row[9]),
                    "updated_at": datetime.fromisoformat(row[10])
                }
                targets.append(MonitorTarget(**target_dict))
            
            return targets
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"데이터 조회 실패: {str(e)}")
        finally:
            conn.close()

    # URL에서 날짜 파라미터 추출
    def extract_date_from_url(self, url: str) -> Optional[str]:
        """URL에서 날짜 파라미터를 추출합니다."""
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            start_date_time = query_params.get('startDateTime')
            start_date = query_params.get('startDate')
            
            if start_date_time:
                return start_date_time[0]
            elif start_date:
                return start_date[0]
            else:
                return None
        except Exception as e:
            print(f"날짜 파라미터 추출 오류: {str(e)}")
            return None
    
    # 날짜 기반 모니터링 간격 계산
    def calculate_interval(self, start_date_str: Optional[str]) -> Optional[float]:
        """날짜 파라미터 기반으로 모니터링 간격을 계산합니다."""
        if not settings.DATE_BASED_SCHEDULING:
            return settings.CHECK_INTERVAL
            
        if start_date_str is None:
            # 날짜 데이터가 없는 경우 기본값 사용
            return random.uniform(*settings.DEFAULT_SHORT_INTERVAL)
            
        try:
            # 날짜 형식 처리
            if start_date_str.find("T") > 0:
                # 공백으로 구분된 시간대 처리
                if " " in start_date_str:
                    # 공백을 +로 변환하고 시간 형식 수정
                    date_part = start_date_str.replace(" ", "+")
                    if "0000" in date_part:
                        date_part = date_part.replace("0000", "00:00")
                    start_datetime = datetime.strptime(date_part, "%Y-%m-%dT%H:%M:%S%z")
                else:
                    # 0000 형식 처리
                    if "0000" in start_date_str:
                        start_date_str = start_date_str.replace("0000", "00:00")
                    start_datetime = datetime.strptime(start_date_str, "%Y-%m-%dT%H:%M:%S%z")
            else:
                # 날짜만 있는 경우 시간과 시간대 추가
                start_datetime = datetime.strptime(start_date_str + "T00:00:00+0900", "%Y-%m-%dT%H:%M:%S%z")
        except ValueError as e:
            print(f"날짜 파싱 오류! {start_date_str}: {str(e)}")
            return random.uniform(*settings.DEFAULT_SHORT_INTERVAL)
            
        # 현재 시간과 비교하여 간격 결정
        now = datetime.now(pytz.timezone('Asia/Seoul'))
        delta = start_datetime - now
        
        if delta.total_seconds() < 0:  # 이미 지난 날짜
            return random.uniform(*settings.DEFAULT_SHORT_INTERVAL)
        if delta.days > 7:  # 7일 이상 남은 경우
            return random.uniform(*settings.DEFAULT_FAR_INTERVAL)
        if delta.days > 1:  # 1-7일 남은 경우
            return random.uniform(*settings.DEFAULT_NEAR_INTERVAL)
        return random.uniform(*settings.DEFAULT_TOMORROW_INTERVAL)  # 내일
    
    # DB에서 모델로 변환
    def _convert_to_model(self, db_target) -> MonitorTarget:
        """데이터베이스 객체를 Pydantic 모델로 변환합니다."""
        return MonitorTarget(
            id=db_target.id,
            url=db_target.url,
            base_url=db_target.base_url,
            label=db_target.label,
            date=db_target.date,
            times=json.loads(db_target.times),
            category=db_target.category,
            service_type=db_target.service_type,
            is_active=db_target.is_active,
            interval=db_target.interval,
            custom_interval=db_target.custom_interval,
            created_at=db_target.created_at,
            updated_at=db_target.updated_at
        )
    
    # 모니터링 대상 생성
    async def create_target(self, target_data: MonitorTargetCreate) -> MonitorTarget:
        """새로운 모니터링 대상을 생성합니다."""
        db = SessionLocal()
        try:
            # 모니터링 간격 계산 (설정되지 않은 경우에만)
            if target_data.interval is None:
                date_str = self.extract_date_from_url(str(target_data.url))
                calculated_interval = self.calculate_interval(date_str)
                custom_interval = False
            else:
                calculated_interval = target_data.interval
                custom_interval = target_data.custom_interval or True
            
            # 데이터베이스 객체 생성
            db_target = DBMonitorTarget(
                url=str(target_data.url),
                base_url=str(target_data.base_url),
                label=target_data.label,
                date=target_data.date,
                times=json.dumps(target_data.times),
                category=target_data.category,
                service_type=target_data.service_type,
                interval=calculated_interval,
                custom_interval=custom_interval
            )
            
            db.add(db_target)
            db.commit()
            db.refresh(db_target)
            
            return self._convert_to_model(db_target)
        except Exception as e:
            db.rollback()
            raise Exception(f"모니터링 대상 생성 중 오류 발생: {str(e)}")
        finally:
            db.close()

    async def get_target(self, target_id: int) -> Optional[MonitorTarget]:
        """특정 모니터링 대상을 조회합니다."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM monitor_targets WHERE id = ?", (target_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            target_dict = {
                "id": row[0],
                "url": row[1],
                "base_url": row[2],
                "label": row[3],
                "date": row[4],
                "times": row[5].split(","),
                "category": row[6],
                "service_type": row[7],
                "is_active": bool(row[8]),
                "created_at": datetime.fromisoformat(row[9]),
                "updated_at": datetime.fromisoformat(row[10])
            }
            
            return MonitorTarget(**target_dict)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"데이터 조회 실패: {str(e)}")
        finally:
            conn.close()

    # 모니터링 대상 업데이트
    async def update_target(self, target_id: int, target_data: MonitorTargetUpdate) -> Optional[MonitorTarget]:
        """모니터링 대상을 업데이트합니다."""
        db = SessionLocal()
        try:
            db_target = db.query(DBMonitorTarget).filter(DBMonitorTarget.id == target_id).first()
            if not db_target:
                return None
            
            # 날짜 변경 감지 및 interval 재계산 (사용자 정의가 아닌 경우에만)
            date_changed = target_data.date is not None and target_data.date != db_target.date
            url_changed = target_data.url is not None and target_data.url != db_target.url
            
            # 업데이트할 데이터 준비
            update_data = {}
            
            # 기본 필드 업데이트
            if target_data.url is not None:
                update_data["url"] = target_data.url
            if target_data.base_url is not None:
                update_data["base_url"] = target_data.base_url
            if target_data.label is not None:
                update_data["label"] = target_data.label
            if target_data.date is not None:
                update_data["date"] = target_data.date
            if target_data.times is not None:
                update_data["times"] = json.dumps(target_data.times)
            if target_data.category is not None:
                update_data["category"] = target_data.category
            if target_data.service_type is not None:
                update_data["service_type"] = target_data.service_type
            if target_data.is_active is not None:
                update_data["is_active"] = target_data.is_active
                
            # interval 업데이트 (명시적으로 제공된 경우 사용자 정의로 설정)
            if target_data.interval is not None:
                update_data["interval"] = target_data.interval
                update_data["custom_interval"] = True
            elif (not db_target.custom_interval) and (date_changed or url_changed):
                # 사용자 정의가 아니고, 날짜나 URL이 변경된 경우 자동 재계산
                new_url = target_data.url or db_target.url
                date_str = self.extract_date_from_url(new_url)
                calculated_interval = self.calculate_interval(date_str)
                update_data["interval"] = calculated_interval
            
            # custom_interval 업데이트 (명시적으로 제공된 경우)
            if target_data.custom_interval is not None:
                update_data["custom_interval"] = target_data.custom_interval
                
                # 사용자 정의를 False로 변경하는 경우, interval 재계산
                if not target_data.custom_interval:
                    url_to_use = target_data.url or db_target.url
                    date_str = self.extract_date_from_url(url_to_use)
                    calculated_interval = self.calculate_interval(date_str)
                    update_data["interval"] = calculated_interval
            
            # 업데이트 실행
            if update_data:
                for key, value in update_data.items():
                    setattr(db_target, key, value)
                db_target.updated_at = datetime.now()
                db.commit()
                db.refresh(db_target)
            
            return self._convert_to_model(db_target)
        except Exception as e:
            db.rollback()
            raise Exception(f"모니터링 대상 업데이트 중 오류 발생: {str(e)}")
        finally:
            db.close()

    async def delete_target(self, target_id: int) -> bool:
        """모니터링 대상을 삭제합니다."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM monitor_targets WHERE id = ?", (target_id,))
            conn.commit()
            
            return cursor.rowcount > 0
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"데이터 삭제 실패: {str(e)}")
        finally:
            conn.close()

    async def get_targets_by_service(self, service_type: str) -> List[MonitorTarget]:
        """서비스 타입별 모니터링 대상을 조회합니다."""
        return await self.get_targets({"service_type": service_type})

    async def get_targets_by_category(self, category: str) -> List[MonitorTarget]:
        """카테고리별 모니터링 대상을 조회합니다."""
        return await self.get_targets({"category": category})

    async def get_active_targets(self) -> List[MonitorTarget]:
        """활성화된 모니터링 대상만 조회합니다."""
        return await self.get_targets({"is_active": True}) 