"""Sleep Now API routes for monitor-page integration"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import hmac
import json
import copy
import re
import sys

router = APIRouter(prefix="/api/v1/sleep-now", tags=["sleep-now"])

# Sleep Now 프로젝트 경로
SLEEP_NOW_PATH = Path("d:/work/project/tools/sleep-now")
STATUS_FILE = SLEEP_NOW_PATH / "data/status.json"
LOGS_DIR = SLEEP_NOW_PATH / "logs/daily"
CONFIG_FILE = SLEEP_NOW_PATH / "config/settings.json"


class EmergencyUnlockRequest(BaseModel):
    password: str
    reason: str = ""


class SleepNowStatus(BaseModel):
    is_active: bool
    mode: str
    block_start: datetime | None = None
    block_end: datetime | None = None
    grace_until: datetime | None = None
    bypass_attempts_today: int = 0


class LogEntry(BaseModel):
    timestamp: datetime
    type: str
    reason: str | None = None
    details: dict | None = None


class DailyStats(BaseModel):
    date: str
    block_duration_minutes: int = 0
    bypass_attempts: int = 0
    emergency_unlocks: int = 0
    estimated_sleep_time: str | None = None


def _load_status() -> dict:
    """Load status from file"""
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return {
        "is_active": False,
        "mode": "disabled",
        "block_start": None,
        "block_end": None,
        "grace_until": None,
        "bypass_attempts_today": 0,
    }


def _save_status(status: dict) -> None:
    """Save status to file"""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    status["last_updated"] = datetime.now().isoformat()
    STATUS_FILE.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")


def _log_event(event_type: str, details: dict | None = None) -> None:
    """Log event to daily log file"""
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"{today}.json"

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if log_file.exists():
        data = json.loads(log_file.read_text(encoding="utf-8"))
    else:
        data = {"date": today, "events": [], "stats": {
            "bypass_attempts": 0,
            "emergency_unlocks": 0,
        }}

    data["events"].append({
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        **(details or {}),
    })

    # Update stats
    if event_type == "bypass_attempt":
        data["stats"]["bypass_attempts"] = data["stats"].get("bypass_attempts", 0) + 1
    elif event_type == "emergency_unlock":
        data["stats"]["emergency_unlocks"] = data["stats"].get("emergency_unlocks", 0) + 1

    log_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_config() -> dict:
    """Load settings.json from sleep-now project"""
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _save_config(config: dict) -> None:
    """Save settings.json to sleep-now project"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def _trigger_reload() -> bool:
    """sleep-now 서비스에 리로드 트리거 생성

    Returns:
        트리거 파일 생성 성공 여부
    """
    trigger_path = SLEEP_NOW_PATH / "data/reload_trigger"
    try:
        trigger_path.parent.mkdir(parents=True, exist_ok=True)
        trigger_path.write_text(datetime.now().isoformat(), encoding="utf-8")
        return True
    except Exception as e:
        return False


def _verify_password(password: str) -> bool:
    """Verify emergency unlock password with timing-attack resistance"""
    config = _load_config()
    stored_hash = config.get("emergency", {}).get("password_hash", "")

    if not stored_hash:
        return False

    input_hash = hashlib.sha256(password.encode()).hexdigest()
    # Use hmac.compare_digest to prevent timing attacks
    return hmac.compare_digest(stored_hash, input_hash)


# ==================== 설정 관리 상수 & 헬퍼 ====================

# PUT /config에서 변경 차단할 필드 (password_hash는 PUT /password 전용)
PROTECTED_FIELDS: dict[str, list[str]] = {
    "emergency": ["password_hash"],
}

# 변경 시 서비스 재시작이 필요한 섹션
RESTART_REQUIRED_SECTIONS: list[str] = ["session_worker", "browsers"]


def _deep_merge(base: dict, override: dict) -> dict:
    """dict를 재귀적으로 deep merge합니다.

    ⚠️ list 필드는 merge가 아닌 전체 교체됩니다.
    base를 복사한 뒤 override 키를 반복하며,
    양쪽 모두 dict인 경우 재귀 호출, 아닌 경우 override 값으로 대체합니다.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_config(config: dict) -> str | None:
    """sleep-now의 Settings.model_validate(config)로 유효성 검증합니다.

    Returns:
        성공 시 None, 실패 시 에러 메시지 str
    """
    try:
        sleep_now_src = str(SLEEP_NOW_PATH / "src")
        if sleep_now_src not in sys.path:
            sys.path.insert(0, sleep_now_src)
        from config import Settings
        Settings.model_validate(config)
        return None
    except Exception as e:
        return str(e)


def _mask_sensitive_fields(config: dict) -> dict:
    """GET 응답 시 민감한 필드를 마스킹합니다.

    emergency.password_hash를 "***"로 마스킹합니다.
    원본 dict 수정 방지를 위해 copy.deepcopy를 사용합니다.
    """
    masked = copy.deepcopy(config)
    if "emergency" in masked and "password_hash" in masked["emergency"]:
        masked["emergency"]["password_hash"] = "***"
    return masked


@router.get("/status", response_model=SleepNowStatus)
async def get_status():
    """현재 차단 상태 조회"""
    data = _load_status()

    # Parse datetime fields
    for field in ["block_start", "block_end", "grace_until"]:
        if data.get(field):
            try:
                data[field] = datetime.fromisoformat(data[field])
            except (ValueError, TypeError):
                data[field] = None

    return SleepNowStatus(**data)


@router.post("/emergency-unlock")
async def emergency_unlock(request: EmergencyUnlockRequest):
    """긴급 해제 (1시간 유예)"""
    # Verify password
    if not _verify_password(request.password):
        _log_event("emergency_unlock_failed", {"reason": "invalid_password"})
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다")

    # Set grace period
    grace_until = datetime.now() + timedelta(hours=1)

    status = _load_status()
    status["grace_until"] = grace_until.isoformat()
    _save_status(status)

    # Restore firewall
    try:
        sys.path.insert(0, str(SLEEP_NOW_PATH / "src"))
        from services.firewall import FirewallService
        FirewallService().restore_all()
    except Exception as e:
        # Log but don't fail - status is already updated
        _log_event("firewall_restore_error", {"error": str(e)})

    _log_event("emergency_unlock", {
        "reason": request.reason,
        "grace_until": grace_until.isoformat(),
    })

    return {
        "success": True,
        "grace_until": grace_until,
        "message": "1시간 유예가 적용되었습니다.",
    }


@router.get("/logs")
async def get_logs(days: int = 7) -> list[LogEntry]:
    """최근 N일 로그 조회"""
    logs = []

    if not LOGS_DIR.exists():
        return logs

    for log_file in sorted(LOGS_DIR.glob("*.json"), reverse=True)[:days]:
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            for event in data.get("events", []):
                logs.append(LogEntry(
                    timestamp=datetime.fromisoformat(event["timestamp"]),
                    type=event["type"],
                    reason=event.get("reason"),
                    details={k: v for k, v in event.items() if k not in ["timestamp", "type", "reason"]},
                ))
        except Exception:
            continue

    return logs


@router.get("/stats")
async def get_stats(days: int = 7) -> list[DailyStats]:
    """일별 통계 조회"""
    stats = []

    if not LOGS_DIR.exists():
        return stats

    for log_file in sorted(LOGS_DIR.glob("*.json"), reverse=True)[:days]:
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            file_stats = data.get("stats", {})
            stats.append(DailyStats(
                date=data.get("date", log_file.stem),
                bypass_attempts=file_stats.get("bypass_attempts", 0),
                emergency_unlocks=file_stats.get("emergency_unlocks", 0),
                estimated_sleep_time=file_stats.get("estimated_sleep_time"),
            ))
        except Exception:
            continue

    return stats


@router.get("/schedule")
async def get_schedule():
    """오늘의 스케줄 조회"""
    if CONFIG_FILE.exists():
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        schedule = config.get("schedule", {})
    else:
        schedule = {
            "warning_times": ["23:00", "23:30", "23:45", "23:50"],
            "block_start": "00:00",
            "block_end": "07:00",
        }

    return {
        "warning_times": schedule.get("warning_times", []),
        "block_start": schedule.get("block_start", "00:00"),
        "block_end": schedule.get("block_end", "07:00"),
    }


@router.post("/skip-today")
async def skip_today(request: EmergencyUnlockRequest):
    """오늘 하루 비활성화 (비밀번호 필요)"""
    if not _verify_password(request.password):
        _log_event("skip_today_failed", {"reason": "invalid_password"})
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다")

    # Set grace period until tomorrow 7 AM
    now = datetime.now()
    tomorrow_7am = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)

    status = _load_status()
    status["grace_until"] = tomorrow_7am.isoformat()
    _save_status(status)

    # Restore firewall if currently blocking
    if status.get("is_active"):
        try:
            sys.path.insert(0, str(SLEEP_NOW_PATH / "src"))
            from services.firewall import FirewallService
            FirewallService().restore_all()
        except Exception:
            pass

    _log_event("skip_today", {
        "reason": request.reason,
        "grace_until": tomorrow_7am.isoformat(),
    })

    return {
        "success": True,
        "grace_until": tomorrow_7am,
        "message": "오늘 하루 비활성화되었습니다.",
    }


# ==================== 설정 변경 API ====================


class ScheduleUpdateRequest(BaseModel):
    """스케줄 설정 변경 요청"""
    password: str
    warning_times: list[str] | None = None
    block_start: str | None = None
    block_end: str | None = None

    @field_validator('warning_times')
    @classmethod
    def validate_warning_times(cls, v):
        if v is None:
            return v
        time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
        for time_str in v:
            if not time_pattern.match(time_str):
                raise ValueError(f'Invalid time format: {time_str}. Use HH:MM format.')
        return v

    @field_validator('block_start', 'block_end')
    @classmethod
    def validate_time(cls, v):
        if v is None:
            return v
        time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
        if not time_pattern.match(v):
            raise ValueError(f'Invalid time format: {v}. Use HH:MM format.')
        return v


class PasswordChangeRequest(BaseModel):
    """비밀번호 변경 요청"""
    current_password: str
    new_password: str
    confirm_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        if len(v) < 16:
            raise ValueError('Password must be at least 16 characters')
        return v


class ConfigUpdateRequest(BaseModel):
    """범용 설정 변경 요청"""
    password: str
    config: dict


class DateExceptionRequest(BaseModel):
    """날짜 예외 추가/수정 요청"""
    password: str
    date: str
    enabled: bool = False
    reason: str = ""

    @field_validator('date')
    @classmethod
    def validate_date(cls, v):
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
            raise ValueError('날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.')
        return v


class DeleteExceptionRequest(BaseModel):
    """날짜 예외 삭제 요청 (비밀번호 request body로 전달, URL 로그 노출 방지)"""
    password: str


@router.put("/schedule")
async def update_schedule(request: ScheduleUpdateRequest):
    """스케줄 설정 변경 (비밀번호 인증 필요)"""
    # 비밀번호 검증
    if not _verify_password(request.password):
        _log_event("schedule_update_failed", {"reason": "invalid_password"})
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다")

    # 설정 파일 로드
    config = _load_config()

    # Phase 3 복수 블록 지원: blocks 배열 사용
    if "blocks" in config.get("schedule", {}) and config["schedule"]["blocks"]:
        # Multi-block mode: 첫 번째 블록 수정
        schedule = config["schedule"]
        if not schedule["blocks"]:
            schedule["blocks"] = [{
                "name": "night",
                "enabled": True,
                "warning_times": ["23:00", "23:30", "23:45", "23:50"],
                "block_start": "00:00",
                "block_end": "07:00"
            }]

        block = schedule["blocks"][0]
    else:
        # Legacy mode: 직접 schedule 필드 수정
        schedule = config.get("schedule", {})
        block = schedule

    # 변경사항 적용
    updated = False
    if request.warning_times is not None:
        if len(request.warning_times) < 1:
            raise HTTPException(status_code=400, detail="최소 1개의 경고 시간이 필요합니다")
        block["warning_times"] = request.warning_times
        updated = True

    if request.block_start is not None:
        block["block_start"] = request.block_start
        updated = True

    if request.block_end is not None:
        block["block_end"] = request.block_end
        updated = True

    if not updated:
        raise HTTPException(status_code=400, detail="변경할 항목이 없습니다")

    # 설정 저장
    config["schedule"] = schedule

    # 유효성 검증 (_validate_config 재사용)
    error = _validate_config(config)
    if error:
        raise HTTPException(status_code=400, detail=f"설정 유효성 검증 실패: {error}")

    _save_config(config)

    _log_event("schedule_updated", {
        "warning_times": block.get("warning_times"),
        "block_start": block.get("block_start"),
        "block_end": block.get("block_end"),
    })

    # ★ sleep-now 서비스에 리로드 트리거 생성
    trigger_success = _trigger_reload()

    if trigger_success:
        message = "스케줄이 업데이트되었습니다. 1분 이내 자동 반영됩니다."
        restart_required = False
    else:
        message = "스케줄이 저장되었으나 서비스 재시작이 필요합니다."
        restart_required = True

    return {
        "success": True,
        "message": message,
        "schedule": {
            "warning_times": block.get("warning_times"),
            "block_start": block.get("block_start"),
            "block_end": block.get("block_end"),
        },
        "restart_required": restart_required,
    }


@router.put("/password")
async def change_password(request: PasswordChangeRequest):
    """비상 비밀번호 변경"""
    # 현재 비밀번호 검증
    if not _verify_password(request.current_password):
        _log_event("password_change_failed", {"reason": "current_password_mismatch"})
        raise HTTPException(status_code=401, detail="현재 비밀번호가 올바르지 않습니다")

    # 새 비밀번호 확인
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="새 비밀번호가 일치하지 않습니다")

    # 현재와 동일한 비밀번호 체크
    if request.current_password == request.new_password:
        raise HTTPException(status_code=400, detail="새 비밀번호는 현재와 달라야 합니다")

    # 새 비밀번호 해시 생성 및 저장
    new_hash = hashlib.sha256(request.new_password.encode()).hexdigest()

    config = _load_config()
    if "emergency" not in config:
        config["emergency"] = {}
    config["emergency"]["password_hash"] = new_hash
    _save_config(config)

    _log_event("password_changed", {"new_hash_prefix": new_hash[:8]})

    return {
        "success": True,
        "message": "비밀번호가 변경되었습니다",
    }


# ==================== 설정 조회/변경 API (범용) ====================


@router.get("/config")
async def get_config():
    """전체 설정 조회 (password_hash 마스킹)"""
    config = _load_config()
    return _mask_sensitive_fields(config)


@router.post("/config/schedule/exceptions")
async def add_date_exception(request: DateExceptionRequest):
    """날짜 예외 추가/수정 (비밀번호 필요)

    ⚠️ 라우트 선언 순서: /config/{section} 보다 먼저 선언하여 FastAPI 매칭 충돌 방지
    """
    if not _verify_password(request.password):
        _log_event("date_exception_failed", {"reason": "invalid_password"})
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다")

    config = _load_config()
    if "schedule" not in config:
        config["schedule"] = {}
    if "exceptions" not in config["schedule"]:
        config["schedule"]["exceptions"] = {}

    config["schedule"]["exceptions"][request.date] = {
        "enabled": request.enabled,
        "reason": request.reason,
    }

    _save_config(config)
    _trigger_reload()
    _log_event("date_exception_added", {
        "date": request.date,
        "enabled": request.enabled,
        "reason": request.reason,
    })

    return {
        "success": True,
        "message": f"{request.date} 날짜 예외가 설정되었습니다.",
        "exception": config["schedule"]["exceptions"][request.date],
    }


@router.delete("/config/schedule/exceptions/{date}")
async def delete_date_exception(date: str, request: DeleteExceptionRequest):
    """날짜 예외 삭제 (비밀번호 request body로 전달, URL 로그 노출 방지)

    ⚠️ 라우트 선언 순서: /config/{section} 보다 먼저 선언하여 FastAPI 매칭 충돌 방지
    """
    # 날짜 형식 검증
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(
            status_code=400,
            detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요."
        )

    if not _verify_password(request.password):
        _log_event("date_exception_delete_failed", {"reason": "invalid_password"})
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다")

    config = _load_config()
    exceptions = config.get("schedule", {}).get("exceptions", {})

    if date not in exceptions:
        raise HTTPException(status_code=404, detail=f"{date} 날짜 예외가 존재하지 않습니다")

    del config["schedule"]["exceptions"][date]
    _save_config(config)
    _trigger_reload()

    return {
        "success": True,
        "message": f"{date} 날짜 예외가 삭제되었습니다.",
    }


@router.get("/config/{section}")
async def get_config_section(section: str):
    """섹션별 설정 조회 (존재하지 않는 섹션은 404 반환)

    emergency 섹션은 password_hash 마스킹 적용
    """
    config = _load_config()
    if section not in config:
        raise HTTPException(status_code=404, detail=f"섹션 '{section}'을 찾을 수 없습니다")

    section_data = config[section]
    if section == "emergency" and isinstance(section_data, dict) and "password_hash" in section_data:
        section_data = dict(section_data)
        section_data["password_hash"] = "***"

    return section_data


@router.put("/config")
async def update_config(request: ConfigUpdateRequest):
    """범용 설정 변경 API (비밀번호 필요, deep merge)

    ⚠️ list 필드(warning_times, kill_targets.kill 등)는 merge가 아닌 전체 교체됩니다.
    emergency.password_hash는 PUT /password 전용으로 이 API에서 변경 불가합니다.
    """
    if not _verify_password(request.password):
        _log_event("config_update_failed", {"reason": "invalid_password"})
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다")

    # PROTECTED_FIELDS 차단 검증
    for section, fields in PROTECTED_FIELDS.items():
        if section in request.config:
            for field in fields:
                if field in request.config[section]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"'{section}.{field}'은(는) 직접 변경할 수 없습니다. PUT /password를 사용하세요."
                    )

    # 현재 설정 로드 후 deep merge
    current_config = _load_config()
    merged_config = _deep_merge(current_config, request.config)

    # Pydantic 유효성 검증
    error = _validate_config(merged_config)
    if error:
        raise HTTPException(status_code=400, detail=f"설정 유효성 검증 실패: {error}")

    # 저장 및 리로드
    _save_config(merged_config)
    _trigger_reload()
    _log_event("config_updated", {"sections": list(request.config.keys())})

    # restart_required 판별
    changed_sections = set(request.config.keys())
    restart_required = bool(changed_sections & set(RESTART_REQUIRED_SECTIONS))

    return {
        "success": True,
        "message": (
            "설정이 업데이트되었습니다. 서비스 재시작이 필요합니다."
            if restart_required
            else "설정이 업데이트되었습니다. 1분 이내 자동 반영됩니다."
        ),
        "sections_updated": list(changed_sections),
        "restart_required": restart_required,
    }
