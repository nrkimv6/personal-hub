import json
import pytest
from datetime import datetime, timedelta
from typing import Optional
from pydantic import ValidationError

from app.modules.dev_runner.schemas import RunRequest

class TestCorrectConformance:
    """CORRECT principles testing for RunRequest schema and argument validations"""

    def test_conformance_schema_to_cli(self):
        """Conformance - RunRequest 필드 1:1 매핑 확인"""
        # 스키마의 기본값이 CLI의 기본 동작 방식과 일치해야 함
        request = RunRequest(
            engine="gemini",
            plan_file="test.md",
            max_cycles=3,
            max_tokens=5000,
            until="15:00",
            dry_run=True,
            skip_plan=True,
            parallel=True,
            projects="test1,test2"
        )
        assert request.engine == "gemini"
        assert request.plan_file == "test.md"
        assert request.max_cycles == 3
        assert request.max_tokens == 5000
        assert request.until == "15:00"
        assert request.dry_run is True
        assert request.skip_plan is True
        assert request.parallel is True
        assert request.projects == "test1,test2"

    def test_range_max_cycles(self):
        """Range - max_cycles 타입 범위 검증"""
        # 문자열을 넣으면 pydantic이 int로 변환 가능한지 시도, 불가능하면 에러
        with pytest.raises(ValidationError):
            RunRequest(max_cycles="not-a-number")

    def test_existence_plan_file_behavior(self):
        """Existence - 필수 파일 누락 시 동작 의도 확인"""
        # RunRequest 스키마 자체에서는 plan_file이 Optional이지만, 
        # API 레이어(ExecutorService)에서는 parallel=False일 때 plan_file이 없으면
        # cli에서 거부하도록 설계되어 있음. 스키마가 이를 허용하는지(Optional[str]) 확인.
        # 엔진 기본값은 settings 단계에서 해석되므로 요청 스키마 기본값은 None이다.
        req = RunRequest(parallel=False)
        assert req.plan_file is None
        assert req.engine is None

    def test_time_until_format(self):
        """Time - until 시간 형식 검증"""
        # CLI에서 HH:MM을 요구하지만 Pydantic에서 강제하고 있지는 않음
        # 추후 Pydantic Regex Validator를 추가할 수 있는 기반 테스트
        req = RunRequest(until="15:00")
        assert ":" in req.until
        
    def test_time_until_logic_simulation(self):
        """Time - until 시간이 과거일 때 익일로 처리하는 로직 모의 검증"""
        until_str = "01:00" # 과거 혹은 미래
        hour, minute = map(int, until_str.split(':'))
        
        now = datetime.now()
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If target is already past, it should add 1 day
        if target_time < now:
            expected_target = target_time + timedelta(days=1)
        else:
            expected_target = target_time
            
        assert expected_target >= now
