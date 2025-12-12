"""
프록시 DB 서비스
작성일: 2025-12-11

프록시 데이터 접근 및 비즈니스 로직을 담당합니다.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse

from sqlalchemy import select, func, desc, asc, and_, or_, Integer
from sqlalchemy.orm import Session, selectinload

from app.models.proxy import Proxy, ProxyCheckHistory, ProxyCollectionRun
from app.schemas.proxy import (
    ProxyCreate,
    ProxyUpdate,
    ProxyResponse,
    ProxyDetailResponse,
    ProxyStatsResponse,
    ProxyListParams,
    ProxyListResponse,
    ProxyCollectionRunResponse,
    ProxyImportResult,
    ProxyCheckHistoryCreate,
    ProxyInfo,
)

logger = logging.getLogger(__name__)


class ProxyDBService:
    """프록시 DB 서비스"""

    def __init__(self, db: Session):
        self.db = db

    # ============== 통계 ==============

    def get_stats(self) -> ProxyStatsResponse:
        """전체 프록시 통계 조회"""
        # 상태별 집계
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

        # 활성 프록시의 평균 응답 시간
        avg_response = (
            self.db.query(func.avg(Proxy.avg_response_time))
            .filter(Proxy.status == "active")
            .scalar()
        )

        # 전체 성공률
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

        # 프로토콜별 분포
        protocol_counts = (
            self.db.query(Proxy.protocol, func.count(Proxy.id))
            .group_by(Proxy.protocol)
            .all()
        )
        by_protocol = {proto: count for proto, count in protocol_counts}

        # 국가별 분포 (상위 10개)
        country_counts = (
            self.db.query(Proxy.country, func.count(Proxy.id))
            .filter(Proxy.country.isnot(None), Proxy.status == "active")
            .group_by(Proxy.country)
            .order_by(desc(func.count(Proxy.id)))
            .limit(10)
            .all()
        )
        by_country = [
            {"country": country, "count": count}
            for country, count in country_counts
        ]

        # 오늘 검증 통계
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())

        today_history = (
            self.db.query(
                func.count(ProxyCheckHistory.id),
                func.sum(func.cast(ProxyCheckHistory.is_valid, Integer))
            )
            .filter(ProxyCheckHistory.checked_at >= today_start)
            .first()
        )
        today_checks = today_history[0] or 0
        today_success = today_history[1] or 0
        today_success_rate = (
            round(today_success / today_checks * 100, 1) if today_checks > 0 else None
        )

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
            today_checks=today_checks,
            today_success_rate=today_success_rate,
        )

    # ============== 목록 조회 ==============

    def get_list(self, params: ProxyListParams) -> ProxyListResponse:
        """프록시 목록 조회 (필터, 정렬, 페이징)"""
        query = self.db.query(Proxy)

        # 필터링
        if params.status:
            query = query.filter(Proxy.status == params.status)
        if params.protocol:
            query = query.filter(Proxy.protocol == params.protocol)
        if params.country:
            query = query.filter(Proxy.country == params.country)
        if params.search:
            search_term = f"%{params.search}%"
            query = query.filter(
                or_(
                    Proxy.url.ilike(search_term),
                    Proxy.host.ilike(search_term),
                )
            )

        # 총 개수
        total = query.count()

        # 정렬
        sort_column = getattr(Proxy, params.sort_by, Proxy.priority_score)
        if params.sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        # 페이징
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

    # ============== 상세 조회 ==============

    def get_by_id(self, proxy_id: int) -> Optional[Proxy]:
        """ID로 프록시 조회"""
        return self.db.query(Proxy).filter(Proxy.id == proxy_id).first()

    def get_detail(self, proxy_id: int, history_limit: int = 50) -> Optional[ProxyDetailResponse]:
        """프록시 상세 조회 (검증 이력 포함)"""
        proxy = (
            self.db.query(Proxy)
            .options(selectinload(Proxy.check_history))
            .filter(Proxy.id == proxy_id)
            .first()
        )

        if not proxy:
            return None

        # 검증 이력 제한
        history = (
            self.db.query(ProxyCheckHistory)
            .filter(ProxyCheckHistory.proxy_id == proxy_id)
            .order_by(desc(ProxyCheckHistory.checked_at))
            .limit(history_limit)
            .all()
        )

        response = ProxyDetailResponse.model_validate(proxy)
        response.check_history = history
        return response

    def get_by_url(self, url: str) -> Optional[Proxy]:
        """URL로 프록시 조회"""
        return self.db.query(Proxy).filter(Proxy.url == url).first()

    # ============== 생성/수정/삭제 ==============

    def create(self, proxy_data: ProxyCreate) -> Proxy:
        """프록시 생성"""
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

    def update(self, proxy_id: int, proxy_data: ProxyUpdate) -> Optional[Proxy]:
        """프록시 수정"""
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return None

        update_data = proxy_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(proxy, key, value)

        self.db.commit()
        self.db.refresh(proxy)
        return proxy

    def delete(self, proxy_id: int) -> bool:
        """프록시 삭제"""
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return False

        self.db.delete(proxy)
        self.db.commit()
        return True

    def update_status(self, proxy_id: int, status: str) -> Optional[Proxy]:
        """프록시 상태 변경"""
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return None

        proxy.status = status
        self.db.commit()
        self.db.refresh(proxy)
        return proxy

    # ============== 검증 이력 ==============

    def add_check_history(self, history_data: ProxyCheckHistoryCreate) -> ProxyCheckHistory:
        """검증 이력 추가 및 프록시 통계 업데이트"""
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

        # 프록시 통계 업데이트
        proxy = self.get_by_id(history_data.proxy_id)
        if proxy:
            proxy.total_checks += 1
            proxy.last_checked_at = datetime.now()

            if history_data.is_valid:
                proxy.success_count += 1
                proxy.fail_count = 0
                proxy.last_success_at = datetime.now()

                # 응답 시간 업데이트
                if history_data.response_time:
                    if proxy.min_response_time is None or history_data.response_time < proxy.min_response_time:
                        proxy.min_response_time = history_data.response_time
                    if proxy.max_response_time is None or history_data.response_time > proxy.max_response_time:
                        proxy.max_response_time = history_data.response_time

                    # 평균 응답 시간 재계산
                    avg_result = (
                        self.db.query(func.avg(ProxyCheckHistory.response_time))
                        .filter(
                            ProxyCheckHistory.proxy_id == proxy.id,
                            ProxyCheckHistory.is_valid == True,
                        )
                        .scalar()
                    )
                    proxy.avg_response_time = avg_result

                # 상태 업데이트
                if proxy.status == "pending":
                    proxy.status = "active"
            else:
                proxy.fail_count += 1

                # 연속 실패 시 비활성화
                if proxy.fail_count >= 7:
                    proxy.status = "inactive"

            # 우선순위 점수 재계산
            proxy.priority_score = self.calculate_priority_score(proxy)

        self.db.commit()
        self.db.refresh(history)
        return history

    def get_check_history(
        self,
        proxy_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> List[ProxyCheckHistory]:
        """프록시 검증 이력 조회"""
        return (
            self.db.query(ProxyCheckHistory)
            .filter(ProxyCheckHistory.proxy_id == proxy_id)
            .order_by(desc(ProxyCheckHistory.checked_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    # ============== 수집 실행 이력 ==============

    def get_collection_runs(
        self,
        limit: int = 20,
        status: Optional[str] = None
    ) -> List[ProxyCollectionRun]:
        """수집 실행 이력 조회"""
        query = self.db.query(ProxyCollectionRun)

        if status:
            query = query.filter(ProxyCollectionRun.status == status)

        return (
            query.order_by(desc(ProxyCollectionRun.started_at))
            .limit(limit)
            .all()
        )

    def create_collection_run(self, config: Optional[Dict] = None) -> ProxyCollectionRun:
        """수집 실행 시작"""
        run = ProxyCollectionRun(
            started_at=datetime.now(),
            status="running",
            config=json.dumps(config) if config else None,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def update_collection_run(
        self,
        run_id: int,
        **kwargs
    ) -> Optional[ProxyCollectionRun]:
        """수집 실행 업데이트"""
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

    # ============== 유틸리티 ==============

    def calculate_priority_score(self, proxy: Proxy) -> float:
        """
        우선순위 점수 계산 (0~100)

        가중치:
        - 성공률 (40%): success_count / total_checks
        - 응답속도 (30%): 빠를수록 높음 (1초 이하 만점, 5초 이상 0점)
        - 안정성 (20%): 연속 실패 횟수 기반 (0회면 만점)
        - 신선도 (10%): 최근 확인된 프록시 우대 (24시간 이내 만점)
        """
        score = 0.0

        # 1. 성공률 (40점)
        if proxy.total_checks > 0:
            success_rate = proxy.success_count / proxy.total_checks
            score += success_rate * 40

        # 2. 응답속도 (30점)
        if proxy.avg_response_time is not None:
            # 1초 이하: 30점, 5초 이상: 0점, 선형 보간
            speed_score = max(0, min(30, (5 - proxy.avg_response_time) / 4 * 30))
            score += speed_score

        # 3. 안정성 (20점)
        # 연속 실패 1회당 -5점
        stability = max(0, 20 - proxy.fail_count * 5)
        score += stability

        # 4. 신선도 (10점)
        if proxy.last_checked_at:
            hours_ago = (datetime.now() - proxy.last_checked_at).total_seconds() / 3600
            # 24시간 이내: 10점, 48시간 이상: 0점
            freshness = max(0, min(10, (48 - hours_ago) / 48 * 10))
            score += freshness

        return round(score, 2)

    def import_from_file(self, file_path: Path, source: str = "file_import") -> ProxyImportResult:
        """
        프록시 파일에서 임포트

        파일 형식:
        http://1.2.3.4:8080  # comment
        https://user:pass@5.6.7.8:3128
        """
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

            # 주석 제거
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

                # 기존 프록시 확인
                existing = self.get_by_url(proxy_url)

                if existing:
                    # 기존 프록시 업데이트 (last_seen_at)
                    existing.last_seen_at = datetime.now()
                    result.updated_count += 1
                else:
                    # 신규 프록시 생성
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

    def get_top_proxies(self, limit: int = 10, status: str = "active") -> List[Proxy]:
        """상위 프록시 조회 (우선순위순)"""
        return (
            self.db.query(Proxy)
            .filter(Proxy.status == status)
            .order_by(desc(Proxy.priority_score))
            .limit(limit)
            .all()
        )

    def get_proxies_by_response_time(
        self,
        min_response_time: Optional[float] = None,
        max_response_time: Optional[float] = None,
        limit: int = 10,
        status: str = "active",
        exclude_ids: Optional[List[int]] = None,
        min_success_rate: float = 0.5,
    ) -> List[ProxyInfo]:
        """
        응답시간 범위로 프록시 조회

        Args:
            min_response_time: 최소 응답시간 (초), None이면 제한 없음 (초과 조건)
            max_response_time: 최대 응답시간 (초), None이면 제한 없음 (이하 조건)
            limit: 조회할 개수
            status: 상태 필터 (기본: active)
            exclude_ids: 제외할 프록시 ID
            min_success_rate: 최소 성공률 (0.0~1.0)

        Returns:
            ProxyInfo 리스트 (우선순위 내림차순)
        """
        query = self.db.query(Proxy).filter(Proxy.status == status)

        # 제외할 프록시 ID 필터
        if exclude_ids:
            query = query.filter(Proxy.id.notin_(exclude_ids))

        # 응답시간 범위 필터 (측정된 프록시만)
        # min_response_time: 초과 조건 (>)
        if min_response_time is not None:
            query = query.filter(
                Proxy.avg_response_time.isnot(None),
                Proxy.avg_response_time > min_response_time,
            )

        # max_response_time: 이하 조건 (<=)
        if max_response_time is not None:
            query = query.filter(
                Proxy.avg_response_time.isnot(None),
                Proxy.avg_response_time <= max_response_time,
            )

        # 최소 성공률 필터
        if min_success_rate > 0:
            query = query.filter(
                Proxy.total_checks > 0,
                (Proxy.success_count * 1.0 / Proxy.total_checks) >= min_success_rate,
            )

        proxies = (
            query.order_by(desc(Proxy.priority_score))
            .limit(limit)
            .all()
        )

        return [
            ProxyInfo(
                id=p.id,
                url=p.url,
                protocol=p.protocol,
                host=p.host,
                port=p.port,
                username=p.username,
                password=p.password,
                priority_score=p.priority_score or 0.0,
                avg_response_time=p.avg_response_time,
                success_count=p.success_count or 0,
                fail_count=p.fail_count or 0,
                total_checks=p.total_checks or 0,
            )
            for p in proxies
        ]

    def get_top_proxies_for_pool(
        self,
        limit: int = 10,
        status: str = "active",
        min_success_rate: float = 0.0,
        min_checks: int = 0,
        exclude_ids: Optional[List[int]] = None,
        max_response_time: Optional[float] = None,
    ) -> List[ProxyInfo]:
        """
        ProxyManagerV2용 상위 프록시 조회

        Args:
            limit: 조회할 프록시 수
            status: 상태 필터 (기본: active)
            min_success_rate: 최소 성공률 (0.0~1.0)
            min_checks: 최소 검증 횟수 (신뢰도 확보)
            exclude_ids: 제외할 프록시 ID 목록 (직전 풀, 느린 프록시 등)
            max_response_time: 최대 허용 응답시간 (초) - 초과 시 제외

        Returns:
            ProxyInfo 리스트 (우선순위 내림차순)
        """
        query = self.db.query(Proxy).filter(Proxy.status == status)

        # 제외할 프록시 ID 필터
        if exclude_ids:
            query = query.filter(Proxy.id.notin_(exclude_ids))

        # 최대 응답시간 필터 (아직 측정 안 된 프록시는 포함)
        if max_response_time is not None:
            query = query.filter(
                or_(
                    Proxy.avg_response_time.is_(None),
                    Proxy.avg_response_time <= max_response_time,
                )
            )

        # 최소 검증 횟수 필터
        if min_checks > 0:
            query = query.filter(Proxy.total_checks >= min_checks)

        # 최소 성공률 필터 (검증 횟수가 있는 경우만)
        if min_success_rate > 0:
            query = query.filter(
                or_(
                    Proxy.total_checks == 0,  # 아직 검증 안 된 프록시 포함
                    (Proxy.success_count * 1.0 / Proxy.total_checks) >= min_success_rate,
                )
            )

        proxies = (
            query.order_by(desc(Proxy.priority_score))
            .limit(limit)
            .all()
        )

        return [
            ProxyInfo(
                id=p.id,
                url=p.url,
                protocol=p.protocol,
                host=p.host,
                port=p.port,
                username=p.username,
                password=p.password,
                priority_score=p.priority_score or 0.0,
                avg_response_time=p.avg_response_time,
                success_count=p.success_count or 0,
                fail_count=p.fail_count or 0,
                total_checks=p.total_checks or 0,
            )
            for p in proxies
        ]

    def record_check_result(
        self,
        proxy_id: int,
        is_valid: bool,
        response_time: Optional[float] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        detected_ip: Optional[str] = None,
        is_anonymous: Optional[bool] = None,
        http_status: Optional[int] = None,
    ) -> bool:
        """
        프록시 검증 결과 기록 (ProxyManagerV2용 간편 인터페이스)

        검증 이력을 추가하고 프록시 통계를 업데이트합니다.

        Args:
            proxy_id: 프록시 ID
            is_valid: 검증 성공 여부
            response_time: 응답 시간 (초)
            error_type: 에러 유형 (timeout, connection, http_4xx 등)
            error_message: 에러 메시지
            detected_ip: 감지된 IP
            is_anonymous: 익명성 여부
            http_status: HTTP 상태 코드

        Returns:
            성공 여부
        """
        try:
            history_data = ProxyCheckHistoryCreate(
                proxy_id=proxy_id,
                is_valid=is_valid,
                response_time=response_time,
                error_type=error_type,
                error_message=error_message,
                detected_ip=detected_ip,
                is_anonymous=is_anonymous,
                http_status=http_status,
            )
            self.add_check_history(history_data)
            return True
        except Exception as e:
            logger.error(f"Failed to record check result for proxy {proxy_id}: {e}")
            return False

    def get_proxy_info_by_id(self, proxy_id: int) -> Optional[ProxyInfo]:
        """ID로 ProxyInfo 조회"""
        proxy = self.get_by_id(proxy_id)
        if not proxy:
            return None

        return ProxyInfo(
            id=proxy.id,
            url=proxy.url,
            protocol=proxy.protocol,
            host=proxy.host,
            port=proxy.port,
            username=proxy.username,
            password=proxy.password,
            priority_score=proxy.priority_score or 0.0,
            avg_response_time=proxy.avg_response_time,
            success_count=proxy.success_count or 0,
            fail_count=proxy.fail_count or 0,
            total_checks=proxy.total_checks or 0,
        )

    def cleanup_old_history(self, days: int = 90) -> int:
        """오래된 검증 이력 정리"""
        cutoff = datetime.now() - timedelta(days=days)
        deleted = (
            self.db.query(ProxyCheckHistory)
            .filter(ProxyCheckHistory.checked_at < cutoff)
            .delete()
        )
        self.db.commit()
        return deleted

    def deactivate_stale_proxies(self, days: int = 7) -> int:
        """오래된 실패 프록시 비활성화"""
        cutoff = datetime.now() - timedelta(days=days)
        updated = (
            self.db.query(Proxy)
            .filter(
                Proxy.fail_count >= 7,
                Proxy.last_success_at < cutoff,
            )
            .update({"status": "inactive"})
        )
        self.db.commit()
        return updated

    def batch_update_proxy_stats(
        self,
        stats_list: List[Dict[str, Any]],
    ) -> int:
        """
        프록시 통계 배치 업데이트 (풀 갱신 시 사용)

        Args:
            stats_list: 통계 목록
                [{"proxy_id": 1, "success_count": 5, "fail_count": 1, "avg_response_time": 1.2}, ...]

        Returns:
            업데이트된 프록시 수
        """
        updated_count = 0
        now = datetime.now()

        for stats in stats_list:
            proxy_id = stats.get("proxy_id")
            if not proxy_id:
                continue

            proxy = self.get_by_id(proxy_id)
            if not proxy:
                continue

            # 성공/실패 카운트 누적
            success_delta = stats.get("success_count", 0)
            fail_delta = stats.get("fail_count", 0)

            proxy.success_count = (proxy.success_count or 0) + success_delta
            proxy.total_checks = (proxy.total_checks or 0) + success_delta + fail_delta

            # 실패 카운트: 성공이 있으면 리셋, 아니면 누적
            if success_delta > 0:
                proxy.fail_count = fail_delta  # 리셋 후 새 실패만
                proxy.last_success_at = now
            else:
                proxy.fail_count = (proxy.fail_count or 0) + fail_delta

            # 응답시간 업데이트 (이동 평균)
            new_avg = stats.get("avg_response_time")
            if new_avg is not None:
                if proxy.avg_response_time is not None:
                    # 이동 평균: 기존 70% + 새로운 30%
                    proxy.avg_response_time = proxy.avg_response_time * 0.7 + new_avg * 0.3
                else:
                    proxy.avg_response_time = new_avg

            # min/max 응답시간
            min_rt = stats.get("min_response_time")
            max_rt = stats.get("max_response_time")
            if min_rt is not None:
                if proxy.min_response_time is None or min_rt < proxy.min_response_time:
                    proxy.min_response_time = min_rt
            if max_rt is not None:
                if proxy.max_response_time is None or max_rt > proxy.max_response_time:
                    proxy.max_response_time = max_rt

            # 마지막 체크 시간
            proxy.last_checked_at = now

            # 우선순위 점수 재계산
            proxy.priority_score = self.calculate_priority_score(proxy)

            # 상태 업데이트 (연속 실패 시 비활성화)
            if proxy.fail_count >= 7:
                proxy.status = "inactive"
            elif proxy.status == "pending" and success_delta > 0:
                proxy.status = "active"

            updated_count += 1

        try:
            self.db.commit()
            logger.debug(f"Batch updated {updated_count} proxies")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to batch update proxy stats: {e}")
            raise

        return updated_count


# 의존성 주입을 위한 팩토리 함수
def get_proxy_db_service(db: Session) -> ProxyDBService:
    """ProxyDBService 인스턴스 생성"""
    return ProxyDBService(db)
