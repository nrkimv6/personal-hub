"""Popup URL monitor SQLAlchemy model."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base


class PopupUrlMonitor(Base):
    """Popup URL monitor configuration."""

    __tablename__ = "popup_url_monitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    url = Column(Text, nullable=False)
    monitor_kind = Column(String(32), nullable=False, default="popup_list")

    request_profile = Column(String(1), nullable=False, default="A")
    fallback_strategy = Column(String(32), nullable=False, default="reinforce")
    proxy_enabled = Column(Boolean, nullable=False, default=False)

    notify_on_new = Column(Boolean, nullable=False, default=True)
    min_new_count = Column(Integer, nullable=False, default=1)
    stop_on_detected = Column(Boolean, nullable=False, default=False)
    detected_at = Column(DateTime, nullable=True)

    monitoring_mode = Column(String(32), nullable=False, default="anonymous")
    service_account_id = Column(
        Integer,
        ForeignKey("service_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    browser_fallback_enabled = Column(Boolean, nullable=False, default=False)
    is_enabled = Column(Boolean, nullable=False, default=True)

    latest_snapshot_json = Column(Text, nullable=True)
    latest_snapshot_hash = Column(String(128), nullable=True)
    latest_checked_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    service_account = relationship("ServiceAccount")
    runs = relationship(
        "PopupUrlMonitorRun",
        back_populates="monitor",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PopupUrlMonitor(id={self.id}, url={self.url!r}, enabled={self.is_enabled})>"

