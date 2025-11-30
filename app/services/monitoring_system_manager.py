from typing import List, Optional, Dict, Any, Union, Set
from datetime import datetime, timedelta
from fastapi import HTTPException
import sqlite3
from pathlib import Path
import asyncio
import json
import random
from urllib.parse import urlparse, parse_qs
import pytz
import logging
from concurrent.futures import ThreadPoolExecutor
import hashlib

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Float, and_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text
import sqlalchemy.exc

from app.config import settings, logger
from app.models.monitor import MonitorTarget
from app.schemas.monitor import MonitorTargetCreate, MonitorTargetUpdate
from app.services.site_monitor_factory import SiteMonitorFactory
from app.services.abstract_site_monitor import AbstractSiteMonitor
from app.services.notification_service import NotificationService
from app.services.browser_service import BrowserService
from app.models.notification_settings import DBNotificationSettings
from app.database import SessionLocal, Base, engine

# SQLite 데이터베이스 설정
DB_URL = settings.DATABASE_URL
# UTF-8 지원을 위한 쿼리 파라미터 추가
if 'sqlite:///' in DB_URL and '?' not in DB_URL:
    DB_URL += '?charset=utf8'

# SQLAlchemy 설정
# engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
# Base = declarative_base()
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    is_enabled = Column(Boolean, default=True)  # 사용자 활성화/비활성화 설정
    run_status = Column(String, default="idle")  # 실행 상태
    last_error = Column(String, nullable=True)  # 마지막 오류 메시지
    error_count = Column(Integer, default=0)  # 오류 발생 횟수
    interval = Column(Float, nullable=True)  # 모니터링 간격 (초)
    custom_interval = Column(Boolean, default=False)  # 사용자 정의 간격 여부
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# 테이블 생성
Base.metadata.create_all(bind=engine)

class MonitoringSystemManager:
    """모니터링 시스템 관리자"""
    
    def __init__(self, notification_service: Optional[NotificationService] = None, browser_service: Optional[BrowserService] = None):
        self.db_path = Path("monitor.db")
        self._init_db()
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
        self._status_cache: Dict[str, Dict[str, Any]] = {}
        self._error_counts: Dict[str, int] = {}
        self._last_errors: Dict[str, str] = {}
        self._last_checks: Dict[str, datetime] = {}
        self._maintenance_mode: bool = False
        self._scheduled_maintenance: Dict[str, datetime] = {}
        self._concurrent_checks: Set[str] = set()
        self._executor = ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_CHECKS)
        self._check_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_CHECKS)
        self.notification_service = notification_service or NotificationService()
        # browser_service는 명시적으로 전달된 경우에만 사용
        # API 서버에서는 None으로 전달되어야 하며, 워커에서만 BrowserService를 초기화
        self.browser_service = browser_service  # None이면 None으로 유지
        
        # 대기열 관리 추가
        self._monitoring_queue = asyncio.Queue()
        self._active_monitors = set()
        self._max_concurrent = settings.TOTAL_MAX_TABS
        self._queue_processor_task = None

    def _init_db(self):
        """데이터베이스 초기화"""
        # UTF-8 인코딩 지원을 명시적으로 설정
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.execute("PRAGMA encoding = 'UTF-8'")
        cursor = conn.cursor()
        
        try:
            # 기존 테이블 구조 확인
            cursor.execute("PRAGMA table_info(monitor_targets)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # 모니터링 대상 테이블 생성 (존재하지 않는 경우)
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
                    is_enabled BOOLEAN DEFAULT TRUE,
                    run_status TEXT DEFAULT 'idle',
                    last_error TEXT,
                    error_count INTEGER DEFAULT 0,
                    interval REAL,
                    custom_interval BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 필요한 열 추가 (없는 경우)
            for column in ['interval', 'custom_interval', 'is_enabled', 'run_status', 'last_error', 'error_count']:
                if column not in column_names:
                    cursor.execute(f"ALTER TABLE monitor_targets ADD COLUMN {column} {'REAL' if column == 'interval' else 'BOOLEAN' if column == 'custom_interval' or column == 'is_enabled' else 'TEXT' if column == 'run_status' or column == 'last_error' else 'INTEGER'}")
            
            conn.commit()
            logger.info("데이터베이스 초기화 완료")
        except Exception as e:
            logger.error(f"데이터베이스 초기화 오류: {str(e)}")
            conn.rollback()
        finally:
            conn.close()

    def _get_connection(self):
        """데이터베이스 연결 반환"""
        # UTF-8 인코딩 지원을 명시적으로 설정
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.execute("PRAGMA encoding = 'UTF-8'")
        # Row 객체를 딕셔너리처럼 접근할 수 있도록 설정
        conn.row_factory = sqlite3.Row
        return conn

    async def get_targets(self, filters: Dict[str, Any] = None) -> List[MonitorTarget]:
        """모니터링 대상 목록을 조회합니다."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            query = "SELECT * FROM monitor_targets"
            params = []
            
            if filters:
                conditions = []
                for key, value in filters.items():
                    if value is not None:
                        conditions.append(f"{key} = ?")
                        # SQLite boolean 처리: True/False를 1/0으로 변환
                        if isinstance(value, bool):
                            params.append(1 if value else 0)
                        else:
                            params.append(value)

                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

            logger.debug(f"쿼리 실행: {query}, 파라미터: {params}")
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            targets = []
            for row in rows:
                try:
                    times_str = row['times']
                    try:
                        times = json.loads(times_str)
                    except:
                        times = times_str.split(',')
                    
                    created_at = row['created_at']
                    updated_at = row['updated_at']
                    
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at)
                    if isinstance(updated_at, str):
                        updated_at = datetime.fromisoformat(updated_at)
                    
                    target_dict = {
                        "id": row['id'],
                        "url": row['url'],
                        "base_url": row['base_url'],
                        "label": row['label'],
                        "date": row['date'],
                        "times": times,
                        "category": row['category'],
                        "service_type": row['service_type'],
                        "is_active": bool(row['is_active']),
                        "interval": row['interval'],
                        "custom_interval": bool(row['custom_interval']),
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "is_enabled": bool(row['is_enabled'] if 'is_enabled' in row else True),
                        "run_status": row['run_status'] if 'run_status' in row else 'idle',
                        "last_error": row['last_error'] if 'last_error' in row else None,
                        "error_count": int(row['error_count'] if 'error_count' in row else 0)
                    }
                    
                    targets.append(MonitorTarget(**target_dict))
                except Exception as e:
                    logger.error(f"대상 변환 중 오류 발생: {str(e)}, Row: {dict(row)}")
                    continue
            
            return targets
        except Exception as e:
            logger.error(f"데이터 조회 실패: {str(e)}", exc_info=True)
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
        try:
            # times 필드 안전하게 파싱
            times = []
            if db_target.times:
                try:
                    times = json.loads(db_target.times)
                except json.JSONDecodeError as e:
                    logger.warning(f"Times 필드 JSON 파싱 오류 (ID {db_target.id}): {str(e)}")
                    # 손상된 JSON이면 기본값으로 빈 배열 사용
                    times = []
                    # 필요시 DB 업데이트도 가능
                    # db = SessionLocal()
                    # db_target.times = json.dumps(times)
                    # db.commit()
            
            return MonitorTarget(
                id=db_target.id,
                url=db_target.url,
                base_url=db_target.base_url,
                label=db_target.label,
                date=db_target.date,
                times=times,
                category=db_target.category,
                service_type=db_target.service_type,
                is_active=db_target.is_active,
                interval=db_target.interval,
                custom_interval=db_target.custom_interval,
                created_at=db_target.created_at,
                updated_at=db_target.updated_at,
                is_enabled=getattr(db_target, 'is_enabled', True),
                run_status=getattr(db_target, 'run_status', 'idle'),
                last_error=getattr(db_target, 'last_error', None),
                error_count=getattr(db_target, 'error_count', 0)
            )
        except Exception as e:
            logger.error(f"모델 변환 중 오류 발생 (ID {db_target.id}): {str(e)}", exc_info=True)
            # 최소한의 필수 필드만으로 모델 생성
            return MonitorTarget(
                id=db_target.id,
                url=db_target.url,
                base_url=db_target.base_url or "",
                label=db_target.label or f"대상 {db_target.id}",
                date=db_target.date or "",
                times=[],
                category=db_target.category or "",
                service_type=db_target.service_type or "",
                is_active=db_target.is_active,
                interval=db_target.interval or 60.0,
                custom_interval=db_target.custom_interval or False,
                created_at=db_target.created_at or datetime.now(),
                updated_at=db_target.updated_at or datetime.now(),
                is_enabled=True,
                run_status='idle',
                last_error=None,
                error_count=0
            )
    
    # 모니터링 대상 생성
    async def create_target(self, target_data: MonitorTargetCreate) -> MonitorTarget:
        """새로운 모니터링 대상을 생성합니다."""
        db = SessionLocal()
        try:
            logger.info(f"모니터링 대상 생성 시작: {target_data}")
            
            # URL 중복 검사
            existing_target = db.query(DBMonitorTarget).filter(DBMonitorTarget.url == str(target_data.url)).first()
            if existing_target:
                logger.warning(f"이미 존재하는 URL입니다: {target_data.url}")
                raise HTTPException(
                    status_code=409,  # Conflict
                    detail=f"이미 존재하는 URL입니다: {target_data.url}"
                )
            
            # 모니터링 간격 계산 (설정되지 않은 경우에만)
            if target_data.interval is None:
                date_str = self.extract_date_from_url(str(target_data.url))
                logger.info(f"URL에서 추출한 날짜: {date_str}")
                calculated_interval = self.calculate_interval(date_str)
                logger.info(f"계산된 모니터링 간격: {calculated_interval}")
                custom_interval = False
            else:
                calculated_interval = target_data.interval
                custom_interval = target_data.custom_interval or True
                logger.info(f"사용자 지정 모니터링 간격: {calculated_interval}, 커스텀: {custom_interval}")
            
            # 데이터베이스 객체 생성
            try:
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
                logger.info(f"DBMonitorTarget 객체 생성 완료")
            except Exception as e:
                logger.error(f"DBMonitorTarget 객체 생성 실패: {str(e)}")
                raise Exception(f"모니터링 대상 데이터 변환 실패: {str(e)}")
            
            try:
                db.add(db_target)
                db.commit()
                db.refresh(db_target)
                logger.info(f"DB에 모니터링 대상 저장 완료: ID {db_target.id}")
            except sqlalchemy.exc.IntegrityError as e:
                logger.error(f"DB 저장 실패 - 중복 URL: {str(e)}")
                db.rollback()
                if "UNIQUE constraint failed: monitor_targets.url" in str(e):
                    raise HTTPException(
                        status_code=409,  # Conflict
                        detail=f"이미 등록된 URL입니다: {target_data.url}"
                    )
                raise Exception(f"모니터링 대상 저장 실패: {str(e)}")
            except Exception as e:
                logger.error(f"DB 저장 실패: {str(e)}")
                db.rollback()
                raise Exception(f"모니터링 대상 저장 실패: {str(e)}")
            
            try:
                model = self._convert_to_model(db_target)
                logger.info(f"모니터링 대상 모델 변환 완료: ID {model.id}")
                return model
            except Exception as e:
                logger.error(f"모델 변환 실패: {str(e)}")
                raise Exception(f"모니터링 대상 모델 변환 실패: {str(e)}")
        except HTTPException:
            # 이미 정의된 HTTP 예외는 그대로 전달
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"모니터링 대상 생성 중 오류 발생: {str(e)}", exc_info=True)
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
            
            try:
                times_str = row['times']
                try:
                    times = json.loads(times_str)
                except:
                    # 콤마로 구분된 형식인 경우 처리
                    times = times_str.split(',')
                
                # datetime 필드 처리 개선
                created_at = row['created_at']
                updated_at = row['updated_at']
                
                # 문자열이면 datetime으로 변환, 아니면 그대로 사용
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at)
                
                target_dict = {
                    "id": row['id'],
                    "url": row['url'],
                    "base_url": row['base_url'],
                    "label": row['label'],
                    "date": row['date'],
                    "times": times,
                    "category": row['category'],
                    "service_type": row['service_type'],
                    "is_active": bool(row['is_active']),
                    "interval": row['interval'],
                    "custom_interval": bool(row['custom_interval']),
                    "created_at": created_at,
                    "updated_at": updated_at
                }
                
                for field in ['is_enabled', 'run_status', 'last_error', 'error_count']:
                    if field in row.keys():
                        target_dict[field] = row[field] if field != 'error_count' else int(row[field]) if row[field] is not None else 0
                    else:
                        target_dict[field] = True if field == 'is_enabled' else "idle" if field == 'run_status' else None if field == 'last_error' else 0
                
                return MonitorTarget(**target_dict)
            except Exception as e:
                logger.error(f"대상 변환 중 오류 발생: {str(e)}, Row: {dict(row)}")
                return None
        except Exception as e:
            logger.error(f"데이터 조회 실패: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"데이터 조회 실패: {str(e)}")
        finally:
            conn.close()

    # 모니터링 대상 업데이트
    async def update_target(self, target_id: int, target_data: Union[MonitorTargetUpdate, Dict[str, Any]]) -> Optional[MonitorTarget]:
        """모니터링 대상의 정보를 업데이트합니다."""
        db = SessionLocal()
        try:
            db_target = db.query(DBMonitorTarget).filter(DBMonitorTarget.id == target_id).first()
            if not db_target:
                return None
            
            # dict 타입인 경우 처리
            is_dict = isinstance(target_data, dict)
            
            # 날짜 변경 감지 및 interval 재계산 (사용자 정의가 아닌 경우에만)
            date_changed = False
            url_changed = False
            
            if is_dict:
                date_changed = 'date' in target_data and target_data['date'] is not None and target_data['date'] != db_target.date
                url_changed = 'url' in target_data and target_data['url'] is not None and target_data['url'] != db_target.url
            else:
                date_changed = target_data.date is not None and target_data.date != db_target.date
                url_changed = target_data.url is not None and target_data.url != db_target.url
            
            # 업데이트할 데이터 준비
            update_data = {}
            
            # 기본 필드 업데이트
            if is_dict:
                # dict 타입인 경우
                if 'url' in target_data and target_data['url'] is not None:
                    update_data["url"] = target_data['url']
                if 'base_url' in target_data and target_data['base_url'] is not None:
                    update_data["base_url"] = target_data['base_url']
                if 'label' in target_data and target_data['label'] is not None:
                    update_data["label"] = target_data['label']
                if 'date' in target_data and target_data['date'] is not None:
                    update_data["date"] = target_data['date']
                if 'times' in target_data and target_data['times'] is not None:
                    update_data["times"] = json.dumps(target_data['times'])
                if 'category' in target_data and target_data['category'] is not None:
                    update_data["category"] = target_data['category']
                if 'service_type' in target_data and target_data['service_type'] is not None:
                    update_data["service_type"] = target_data['service_type']
                if 'is_active' in target_data and target_data['is_active'] is not None:
                    update_data["is_active"] = target_data['is_active']
                
                # interval 업데이트 (명시적으로 제공된 경우 사용자 정의로 설정)
                if 'interval' in target_data and target_data['interval'] is not None:
                    update_data["interval"] = target_data['interval']
                    update_data["custom_interval"] = True
                elif (not db_target.custom_interval) and (date_changed or url_changed):
                    # 사용자 정의가 아니고, 날짜나 URL이 변경된 경우 자동 재계산
                    new_url = target_data.get('url', db_target.url)
                    date_str = self.extract_date_from_url(new_url)
                    calculated_interval = self.calculate_interval(date_str)
                    update_data["interval"] = calculated_interval
                
                # custom_interval 업데이트 (명시적으로 제공된 경우)
                if 'custom_interval' in target_data and target_data['custom_interval'] is not None:
                    update_data["custom_interval"] = target_data['custom_interval']
                    
                    # 사용자 정의를 False로 변경하는 경우, interval 재계산
                    if not target_data['custom_interval']:
                        url_to_use = target_data.get('url', db_target.url)
                        date_str = self.extract_date_from_url(url_to_use)
                        calculated_interval = self.calculate_interval(date_str)
                        update_data["interval"] = calculated_interval
            else:
                # Pydantic 모델인 경우 (기존 코드)
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
            logger.error(f"모니터링 대상 업데이트 중 오류 발생: {str(e)}", exc_info=True)
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
        """활성화된 모니터링 대상만 조회합니다. (is_active=True AND is_enabled=True)"""
        return await self.get_targets({"is_active": True, "is_enabled": True})

    async def fix_invalid_times(self):
        """손상된 times 필드를 가진 모니터링 대상을 수정합니다."""
        db = SessionLocal()
        try:
            logger.info("손상된 times 필드 검사 시작")
            targets = db.query(DBMonitorTarget).all()
            fixed_count = 0
            
            for target in targets:
                try:
                    # times 필드가 유효한 JSON인지 확인
                    if target.times:
                        try:
                            json.loads(target.times)
                        except json.JSONDecodeError:
                            # 손상된 JSON 수정
                            logger.warning(f"손상된 times 필드 발견 (ID {target.id}): {target.times}")
                            # 기본값으로 빈 배열 사용
                            target.times = json.dumps([])
                            fixed_count += 1
                except Exception as e:
                    logger.error(f"대상 ID {target.id} 검사 중 오류: {str(e)}")
            
            if fixed_count > 0:
                db.commit()
                logger.info(f"총 {fixed_count}개의 손상된 times 필드 수정 완료")
            else:
                logger.info("손상된 times 필드가 발견되지 않았습니다")
            
            return fixed_count
        except Exception as e:
            db.rollback()
            logger.error(f"times 필드 수정 중 오류 발생: {str(e)}", exc_info=True)
            raise Exception(f"times 필드 수정 중 오류 발생: {str(e)}")
        finally:
            db.close()

    async def start_queue_processor(self):
        """대기열 처리기를 시작합니다."""
        if not self._queue_processor_task:
            self._queue_processor_task = asyncio.create_task(self._process_queue())
            logger.info("대기열 처리기 시작됨")

    async def stop_queue_processor(self):
        """대기열 처리기를 중지합니다."""
        if self._queue_processor_task:
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
            self._queue_processor_task = None
            logger.info("대기열 처리기 중지됨")

    async def add_to_queue(self, target: MonitorTarget):
        """모니터링 대상을 대기열에 추가합니다."""
        await self._monitoring_queue.put(target)
        logger.info(f"대상 {target.id} ({target.label})가 대기열에 추가됨")
        
        # 대기열 처리기가 실행 중이 아니면 시작
        if not self._queue_processor_task:
            await self.start_queue_processor()

    async def _process_queue(self):
        """대기열에서 모니터링 대상을 처리합니다."""
        while True:
            try:
                # 현재 활성 모니터 수가 최대치보다 적을 때만 새 모니터링 시작
                if len(self._active_monitors) < self._max_concurrent:
                    target = await self._monitoring_queue.get()
                    self._active_monitors.add(str(target.id))
                    asyncio.create_task(self._monitor_loop(target))
                    logger.info(f"대상 {target.id} ({target.label}) 모니터링 시작")
                else:
                    # 대기열이 비어있지 않으면 잠시 대기
                    if not self._monitoring_queue.empty():
                        await asyncio.sleep(1)
                    else:
                        # 대기열이 비어있으면 처리기 중지
                        await self.stop_queue_processor()
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"대기열 처리 중 오류 발생: {str(e)}")
                await asyncio.sleep(1)

    async def _monitor_loop(self, target: MonitorTarget, service: AbstractSiteMonitor) -> None:
        """모니터링 루프를 실행합니다."""
        target_id = str(target.id)
        try:
            while True:
                try:
                    # 유지보수 모드 확인
                    if self._maintenance_mode:
                        logger.info(f"유지보수 모드로 인해 모니터링 일시 중지: {target_id}")
                        await asyncio.sleep(60)
                        continue
                    
                    # 예약된 유지보수 확인
                    maintenance_time = self._scheduled_maintenance.get(target_id)
                    if maintenance_time and datetime.now() >= maintenance_time:
                        logger.info(f"예약된 유지보수로 인해 모니터링 일시 중지: {target_id}")
                        await asyncio.sleep(60)
                        continue
                    
                    # 동시성 제어
                    async with self._check_semaphore:
                        if target_id in self._concurrent_checks:
                            logger.warning(f"이미 체크 중인 대상입니다: {target_id}")
                            await asyncio.sleep(5)
                            continue
                        
                        self._concurrent_checks.add(target_id)
                        try:
                            # 상태 확인
                            new_status = await service.check_status(target)
                            self._last_checks[target_id] = datetime.now()
                            
                            # 상태 변경 감지
                            if self._has_status_changed(target_id, new_status):
                                await service.handle_status_change(target, new_status)
                                self._status_cache[target_id] = new_status
                                self._error_counts[target_id] = 0
                                self._last_errors[target_id] = None
                                
                                # 성공적인 체크 후 상태 업데이트
                                db = SessionLocal()
                                try:
                                    db_target = db.query(DBMonitorTarget).filter(DBMonitorTarget.id == target.id).first()
                                    if db_target:
                                        db_target.error_count = 0
                                        db_target.last_error = None
                                        db_target.run_status = "running"
                                        db.commit()
                                finally:
                                    db.close()
                        finally:
                            self._concurrent_checks.remove(target_id)
                    
                    # 다음 체크까지 대기
                    interval = await service.get_monitoring_interval(target)
                    await asyncio.sleep(interval)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"모니터링 중 에러 발생: {error_msg}")
                    
                    # 에러 카운트 증가
                    self._error_counts[target_id] = self._error_counts.get(target_id, 0) + 1
                    self._last_errors[target_id] = error_msg
                    
                    # 에러 상태 업데이트
                    db = SessionLocal()
                    try:
                        db_target = db.query(DBMonitorTarget).filter(DBMonitorTarget.id == target.id).first()
                        if db_target:
                            db_target.error_count = self._error_counts[target_id]
                            db_target.last_error = error_msg
                            db_target.run_status = "error"
                            db.commit()
                    except Exception as db_error:
                        logger.error(f"에러 상태 업데이트 실패: {str(db_error)}")
                    finally:
                        db.close()
                    
                    # 에러 발생 시 대기 시간 조정
                    error_wait = min(30 * (2 ** (self._error_counts[target_id] - 1)), 3600)
                    await asyncio.sleep(error_wait)
        finally:
            # 모니터링 종료 시 활성 모니터 목록에서 제거
            self._active_monitors.discard(target_id)
            logger.info(f"대상 {target_id} 모니터링 종료")

    async def start_monitoring(self, target: MonitorTarget) -> None:
        """모니터링을 시작합니다."""
        if target.id in self._monitoring_tasks:
            logger.warning(f"이미 모니터링 중인 대상입니다: {target.id}")
            return
        
        # 모니터링 서비스 생성
        service = SiteMonitorFactory.create_service(target)
        
        # 대기열에 추가
        await self.add_to_queue(target)
        logger.info(f"모니터링 시작 요청: {target.label}")

    async def stop_monitoring(self, target_id: str) -> None:
        """모니터링을 중지합니다."""
        task = self._monitoring_tasks.get(target_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._monitoring_tasks[target_id]
            self._active_monitors.discard(target_id)
            logger.info(f"모니터링 중지: {target_id}")

    def _has_status_changed(self, target_id: str, new_status: Dict[str, Any]) -> bool:
        """상태 변경 여부를 확인합니다."""
        old_status = self._status_cache.get(target_id)
        if not old_status:
            return True
        
        # 해시값 비교
        return old_status.get("hash") != new_status.get("hash")
    
    def get_monitoring_status(self) -> List[Dict[str, Any]]:
        """모니터링 상태를 반환합니다."""
        status_list = []
        for target_id, status in self._status_cache.items():
            status_info = {
                "target_id": target_id,
                "status": status,
                "last_check": self._last_checks.get(target_id, datetime.now()).isoformat(),
                "error_count": self._error_counts.get(target_id, 0),
                "last_error": self._last_errors.get(target_id),
                "is_monitoring": target_id in self._monitoring_tasks
            }
            status_list.append(status_info)
        return status_list
    
    async def get_target_status(self, target_id: str) -> Optional[Dict[str, Any]]:
        """특정 모니터링 대상의 상태를 반환합니다."""
        if target_id not in self._status_cache:
            return None
            
        return {
            "status": self._status_cache[target_id],
            "last_check": self._last_checks.get(target_id, datetime.now()).isoformat(),
            "error_count": self._error_counts.get(target_id, 0),
            "last_error": self._last_errors.get(target_id),
            "is_monitoring": target_id in self._monitoring_tasks
        }
    
    async def reset_target_status(self, target_id: str) -> bool:
        """특정 모니터링 대상의 상태를 초기화합니다."""
        if target_id in self._status_cache:
            del self._status_cache[target_id]
        if target_id in self._error_counts:
            del self._error_counts[target_id]
        if target_id in self._last_errors:
            del self._last_errors[target_id]
        if target_id in self._last_checks:
            del self._last_checks[target_id]
            
        db = SessionLocal()
        try:
            db_target = db.query(DBMonitorTarget).filter(DBMonitorTarget.id == target_id).first()
            if db_target:
                db_target.error_count = 0
                db_target.last_error = None
                db_target.run_status = "idle"
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"상태 초기화 실패: {str(e)}")
            return False
        finally:
            db.close()
    
    async def start_all_monitoring(self) -> None:
        """모든 활성화된 모니터링 대상을 시작합니다."""
        targets = await self.get_active_targets()
        for target in targets:
            if target.is_enabled:
                await self.start_monitoring(target)
    
    async def stop_all_monitoring(self) -> None:
        """모든 모니터링을 중지합니다."""
        for target_id in list(self._monitoring_tasks.keys()):
            await self.stop_monitoring(target_id)
    
    async def restart_monitoring(self, target_id: str) -> None:
        """특정 모니터링 대상을 재시작합니다."""
        await self.stop_monitoring(target_id)
        target = await self.get_target(target_id)
        if target and target.is_enabled:
            await self.start_monitoring(target)
    
    async def update_monitoring_interval(self, target_id: str, interval: float) -> bool:
        """모니터링 간격을 업데이트합니다."""
        db = SessionLocal()
        try:
            db_target = db.query(DBMonitorTarget).filter(DBMonitorTarget.id == target_id).first()
            if db_target:
                db_target.interval = interval
                db_target.custom_interval = True
                db.commit()
                
                # 실행 중인 모니터링 재시작
                if target_id in self._monitoring_tasks:
                    await self.restart_monitoring(target_id)
                return True
            return False
        except Exception as e:
            logger.error(f"모니터링 간격 업데이트 실패: {str(e)}")
            return False
        finally:
            db.close()
    
    async def set_maintenance_mode(self, enabled: bool) -> None:
        """유지보수 모드를 설정합니다."""
        self._maintenance_mode = enabled
        if enabled:
            logger.info("유지보수 모드 활성화")
        else:
            logger.info("유지보수 모드 비활성화")
    
    async def schedule_maintenance(self, target_id: str, start_time: datetime, duration: int) -> None:
        """특정 대상에 대한 유지보수를 예약합니다."""
        self._scheduled_maintenance[target_id] = start_time
        logger.info(f"대상 {target_id}에 대한 유지보수 예약: {start_time}부터 {duration}분간")
        
        # 유지보수 종료 시간 설정
        end_time = start_time + timedelta(minutes=duration)
        asyncio.create_task(self._end_maintenance(target_id, end_time))
    
    async def _end_maintenance(self, target_id: str, end_time: datetime) -> None:
        """예약된 유지보수를 종료합니다."""
        await asyncio.sleep((end_time - datetime.now()).total_seconds())
        if target_id in self._scheduled_maintenance:
            del self._scheduled_maintenance[target_id]
            logger.info(f"대상 {target_id}의 유지보수 종료")
    
    async def get_maintenance_schedule(self) -> Dict[str, datetime]:
        """예약된 유지보수 일정을 반환합니다."""
        return self._scheduled_maintenance
    
    async def get_concurrent_checks(self) -> Set[str]:
        """현재 체크 중인 대상 목록을 반환합니다."""
        return self._concurrent_checks
    
    async def cleanup_old_status(self, days: int = 7) -> None:
        """지정된 일수 이전의 상태 데이터를 정리합니다."""
        cutoff_date = datetime.now() - timedelta(days=days)
        db = SessionLocal()
        try:
            # 오래된 상태 데이터 삭제
            db.query(DBMonitorTarget).filter(
                and_(
                    DBMonitorTarget.updated_at < cutoff_date,
                    DBMonitorTarget.run_status == "idle"
                )
            ).delete()
            db.commit()
            logger.info(f"{days}일 이전의 오래된 상태 데이터 정리 완료")
        except Exception as e:
            logger.error(f"상태 데이터 정리 실패: {str(e)}")
            db.rollback()
        finally:
            db.close()
    
    async def get_performance_metrics(self) -> Dict[str, Any]:
        """모니터링 성능 메트릭을 반환합니다."""
        return {
            "active_targets": len(self._monitoring_tasks),
            "concurrent_checks": len(self._concurrent_checks),
            "error_counts": sum(self._error_counts.values()),
            "last_checks": {
                target_id: last_check.isoformat()
                for target_id, last_check in self._last_checks.items()
            },
            "maintenance_mode": self._maintenance_mode,
            "scheduled_maintenance": {
                target_id: time.isoformat()
                for target_id, time in self._scheduled_maintenance.items()
            }
        }

    async def check_status(self, target: MonitorTarget) -> Dict[str, Any]:
        """
        모니터링 대상의 상태를 확인합니다.
        """
        raise NotImplementedError("Subclasses must implement check_status")

    async def handle_status_change(self, target: MonitorTarget, new_status: Dict[str, Any]) -> None:
        """
        상태 변화를 처리하고 필요한 알림을 발송합니다.
        """
        try:
            # 상태 변화 로깅
            logger.info(f"Status changed for target {target.id}: {new_status}")

            # 알림 발송
            await self.notification_service.send_notification(
                target=target,
                status=new_status
            )

        except Exception as e:
            logger.error(f"Error handling status change: {str(e)}")
            raise

    def get_interval(self, target: MonitorTarget) -> int:
        """
        모니터링 간격을 계산합니다.
        """
        # 기본 간격은 5초
        return 5

    def validate_target(self, target: MonitorTarget) -> bool:
        """
        모니터링 대상의 유효성을 검사합니다.
        """
        if not target.url or not target.label:
            return False
        return True 