"""Deterministic time-window scheduler used by scheduled workers."""

import hashlib
import random
from datetime import date as date_type, datetime, time, timedelta
from typing import List, Optional, Tuple

from ..models.schemas import TimeWindow


class InstagramScheduler:
    """Time-window based scheduler.

    동일한 날짜에는 동일한 스케줄을 생성합니다. ``start == end``는 하루
    전체 범위가 아니라 정확한 실행 시각으로 처리합니다.
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

    def _get_seed_for_date(self, date: date_type) -> int:
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

    def _window_to_minutes(self, window: TimeWindow) -> tuple[int, int]:
        """윈도우 시작/종료 시각을 분 단위로 변환."""
        start = self._parse_time(window.start)
        end = self._parse_time(window.end)
        return self._time_to_minutes(start), self._time_to_minutes(end)

    def _datetime_from_minutes(self, base_date: date_type, minutes: int) -> datetime:
        """기준 날짜와 분 단위 시각을 datetime으로 변환."""
        run_date = base_date
        if minutes >= 24 * 60:
            minutes -= 24 * 60
            run_date = base_date + timedelta(days=1)
        return datetime.combine(run_date, self._minutes_to_time(minutes))

    def generate_calendar_day_schedule(self, day: date_type) -> List[datetime]:
        """Calendar day에 표시/판정할 스케줄 후보를 반환."""
        candidates = (
            self.generate_daily_schedule(day - timedelta(days=1))
            + self.generate_daily_schedule(day)
        )
        return sorted(run_time for run_time in candidates if run_time.date() == day)

    def generate_daily_schedule(self, date: date_type = None) -> List[datetime]:
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

        if self.daily_runs <= 0 or not self.time_windows:
            return []

        times: list[datetime] = []
        exact_seen: set[int] = set()
        exact_windows: list[tuple[int, TimeWindow]] = []
        range_windows: list[tuple[int, int, TimeWindow]] = []

        for window in self.time_windows:
            start_minutes, end_minutes = self._window_to_minutes(window)
            if start_minutes == end_minutes:
                if start_minutes not in exact_seen:
                    exact_windows.append((start_minutes, window))
                    exact_seen.add(start_minutes)
                continue
            if end_minutes < start_minutes:
                end_minutes += 24 * 60
            range_windows.append((start_minutes, end_minutes, window))

        # Exact windows are explicit slots. When only exact slots exist, daily_runs is
        # an upper bound because inventing extra times would change the saved intent.
        for exact_minutes, _window in exact_windows[:self.daily_runs]:
            times.append(self._datetime_from_minutes(date, exact_minutes))

        remaining_runs = self.daily_runs - len(times)
        if remaining_runs > 0 and range_windows:
            for index in range(remaining_runs):
                start_minutes, end_minutes, _window = range_windows[index % len(range_windows)]
                random_minutes = rng.randint(start_minutes, end_minutes)
                times.append(self._datetime_from_minutes(date, random_minutes))

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

        candidate_dates = [
            now.date() - timedelta(days=1),
            now.date(),
            now.date() + timedelta(days=1),
        ]
        candidates = sorted(
            run_time
            for candidate_date in candidate_dates
            for run_time in self.generate_daily_schedule(candidate_date)
        )
        for run_time in candidates:
            if run_time > now:
                return run_time

        return None

    def get_due_run_time(
        self,
        last_run: Optional[datetime] = None,
        now: datetime = None,
        tolerance_minutes: int = 5,
        min_interval_hours: int = 0
    ) -> Optional[datetime]:
        """현재 허용 오차 내에서 실행해야 할 예정 시각 반환."""
        if now is None:
            now = datetime.now()

        if min_interval_hours > 0 and last_run is not None:
            min_interval = timedelta(hours=min_interval_hours)
            if (now - last_run) < min_interval:
                return None

        tolerance = timedelta(minutes=tolerance_minutes)
        candidates = sorted(
            self.generate_daily_schedule(now.date() - timedelta(days=1))
            + self.generate_daily_schedule(now.date())
        )

        for run_time in candidates:
            if run_time <= now <= run_time + tolerance:
                if last_run is None or last_run < run_time:
                    return run_time

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
        return self.get_due_run_time(
            last_run=last_run,
            now=now,
            tolerance_minutes=tolerance_minutes,
            min_interval_hours=min_interval_hours,
        ) is not None

    def get_completed_count(
        self,
        last_runs: List[datetime],
        date: date_type = None
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

        schedule = self.generate_calendar_day_schedule(now.date())
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
