"""Sleep Now API routes for monitor-page integration"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
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


def _verify_password(password: str) -> bool:
    """Verify emergency unlock password"""
    if not CONFIG_FILE.exists():
        return False

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    stored_hash = config.get("emergency", {}).get("password_hash", "")

    if not stored_hash:
        return False

    input_hash = hashlib.sha256(password.encode()).hexdigest()
    return input_hash == stored_hash


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
