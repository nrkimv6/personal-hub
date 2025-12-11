"""
프록시 DB 서비스 테스트
작성일: 2025-12-11

RIGHT-BICEP 원칙에 따른 테스트:
- Right: 정상 동작 확인
- Boundary: 경계 조건 확인
- Inverse: 역관계 확인
- Cross-check: 교차 검증
- Error: 에러 조건 확인
- Performance: 성능 특성 확인
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text, Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, Session, relationship, declarative_base
from pathlib import Path
import tempfile
import os

# 테스트용 독립 Base 생성 (다른 모델과 충돌 방지)
TestBase = declarative_base()


class Proxy(TestBase):
    """프록시 마스터 테이블 (테스트용)"""
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    url = Column(String, unique=True, nullable=False)
    protocol = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String)
    password = Column(String)
    status = Column(String, default="pending")
    total_checks = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    avg_response_time = Column(Float)
    min_response_time = Column(Float)
    max_response_time = Column(Float)
    priority_score = Column(Float, default=0)
    first_seen_at = Column(DateTime, default=datetime.now)
    last_seen_at = Column(DateTime)
    last_checked_at = Column(DateTime)
    last_success_at = Column(DateTime)
    source = Column(String)
    country = Column(String)
    tags = Column(Text)

    check_history = relationship(
        "ProxyCheckHistory",
        back_populates="proxy",
        cascade="all, delete-orphan",
    )

    @property
    def success_rate(self):
        if self.total_checks and self.total_checks > 0:
            return round(self.success_count / self.total_checks * 100, 1)
        return None


class ProxyCheckHistory(TestBase):
    """프록시 검증 이력 테이블 (테스트용)"""
    __tablename__ = "proxy_check_history"

    id = Column(Integer, primary_key=True)
    proxy_id = Column(Integer, ForeignKey("proxies.id", ondelete="CASCADE"), nullable=False)
    checked_at = Column(DateTime, default=datetime.now)
    is_valid = Column(Boolean, nullable=False)
    response_time = Column(Float)
    error_type = Column(String)
    error_message = Column(Text)
    http_status = Column(Integer)
    detected_ip = Column(String)
    is_anonymous = Column(Boolean)

    proxy = relationship("Proxy", back_populates="check_history")


class ProxyCollectionRun(TestBase):
    """프록시 수집 실행 이력 테이블 (테스트용)"""
    __tablename__ = "proxy_collection_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime)
    status = Column(String, default="running")
    collected_count = Column(Integer, default=0)
    new_count = Column(Integer, default=0)
    validated_count = Column(Integer, default=0)
    valid_count = Column(Integer, default=0)
    source_stats = Column(Text)
    error_message = Column(Text)
    config = Column(Text)

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


from app.schemas.proxy import (
    ProxyCreate,
    ProxyUpdate,
    ProxyListParams,
    ProxyCheckHistoryCreate,
)


# 테스트용 서비스 클래스 (app.services.proxy_db_service와 동일한 로직)
import json
from sqlalchemy import func, desc, asc, or_


class TestProxyDBService:
    """테스트용 프록시 DB 서비스"""

    def __init__(self, db: Session):
        self.db = db

    def get_stats(self):
        """전체 프록시 통계 조회"""
        from app.schemas.proxy import ProxyStatsResponse

        status_counts = (
            self.db.query(Proxy.status, func.count(Proxy.id))
            .group_by(Proxy.status)
            .all()
        )
        status_dict = {status: count for status, count in status_counts}

        total = sum(status_dict.values())
        active = status_dict.get("active", 0)
        pending = status_dict.get("pending", 0)
        inactive = status_dict.get("inactive", 0)
        blacklisted = status_dict.get("blacklisted", 0)

        avg_response = (
            self.db.query(func.avg(Proxy.avg_response_time))
            .filter(Proxy.status == "active")
            .scalar()
        )

        total_success = (
            self.db.query(func.sum(Proxy.success_count))
            .filter(Proxy.status == "active")
            .scalar() or 0
        )
        total_checks = (
            self.db.query(func.sum(Proxy.total_checks))
            .filter(Proxy.status == "active")
            .scalar() or 0
        )
        overall_success_rate = (
            round(total_success / total_checks * 100, 1) if total_checks > 0 else None
        )

        protocol_counts = (
            self.db.query(Proxy.protocol, func.count(Proxy.id))
            .group_by(Proxy.protocol)
            .all()
        )
        by_protocol = {proto: count for proto, count in protocol_counts}

        country_counts = (
            self.db.query(Proxy.country, func.count(Proxy.id))
            .filter(Proxy.country.isnot(None), Proxy.status == "active")
            .group_by(Proxy.country)
            .order_by(desc(func.count(Proxy.id)))
            .limit(10)
            .all()
        )
        by_country = [{"country": country, "count": count} for country, count in country_counts]

        return ProxyStatsResponse(
            total=total,
            active=active,
            pending=pending,
            inactive=inactive,
            blacklisted=blacklisted,
            avg_response_time=round(avg_response, 3) if avg_response else None,
            overall_success_rate=overall_success_rate,
            by_protocol=by_protocol,
            by_country=by_country,
            today_checks=0,
            today_success_rate=None,
        )

    def get_list(self, params: ProxyListParams):
        """프록시 목록 조회"""
        from app.schemas.proxy import ProxyListResponse, ProxyResponse

        query = self.db.query(Proxy)

        if params.status:
            query = query.filter(Proxy.status == params.status)
        if params.protocol:
            query = query.filter(Proxy.protocol == params.protocol)
        if params.country:
            query = query.filter(Proxy.country == params.country)
        if params.search:
            search_term = f"%{params.search}%"
            query = query.filter(or_(Proxy.url.ilike(search_term), Proxy.host.ilike(search_term)))

        total = query.count()

        sort_column = getattr(Proxy, params.sort_by, Proxy.priority_score)
        if params.sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        offset = (params.page - 1) * params.page_size
        proxies = query.offset(offset).limit(params.page_size).all()
        total_pages = (total + params.page_size - 1) // params.page_size

        return ProxyListResponse(
            items=[ProxyResponse.model_validate(p) for p in proxies],
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
        )

    def get_by_id(self, proxy_id: int):
        return self.db.query(Proxy).filter(Proxy.id == proxy_id).first()

    def get_by_url(self, url: str):
        return self.db.query(Proxy).filter(Proxy.url == url).first()

    def create(self, proxy_data: ProxyCreate):
        proxy = Proxy(
            url=proxy_data.url,
            protocol=proxy_data.protocol,
            host=proxy_data.host,
            port=proxy_data.port,
            username=proxy_data.username,
            password=proxy_data.password,
            source=proxy_data.source,
            country=proxy_data.country,
            tags=proxy_data.tags,
            first_seen_at=datetime.now(),
            last_seen_at=datetime.now(),
        )
        self.db.add(proxy)
        self.db.commit()
        self.db.refresh(proxy)
        return proxy

    def update(self, proxy_id: int, proxy_data: ProxyUpdate):
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return None
        update_data = proxy_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(proxy, key, value)
        self.db.commit()
        self.db.refresh(proxy)
        return proxy

    def delete(self, proxy_id: int):
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return False
        self.db.delete(proxy)
        self.db.commit()
        return True

    def update_status(self, proxy_id: int, status: str):
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return None
        proxy.status = status
        self.db.commit()
        self.db.refresh(proxy)
        return proxy

    def add_check_history(self, history_data: ProxyCheckHistoryCreate):
        history = ProxyCheckHistory(
            proxy_id=history_data.proxy_id,
            is_valid=history_data.is_valid,
            response_time=history_data.response_time,
            error_type=history_data.error_type,
            error_message=history_data.error_message,
            http_status=history_data.http_status,
            detected_ip=history_data.detected_ip,
            is_anonymous=history_data.is_anonymous,
            checked_at=datetime.now(),
        )
        self.db.add(history)

        proxy = self.get_by_id(history_data.proxy_id)
        if proxy:
            proxy.total_checks += 1
            proxy.last_checked_at = datetime.now()

            if history_data.is_valid:
                proxy.success_count += 1
                proxy.fail_count = 0
                proxy.last_success_at = datetime.now()

                if history_data.response_time:
                    if proxy.min_response_time is None or history_data.response_time < proxy.min_response_time:
                        proxy.min_response_time = history_data.response_time
                    if proxy.max_response_time is None or history_data.response_time > proxy.max_response_time:
                        proxy.max_response_time = history_data.response_time

                    all_times = (
                        self.db.query(func.avg(ProxyCheckHistory.response_time))
                        .filter(ProxyCheckHistory.proxy_id == proxy.id, ProxyCheckHistory.is_valid == True)
                        .scalar()
                    )
                    proxy.avg_response_time = all_times

                if proxy.status == "pending":
                    proxy.status = "active"
            else:
                proxy.fail_count += 1
                if proxy.fail_count >= 7:
                    proxy.status = "inactive"

            proxy.priority_score = self.calculate_priority_score(proxy)

        self.db.commit()
        self.db.refresh(history)
        return history

    def get_check_history(self, proxy_id: int, limit: int = 50, offset: int = 0):
        return (
            self.db.query(ProxyCheckHistory)
            .filter(ProxyCheckHistory.proxy_id == proxy_id)
            .order_by(desc(ProxyCheckHistory.checked_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_collection_runs(self, limit: int = 20, status=None):
        query = self.db.query(ProxyCollectionRun)
        if status:
            query = query.filter(ProxyCollectionRun.status == status)
        return query.order_by(desc(ProxyCollectionRun.started_at)).limit(limit).all()

    def create_collection_run(self, config=None):
        run = ProxyCollectionRun(
            started_at=datetime.now(),
            status="running",
            config=json.dumps(config) if config else None,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def update_collection_run(self, run_id: int, **kwargs):
        run = self.db.query(ProxyCollectionRun).filter(ProxyCollectionRun.id == run_id).first()
        if not run:
            return None
        for key, value in kwargs.items():
            if key == "source_stats" and isinstance(value, dict):
                value = json.dumps(value)
            if hasattr(run, key):
                setattr(run, key, value)
        self.db.commit()
        self.db.refresh(run)
        return run

    def calculate_priority_score(self, proxy):
        score = 0.0
        if proxy.total_checks > 0:
            success_rate = proxy.success_count / proxy.total_checks
            score += success_rate * 40
        if proxy.avg_response_time is not None:
            speed_score = max(0, min(30, (5 - proxy.avg_response_time) / 4 * 30))
            score += speed_score
        stability = max(0, 20 - proxy.fail_count * 5)
        score += stability
        if proxy.last_checked_at:
            hours_ago = (datetime.now() - proxy.last_checked_at).total_seconds() / 3600
            freshness = max(0, min(10, (48 - hours_ago) / 48 * 10))
            score += freshness
        return round(score, 2)

    def import_from_file(self, file_path, source="file_import"):
        from app.schemas.proxy import ProxyImportResult
        from urllib.parse import urlparse

        result = ProxyImportResult(
            total_parsed=0,
            new_count=0,
            updated_count=0,
            skipped_count=0,
            errors=[],
        )

        if not file_path.exists():
            result.errors.append(f"파일을 찾을 수 없습니다: {file_path}")
            return result

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            result.errors.append(f"파일 읽기 오류: {e}")
            return result

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            proxy_url = line.split("#")[0].strip()
            if not proxy_url:
                continue

            result.total_parsed += 1

            try:
                parsed = urlparse(proxy_url)
                if not parsed.scheme or not parsed.hostname or not parsed.port:
                    result.errors.append(f"라인 {line_num}: 잘못된 프록시 형식 - {proxy_url}")
                    result.skipped_count += 1
                    continue

                existing = self.get_by_url(proxy_url)
                if existing:
                    existing.last_seen_at = datetime.now()
                    result.updated_count += 1
                else:
                    proxy_data = ProxyCreate(
                        url=proxy_url,
                        protocol=parsed.scheme,
                        host=parsed.hostname,
                        port=parsed.port,
                        username=parsed.username,
                        password=parsed.password,
                        source=source,
                    )
                    self.create(proxy_data)
                    result.new_count += 1
            except Exception as e:
                result.errors.append(f"라인 {line_num}: 처리 오류 - {e}")
                result.skipped_count += 1

        self.db.commit()
        return result

    def get_top_proxies(self, limit: int = 10, status: str = "active"):
        return (
            self.db.query(Proxy)
            .filter(Proxy.status == status)
            .order_by(desc(Proxy.priority_score))
            .limit(limit)
            .all()
        )

    def cleanup_old_history(self, days: int = 90):
        cutoff = datetime.now() - timedelta(days=days)
        deleted = (
            self.db.query(ProxyCheckHistory)
            .filter(ProxyCheckHistory.checked_at < cutoff)
            .delete()
        )
        self.db.commit()
        return deleted

    def get_detail(self, proxy_id: int, history_limit: int = 50):
        from app.schemas.proxy import ProxyDetailResponse
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return None
        history = self.get_check_history(proxy_id, limit=history_limit)
        response = ProxyDetailResponse.model_validate(proxy)
        response.check_history = history
        return response


@pytest.fixture
def test_db():
    """테스트용 인메모리 SQLite DB 생성"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    TestBase.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def proxy_service(test_db):
    """테스트용 ProxyDBService 인스턴스"""
    return TestProxyDBService(test_db)


@pytest.fixture
def sample_proxy_data():
    """테스트용 프록시 데이터"""
    return ProxyCreate(
        url="http://192.168.1.1:8080",
        protocol="http",
        host="192.168.1.1",
        port=8080,
        source="test",
    )


@pytest.fixture
def sample_proxies(proxy_service):
    """여러 개의 테스트용 프록시 생성"""
    proxies = []
    for i in range(10):
        proxy_data = ProxyCreate(
            url=f"http://192.168.1.{i+1}:8080",
            protocol="http" if i % 2 == 0 else "https",
            host=f"192.168.1.{i+1}",
            port=8080,
            source="test",
            country="KR" if i < 5 else "US",
        )
        proxy = proxy_service.create(proxy_data)
        proxies.append(proxy)
    return proxies


class TestProxyCreate:
    """프록시 생성 테스트"""

    def test_right_create_proxy(self, proxy_service, sample_proxy_data):
        """[Right] 프록시 생성이 정상 동작해야 함"""
        proxy = proxy_service.create(sample_proxy_data)

        assert proxy.id is not None
        assert proxy.url == sample_proxy_data.url
        assert proxy.protocol == sample_proxy_data.protocol
        assert proxy.host == sample_proxy_data.host
        assert proxy.port == sample_proxy_data.port
        assert proxy.status == "pending"
        assert proxy.total_checks == 0
        assert proxy.priority_score == 0

    def test_right_create_proxy_with_auth(self, proxy_service):
        """[Right] 인증 정보가 있는 프록시 생성"""
        proxy_data = ProxyCreate(
            url="http://user:pass@192.168.1.100:8080",
            protocol="http",
            host="192.168.1.100",
            port=8080,
            username="user",
            password="pass",
        )
        proxy = proxy_service.create(proxy_data)

        assert proxy.username == "user"
        assert proxy.password == "pass"

    def test_boundary_create_duplicate_url(self, proxy_service, sample_proxy_data):
        """[Boundary] 중복 URL 프록시 생성 시 에러"""
        proxy_service.create(sample_proxy_data)

        with pytest.raises(Exception):  # IntegrityError
            proxy_service.create(sample_proxy_data)


class TestProxyRead:
    """프록시 조회 테스트"""

    def test_right_get_by_id(self, proxy_service, sample_proxy_data):
        """[Right] ID로 프록시 조회"""
        created = proxy_service.create(sample_proxy_data)
        found = proxy_service.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.url == created.url

    def test_right_get_by_url(self, proxy_service, sample_proxy_data):
        """[Right] URL로 프록시 조회"""
        created = proxy_service.create(sample_proxy_data)
        found = proxy_service.get_by_url(sample_proxy_data.url)

        assert found is not None
        assert found.id == created.id

    def test_boundary_get_nonexistent_id(self, proxy_service):
        """[Boundary] 존재하지 않는 ID 조회"""
        found = proxy_service.get_by_id(99999)
        assert found is None

    def test_boundary_get_nonexistent_url(self, proxy_service):
        """[Boundary] 존재하지 않는 URL 조회"""
        found = proxy_service.get_by_url("http://nonexistent:8080")
        assert found is None


class TestProxyList:
    """프록시 목록 조회 테스트"""

    def test_right_get_list(self, proxy_service, sample_proxies):
        """[Right] 프록시 목록 조회"""
        params = ProxyListParams()
        result = proxy_service.get_list(params)

        assert result.total == 10
        assert len(result.items) == 10
        assert result.page == 1
        assert result.total_pages == 1

    def test_right_filter_by_status(self, proxy_service, sample_proxies):
        """[Right] 상태별 필터링"""
        # 일부 프록시를 active로 변경
        for i, proxy in enumerate(sample_proxies[:5]):
            proxy_service.update_status(proxy.id, "active")

        params = ProxyListParams(status="active")
        result = proxy_service.get_list(params)

        assert result.total == 5
        for item in result.items:
            assert item.status == "active"

    def test_right_filter_by_protocol(self, proxy_service, sample_proxies):
        """[Right] 프로토콜별 필터링"""
        params = ProxyListParams(protocol="http")
        result = proxy_service.get_list(params)

        assert result.total == 5  # 0, 2, 4, 6, 8 인덱스
        for item in result.items:
            assert item.protocol == "http"

    def test_right_filter_by_country(self, proxy_service, sample_proxies):
        """[Right] 국가별 필터링"""
        params = ProxyListParams(country="KR")
        result = proxy_service.get_list(params)

        assert result.total == 5

    def test_right_search(self, proxy_service, sample_proxies):
        """[Right] 검색 기능"""
        params = ProxyListParams(search="192.168.1.1")
        result = proxy_service.get_list(params)

        # 192.168.1.1, 192.168.1.10 매칭
        assert result.total >= 1

    def test_boundary_pagination(self, proxy_service, sample_proxies):
        """[Boundary] 페이징"""
        params = ProxyListParams(page=1, page_size=3)
        result = proxy_service.get_list(params)

        assert len(result.items) == 3
        assert result.total == 10
        assert result.total_pages == 4

        # 두 번째 페이지
        params = ProxyListParams(page=2, page_size=3)
        result = proxy_service.get_list(params)

        assert len(result.items) == 3
        assert result.page == 2

    def test_right_sorting(self, proxy_service, sample_proxies):
        """[Right] 정렬"""
        # priority_score 업데이트
        for i, proxy in enumerate(sample_proxies):
            proxy.priority_score = i * 10
        proxy_service.db.commit()

        params = ProxyListParams(sort_by="priority_score", sort_order="desc")
        result = proxy_service.get_list(params)

        scores = [item.priority_score for item in result.items]
        assert scores == sorted(scores, reverse=True)


class TestProxyUpdate:
    """프록시 수정 테스트"""

    def test_right_update_status(self, proxy_service, sample_proxy_data):
        """[Right] 상태 변경"""
        proxy = proxy_service.create(sample_proxy_data)
        updated = proxy_service.update_status(proxy.id, "active")

        assert updated.status == "active"

    def test_right_update_proxy(self, proxy_service, sample_proxy_data):
        """[Right] 프록시 업데이트"""
        proxy = proxy_service.create(sample_proxy_data)
        update_data = ProxyUpdate(status="blacklisted", tags='["blocked"]')
        updated = proxy_service.update(proxy.id, update_data)

        assert updated.status == "blacklisted"
        assert updated.tags == '["blocked"]'

    def test_boundary_update_nonexistent(self, proxy_service):
        """[Boundary] 존재하지 않는 프록시 업데이트"""
        result = proxy_service.update_status(99999, "active")
        assert result is None


class TestProxyDelete:
    """프록시 삭제 테스트"""

    def test_right_delete_proxy(self, proxy_service, sample_proxy_data):
        """[Right] 프록시 삭제"""
        proxy = proxy_service.create(sample_proxy_data)
        success = proxy_service.delete(proxy.id)

        assert success is True
        assert proxy_service.get_by_id(proxy.id) is None

    def test_boundary_delete_nonexistent(self, proxy_service):
        """[Boundary] 존재하지 않는 프록시 삭제"""
        success = proxy_service.delete(99999)
        assert success is False


class TestCheckHistory:
    """검증 이력 테스트"""

    def test_right_add_success_history(self, proxy_service, sample_proxy_data):
        """[Right] 성공 검증 이력 추가"""
        proxy = proxy_service.create(sample_proxy_data)

        history_data = ProxyCheckHistoryCreate(
            proxy_id=proxy.id,
            is_valid=True,
            response_time=0.5,
            detected_ip="1.2.3.4",
            is_anonymous=True,
        )
        history = proxy_service.add_check_history(history_data)

        assert history.id is not None
        assert history.is_valid is True

        # 프록시 통계 업데이트 확인
        updated_proxy = proxy_service.get_by_id(proxy.id)
        assert updated_proxy.total_checks == 1
        assert updated_proxy.success_count == 1
        assert updated_proxy.fail_count == 0
        assert updated_proxy.status == "active"  # pending -> active

    def test_right_add_failure_history(self, proxy_service, sample_proxy_data):
        """[Right] 실패 검증 이력 추가"""
        proxy = proxy_service.create(sample_proxy_data)

        history_data = ProxyCheckHistoryCreate(
            proxy_id=proxy.id,
            is_valid=False,
            error_type="timeout",
            error_message="Connection timed out",
        )
        history = proxy_service.add_check_history(history_data)

        assert history.is_valid is False

        updated_proxy = proxy_service.get_by_id(proxy.id)
        assert updated_proxy.total_checks == 1
        assert updated_proxy.success_count == 0
        assert updated_proxy.fail_count == 1
        assert updated_proxy.status == "pending"  # 아직 pending

    def test_right_consecutive_failures_deactivate(self, proxy_service, sample_proxy_data):
        """[Right] 연속 실패 시 비활성화"""
        proxy = proxy_service.create(sample_proxy_data)

        # 7번 연속 실패
        for i in range(7):
            history_data = ProxyCheckHistoryCreate(
                proxy_id=proxy.id,
                is_valid=False,
                error_type="timeout",
            )
            proxy_service.add_check_history(history_data)

        updated_proxy = proxy_service.get_by_id(proxy.id)
        assert updated_proxy.fail_count == 7
        assert updated_proxy.status == "inactive"

    def test_right_success_resets_fail_count(self, proxy_service, sample_proxy_data):
        """[Right] 성공 시 연속 실패 횟수 리셋"""
        proxy = proxy_service.create(sample_proxy_data)

        # 3번 실패
        for _ in range(3):
            proxy_service.add_check_history(ProxyCheckHistoryCreate(
                proxy_id=proxy.id,
                is_valid=False,
                error_type="timeout",
            ))

        # 1번 성공
        proxy_service.add_check_history(ProxyCheckHistoryCreate(
            proxy_id=proxy.id,
            is_valid=True,
            response_time=0.5,
        ))

        updated_proxy = proxy_service.get_by_id(proxy.id)
        assert updated_proxy.fail_count == 0

    def test_right_get_check_history(self, proxy_service, sample_proxy_data):
        """[Right] 검증 이력 조회"""
        proxy = proxy_service.create(sample_proxy_data)

        # 5개 이력 추가
        for i in range(5):
            proxy_service.add_check_history(ProxyCheckHistoryCreate(
                proxy_id=proxy.id,
                is_valid=i % 2 == 0,
                response_time=0.5 if i % 2 == 0 else None,
            ))

        history = proxy_service.get_check_history(proxy.id, limit=10)
        assert len(history) == 5


class TestStats:
    """통계 테스트"""

    def test_right_get_stats_empty(self, proxy_service):
        """[Right] 비어있는 DB 통계"""
        stats = proxy_service.get_stats()

        assert stats.total == 0
        assert stats.active == 0
        assert stats.pending == 0

    def test_right_get_stats(self, proxy_service, sample_proxies):
        """[Right] 통계 조회"""
        # 일부 프록시를 active로 변경
        for proxy in sample_proxies[:3]:
            proxy_service.update_status(proxy.id, "active")

        stats = proxy_service.get_stats()

        assert stats.total == 10
        assert stats.active == 3
        assert stats.pending == 7
        assert "http" in stats.by_protocol
        assert "https" in stats.by_protocol


class TestPriorityScore:
    """우선순위 점수 테스트"""

    def test_right_calculate_priority_score(self, proxy_service, sample_proxy_data):
        """[Right] 우선순위 점수 계산"""
        proxy = proxy_service.create(sample_proxy_data)

        # 초기 상태: 0점
        assert proxy.priority_score == 0

        # 성공 이력 추가
        proxy_service.add_check_history(ProxyCheckHistoryCreate(
            proxy_id=proxy.id,
            is_valid=True,
            response_time=0.5,
        ))

        updated_proxy = proxy_service.get_by_id(proxy.id)
        # 성공률 100% (40점) + 응답속도 0.5초 (약 33점) + 안정성 (20점) + 신선도 (최근 검증, ~10점)
        # 실제 계산: 40 + 33.75 + 20 + ~10 = ~103 하지만 타이밍에 따라 달라질 수 있음
        # 최소 70점 이상은 보장되어야 함
        assert updated_proxy.priority_score >= 70

    def test_right_get_top_proxies(self, proxy_service, sample_proxies):
        """[Right] 상위 프록시 조회"""
        # priority_score 설정
        for i, proxy in enumerate(sample_proxies):
            proxy.priority_score = (i + 1) * 10
            proxy.status = "active"
        proxy_service.db.commit()

        top = proxy_service.get_top_proxies(limit=5, status="active")

        assert len(top) == 5
        # 점수 내림차순
        scores = [p.priority_score for p in top]
        assert scores == sorted(scores, reverse=True)


class TestCollectionRuns:
    """수집 실행 이력 테스트"""

    def test_right_create_collection_run(self, proxy_service):
        """[Right] 수집 실행 시작"""
        run = proxy_service.create_collection_run(config={"max_concurrent": 50})

        assert run.id is not None
        assert run.status == "running"
        assert run.started_at is not None

    def test_right_update_collection_run(self, proxy_service):
        """[Right] 수집 실행 업데이트"""
        run = proxy_service.create_collection_run()

        updated = proxy_service.update_collection_run(
            run.id,
            status="completed",
            finished_at=datetime.now(),
            collected_count=100,
            new_count=50,
            valid_count=80,
            source_stats={"ProxyScrape": 100},
        )

        assert updated.status == "completed"
        assert updated.collected_count == 100
        assert updated.new_count == 50

    def test_right_get_collection_runs(self, proxy_service):
        """[Right] 수집 이력 조회"""
        # 3개 생성
        for _ in range(3):
            proxy_service.create_collection_run()

        runs = proxy_service.get_collection_runs(limit=10)
        assert len(runs) == 3


class TestImport:
    """파일 임포트 테스트"""

    def test_right_import_from_file(self, proxy_service, tmp_path):
        """[Right] 파일에서 임포트"""
        # 테스트 파일 생성
        proxy_file = tmp_path / "proxy_list.txt"
        proxy_file.write_text("""# Test proxy list
http://1.2.3.4:8080
https://5.6.7.8:3128  # fast
socks5://9.10.11.12:1080
invalid-line
""")

        result = proxy_service.import_from_file(proxy_file, source="test_import")

        assert result.total_parsed == 4  # 주석 제외
        assert result.new_count == 3  # 유효한 프록시
        assert result.skipped_count == 1  # invalid-line
        assert len(result.errors) == 1

    def test_right_import_updates_existing(self, proxy_service, tmp_path, sample_proxy_data):
        """[Right] 기존 프록시 업데이트"""
        # 먼저 프록시 생성
        proxy_service.create(sample_proxy_data)

        # 같은 URL 포함한 파일
        proxy_file = tmp_path / "proxy_list.txt"
        proxy_file.write_text(f"{sample_proxy_data.url}\nhttp://new.proxy:8080")

        result = proxy_service.import_from_file(proxy_file)

        assert result.total_parsed == 2
        assert result.new_count == 1  # new.proxy만
        assert result.updated_count == 1  # 기존 프록시

    def test_error_import_nonexistent_file(self, proxy_service):
        """[Error] 존재하지 않는 파일 임포트"""
        result = proxy_service.import_from_file(Path("/nonexistent/file.txt"))

        assert result.total_parsed == 0
        assert len(result.errors) == 1
        assert "파일을 찾을 수 없습니다" in result.errors[0]


class TestCleanup:
    """정리 작업 테스트"""

    def test_right_cleanup_old_history(self, proxy_service, sample_proxy_data):
        """[Right] 오래된 이력 정리"""
        proxy = proxy_service.create(sample_proxy_data)

        # 오래된 이력 추가 (직접 DB에)
        old_history = ProxyCheckHistory(
            proxy_id=proxy.id,
            is_valid=True,
            response_time=0.5,
            checked_at=datetime.now() - timedelta(days=100),
        )
        proxy_service.db.add(old_history)
        proxy_service.db.commit()

        # 최근 이력 추가
        proxy_service.add_check_history(ProxyCheckHistoryCreate(
            proxy_id=proxy.id,
            is_valid=True,
            response_time=0.5,
        ))

        deleted = proxy_service.cleanup_old_history(days=90)

        assert deleted == 1

        # 최근 이력은 남아있어야 함
        history = proxy_service.get_check_history(proxy.id)
        assert len(history) == 1


class TestCrossCheck:
    """교차 검증 테스트"""

    def test_cross_check_stats_match_list(self, proxy_service, sample_proxies):
        """[Cross-check] 통계와 목록 조회 결과 일치"""
        # 상태 변경
        for i, proxy in enumerate(sample_proxies):
            if i < 3:
                proxy_service.update_status(proxy.id, "active")
            elif i < 5:
                proxy_service.update_status(proxy.id, "inactive")

        # 통계
        stats = proxy_service.get_stats()

        # 목록
        active_list = proxy_service.get_list(ProxyListParams(status="active"))
        inactive_list = proxy_service.get_list(ProxyListParams(status="inactive"))
        pending_list = proxy_service.get_list(ProxyListParams(status="pending"))

        assert stats.active == active_list.total
        assert stats.inactive == inactive_list.total
        assert stats.pending == pending_list.total
        assert stats.total == active_list.total + inactive_list.total + pending_list.total

    def test_inverse_delete_and_count(self, proxy_service, sample_proxies):
        """[Inverse] 삭제 후 카운트 감소 확인"""
        initial_stats = proxy_service.get_stats()
        initial_total = initial_stats.total

        # 삭제
        proxy_service.delete(sample_proxies[0].id)

        final_stats = proxy_service.get_stats()
        assert final_stats.total == initial_total - 1
