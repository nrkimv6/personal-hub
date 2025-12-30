# Core module - 핵심 인프라
from app.core.config import settings, logger, setup_logging, Settings
from app.core.database import get_db, SessionLocal, Base, engine, init_extra_tables
from app.core.dependencies import get_notification_service, get_db_session
from app.core.exceptions import (
    AppException,
    NotFoundError,
    ValidationError,
    DatabaseError,
    BrowserError,
    BookingError,
)

__all__ = [
    # config
    "settings",
    "logger",
    "setup_logging",
    "Settings",
    # database
    "get_db",
    "SessionLocal",
    "Base",
    "engine",
    "init_extra_tables",
    # dependencies
    "get_notification_service",
    "get_db_session",
    # exceptions
    "AppException",
    "NotFoundError",
    "ValidationError",
    "DatabaseError",
    "BrowserError",
    "BookingError",
]
