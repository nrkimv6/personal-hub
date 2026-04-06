"""Popup URL monitor run history SQLAlchemy model."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base


class PopupUrlMonitorRun(Base):
    """Single monitor execution result."""

    __tablename__ = "popup_url_monitor_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(
        Integer,
        ForeignKey("popup_url_monitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(32), nullable=False, default="success")

    new_count = Column(Integer, nullable=False, default=0)
    has_new = Column(Boolean, nullable=False, default=False)

    proxy_url = Column(Text, nullable=True)
    request_profile = Column(String(1), nullable=True)
    fallback_applied = Column(Boolean, nullable=False, default=False)
    snapshot_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    monitor = relationship("PopupUrlMonitor", back_populates="runs")

    def __repr__(self) -> str:
        return (
            f"<PopupUrlMonitorRun(id={self.id}, monitor_id={self.monitor_id}, "
            f"status={self.status}, has_new={self.has_new})>"
        )

