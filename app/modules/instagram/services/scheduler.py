"""Instagram Scheduler - 하루 3번 랜덤 시간 스케줄링."""

import random
import hashlib
from datetime import datetime, time, timedelta
from typing import List, Optional, Tuple

from ..models.schemas import TimeWindow


class InstagramScheduler:
    """하루 3번 랜덤 시간에 크롤링 실행하는 스케줄러.

    동일한 날짜에는 동일한 스케줄을 생성합니다 (결정적 랜덤).
    """

    def __init__(
        self,
        daily_runs: int = 3,
        time_windows: Optional[List[TimeWindow]] = None,
        seed_prefix: str = "instagram_scheduler"
    ):
        """
        Args:
            daily_runs: 하루 실행 횟수 (기본 3)
            time_windows: 시간대 설정 리스트
            seed_prefix: 랜덤 시드 접두사 (테스트용)
        """
        self.daily_runs = daily_runs
        self.seed_prefix = seed_prefix

        if time_windows is None:
            self.time_windows = [
                TimeWindow(start="07:00", end="10:00"),
                TimeWindow(start="12:00", end="15:00"),
                TimeWindow(start="19:00", end="23:00"),
            ]
        else:
            self.time_windows = time_windows

    def _get_seed_for_date(self, date: datetime.date) -> int:
        """날짜별 결정적 시드 생성."""
        seed_str = f"{self.seed_prefix}_{date.isoformat()}"
        hash_value = hashlib.md5(seed_str.encode()).hexdigest()
        return int(hash_value[:8], 16)

    def _parse_time(self, time_str: str) -> time:
        """HH:MM 형식 문자열을 time 객체로 변환."""
        parts = time_str.split(":")
        return time(hour=int(parts[0]), minute=int(parts[1]))

    def _time_to_minutes(self, t: time) -> int:
        """time 객체를 분 단위로 변환."""
        return t.hour * 60 + t.minute

    def _minutes_to_time(self, minutes: int) -> time:
        """분 단위를 time 객체로 변환."""
        return time(hour=minutes // 60, minute=minutes % 60)

    def generate_daily_schedule(self, date: datetime.date = None) -> List[datetime]:
        """하루의 실행 시간 목록 생성.

        Args:
            date: 대상 날짜 (기본: 오늘)

        Returns:
            정렬된 실행 시간 datetime 목록
        """
        if date is None:
            date = datetime.now().date()

        # 날짜별 결정적 랜덤
        seed = self._get_seed_for_date(date)
        rng = random.Random(seed)

        times = []

        # 각 시간대에서 랜덤 시간 선택
        for window in self.time_windows[:self.daily_runs]:
            start = self._parse_time(window.start)
            end = self._parse_time(window.end)

            start_minutes = self._time_to_minutes(start)
            end_minutes = self._time_to_minutes(end)

            # 종료가 시작보다 작으면 (예: 23:00-01:00) 다음날로 간주
            if end_minutes <= start_minutes:
                end_minutes += 24 * 60

            random_minutes = rng.randint(start_minutes, end_minutes)

            # 24시간 초과 처리
            if random_minutes >= 24 * 60:
                random_minutes -= 24 * 60
                run_date = date + timedelta(days=1)
            else:
                run_date = date

            run_time = datetime.combine(
                run_date,
                self._minutes_to_time(random_minutes)
            )
            times.append(run_time)

        return sorted(times)

    def get_next_run_time(self, now: datetime = None) -> Optional[datetime]:
        """다음 실행 시간 반환.

        Args:
            now: 현재 시간 (기본: datetime.now())

        Returns:
            다음 실행 시간, 없으면 None
        """
        if now is None:
            now = datetime.now()

        # 오늘 스케줄에서 남은 실행 시간 확인
        today_schedule = self.generate_daily_schedule(now.date())
        for run_time in today_schedule:
            if run_time > now:
                return run_time

        # 오늘 모두 지남 → 내일 첫 실행
        tomorrow = now.date() + timedelta(days=1)
        tomorrow_schedule = self.generate_daily_schedule(tomorrow)

        if tomorrow_schedule:
            return tomorrow_schedule[0]

        return None

    def should_run_now(
        self,
        last_run: Optional[datetime] = None,
        now: datetime = None,
        tolerance_minutes: int = 5,
        min_interval_hours: int = 0
    ) -> bool:
        """현재 실행해야 하는지 확인.

        Args:
            last_run: 마지막 실행 시간
            now: 현재 시간 (기본: datetime.now())
            tolerance_minutes: 허용 오차 (분)
            min_interval_hours: 최소 실행 간격 (시간, 0이면 무시)

        Returns:
            실행해야 하면 True
        """
        if now is None:
            now = datetime.now()

        # 최소 간격 체크: 마지막 실행 후 min_interval_hours 시간이 지나지 않았으면 스킵
        if min_interval_hours > 0 and last_run is not None:
            min_interval = timedelta(hours=min_interval_hours)
            if (now - last_run) < min_interval:
                return False

        today_schedule = self.generate_daily_schedule(now.date())
        tolerance = timedelta(minutes=tolerance_minutes)

        for run_time in today_schedule:
            # 예정 시간이 지났고, 허용 범위 내
            if run_time <= now <= run_time + tolerance:
                # 마지막 실행이 이 시간 이전이면 실행
                if last_run is None or last_run < run_time:
                    return True

        return False

    def get_completed_count(
        self,
        last_runs: List[datetime],
        date: datetime.date = None
    ) -> int:
        """오늘 완료된 실행 횟수.

        Args:
            last_runs: 실행 기록 목록
            date: 대상 날짜 (기본: 오늘)

        Returns:
            완료된 실행 횟수
        """
        if date is None:
            date = datetime.now().date()

        return sum(1 for run in last_runs if run.date() == date)

    def get_today_schedule_status(
        self,
        last_runs: List[datetime],
        now: datetime = None
    ) -> List[Tuple[datetime, bool]]:
        """오늘 스케줄의 완료 상태.

        Args:
            last_runs: 실행 기록 목록
            now: 현재 시간

        Returns:
            (실행 시간, 완료 여부) 튜플 목록
        """
        if now is None:
            now = datetime.now()

        schedule = self.generate_daily_schedule(now.date())
        result = []

        for run_time in schedule:
            # 해당 시간대에 실행된 기록이 있는지 확인
            completed = any(
                run.date() == run_time.date() and
                abs((run - run_time).total_seconds()) < 3600  # 1시간 이내
                for run in last_runs
            )
            result.append((run_time, completed))

        return result
