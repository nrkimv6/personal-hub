"""Dismissed duplicate pair model."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint

from .base import Base


class DismissedDuplicate(Base):
    """A user-dismissed duplicate candidate pair.

    The two entity ids are stored in sorted order so the same pair has one
    canonical row regardless of request ordering.
    """

    __tablename__ = "dismissed_duplicates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String, nullable=False, index=True)
    entity1_id = Column(Integer, nullable=False)
    entity2_id = Column(Integer, nullable=False)
    dismissed_at = Column(DateTime, default=datetime.now, nullable=False)
    dismissed_by = Column(String)

    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity1_id",
            "entity2_id",
            name="uq_dismissed_duplicates_pair",
        ),
        Index("idx_dismissed_duplicates_lookup", "entity_type", "entity1_id", "entity2_id"),
    )

    @classmethod
    def ordered_pair(cls, first_id: int, second_id: int) -> tuple[int, int]:
        return (first_id, second_id) if first_id <= second_id else (second_id, first_id)
