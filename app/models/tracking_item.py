"""Tracking item ORM model."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class TrackingItem(Base):
    """Deadline/start-date based tracking item independent from plan records."""

    __tablename__ = "tracking_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    start_at = Column(DateTime, nullable=True, index=True)
    due_at = Column(DateTime, nullable=True, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    linked_plans = relationship(
        "TrackingItemPlanLink",
        back_populates="tracking_item",
        lazy="select",
        order_by="TrackingItemPlanLink.created_at",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<TrackingItem(id={self.id}, title={self.title!r})>"


class TrackingItemPlanLink(Base):
    """Tracking 항목 ↔ Plan 레코드 N:N 링크 테이블."""

    __tablename__ = "tracking_item_plan_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_item_id = Column(
        Integer, ForeignKey("tracking_items.id", ondelete="CASCADE"), nullable=False
    )
    plan_record_id = Column(
        Integer, ForeignKey("plan_records.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        UniqueConstraint("tracking_item_id", "plan_record_id", name="uq_tracking_item_plan_link"),
        Index("ix_tracking_links_tracking_id", "tracking_item_id"),
        Index("ix_tracking_links_plan_record_id", "plan_record_id"),
    )

    tracking_item = relationship("TrackingItem", back_populates="linked_plans")
    plan_record = relationship("PlanRecord", back_populates="tracking_links")

    def __repr__(self) -> str:
        return f"<TrackingItemPlanLink(id={self.id}, tracking_item_id={self.tracking_item_id}, plan_record_id={self.plan_record_id})>"
