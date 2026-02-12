"""
API 비용 추적 모듈

api_usage / api_limits 테이블 연동
- 일일/월간 리밋 체크
- 80% 도달 시 경고
- 초과 시 모델 자동 전환
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class CostTracker:
    """API 비용 추적"""

    def __init__(self, db: Session):
        self.db = db

    def record_usage(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        image_count: int = 0,
    ) -> float:
        """
        API 사용량 기록

        Args:
            model: 모델명 (claude-3-sonnet, gemini-flash 등)
            input_tokens: 입력 토큰 수
            output_tokens: 출력 토큰 수
            image_count: 이미지 수

        Returns:
            예상 비용 (USD)
        """
        today = date.today().isoformat()

        # 비용 계산 (모델별 요금)
        cost = self._calculate_cost(model, input_tokens, output_tokens, image_count)

        # DB 저장
        insert_query = text("""
            INSERT INTO api_usage (date, model, input_tokens, output_tokens, image_count, estimated_cost_usd)
            VALUES (:date, :model, :input_tokens, :output_tokens, :image_count, :cost)
        """)
        self.db.execute(insert_query, {
            "date": today,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "image_count": image_count,
            "cost": cost,
        })
        self.db.commit()

        logger.info(f"API usage recorded: {model} - ${cost:.4f}")

        return cost

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        image_count: int,
    ) -> float:
        """
        모델별 비용 계산 (USD)

        참고: 실제 요금은 변동될 수 있음
        """
        cost = 0.0

        if "claude" in model.lower():
            # Claude 3 Sonnet 기준
            cost += (input_tokens / 1_000_000) * 3.0  # $3 per 1M input tokens
            cost += (output_tokens / 1_000_000) * 15.0  # $15 per 1M output tokens
            cost += image_count * 0.00048  # ~$0.48 per 1K images
        elif "gemini" in model.lower():
            # Gemini Flash 기준
            cost += (input_tokens / 1_000_000) * 0.075  # $0.075 per 1M tokens
            cost += (output_tokens / 1_000_000) * 0.30  # $0.30 per 1M tokens
            cost += image_count * 0.00001  # 매우 저렴
        else:
            # 기본 추정
            cost += (input_tokens / 1_000_000) * 1.0
            cost += (output_tokens / 1_000_000) * 5.0
            cost += image_count * 0.0001

        return cost

    def get_daily_usage(self, target_date: Optional[str] = None) -> Dict:
        """
        일일 사용량 조회

        Args:
            target_date: 조회할 날짜 (YYYY-MM-DD), None이면 오늘

        Returns:
            사용량 통계
        """
        if not target_date:
            target_date = date.today().isoformat()

        query = text("""
            SELECT
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(image_count) as total_images,
                SUM(estimated_cost_usd) as total_cost
            FROM api_usage
            WHERE date = :date
        """)
        result = self.db.execute(query, {"date": target_date}).fetchone()

        if not result:
            return {
                "date": target_date,
                "input_tokens": 0,
                "output_tokens": 0,
                "images": 0,
                "cost": 0.0,
            }

        return {
            "date": target_date,
            "input_tokens": result.total_input_tokens or 0,
            "output_tokens": result.total_output_tokens or 0,
            "images": result.total_images or 0,
            "cost": float(result.total_cost or 0.0),
        }

    def get_monthly_usage(self, year: int, month: int) -> Dict:
        """
        월간 사용량 조회

        Args:
            year: 연도
            month: 월 (1~12)

        Returns:
            사용량 통계
        """
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-31"

        query = text("""
            SELECT
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(image_count) as total_images,
                SUM(estimated_cost_usd) as total_cost
            FROM api_usage
            WHERE date >= :start_date AND date <= :end_date
        """)
        result = self.db.execute(query, {
            "start_date": start_date,
            "end_date": end_date,
        }).fetchone()

        if not result:
            return {
                "year": year,
                "month": month,
                "input_tokens": 0,
                "output_tokens": 0,
                "images": 0,
                "cost": 0.0,
            }

        return {
            "year": year,
            "month": month,
            "input_tokens": result.total_input_tokens or 0,
            "output_tokens": result.total_output_tokens or 0,
            "images": result.total_images or 0,
            "cost": float(result.total_cost or 0.0),
        }

    def check_limits(self) -> Dict:
        """
        리밋 체크 (일일/월간)

        Returns:
            리밋 상태 정보
        """
        # 일일 리밋
        daily_limit_query = text("""
            SELECT max_cost_usd, max_images
            FROM api_limits
            WHERE limit_type = 'daily' AND is_active = 1
            LIMIT 1
        """)
        daily_limit = self.db.execute(daily_limit_query).fetchone()

        daily_usage = self.get_daily_usage()

        daily_status = {
            "type": "daily",
            "usage": daily_usage,
            "limit": None,
            "percent": 0.0,
            "exceeded": False,
            "warning": False,
        }

        if daily_limit:
            max_cost = daily_limit.max_cost_usd
            max_images = daily_limit.max_images

            if max_cost:
                percent = (daily_usage["cost"] / max_cost) * 100
                daily_status["limit"] = {"cost": max_cost, "images": max_images}
                daily_status["percent"] = percent
                daily_status["exceeded"] = percent >= 100
                daily_status["warning"] = percent >= 80

        # 월간 리밋
        now = datetime.now()
        monthly_limit_query = text("""
            SELECT max_cost_usd, max_images
            FROM api_limits
            WHERE limit_type = 'monthly' AND is_active = 1
            LIMIT 1
        """)
        monthly_limit = self.db.execute(monthly_limit_query).fetchone()

        monthly_usage = self.get_monthly_usage(now.year, now.month)

        monthly_status = {
            "type": "monthly",
            "usage": monthly_usage,
            "limit": None,
            "percent": 0.0,
            "exceeded": False,
            "warning": False,
        }

        if monthly_limit:
            max_cost = monthly_limit.max_cost_usd
            max_images = monthly_limit.max_images

            if max_cost:
                percent = (monthly_usage["cost"] / max_cost) * 100
                monthly_status["limit"] = {"cost": max_cost, "images": max_images}
                monthly_status["percent"] = percent
                monthly_status["exceeded"] = percent >= 100
                monthly_status["warning"] = percent >= 80

        return {
            "daily": daily_status,
            "monthly": monthly_status,
        }

    def should_switch_model(self) -> Optional[str]:
        """
        리밋 초과 시 모델 전환 권장

        Returns:
            권장 모델명 (None이면 전환 불필요)
        """
        limits = self.check_limits()

        # 일일/월간 중 하나라도 초과 시
        if limits["daily"]["exceeded"] or limits["monthly"]["exceeded"]:
            logger.warning("API limit exceeded, recommending model switch")
            return "cli"  # CLI 모드로 전환

        # 경고 수준 (80%) 도달 시
        if limits["daily"]["warning"] or limits["monthly"]["warning"]:
            logger.warning("API limit warning (80% reached)")
            # 여전히 사용 가능하지만 경고만

        return None
