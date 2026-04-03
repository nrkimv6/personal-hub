"""Shared enum and literal schemas for slide scanner."""

from enum import Enum
from typing import Literal


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RemoteDeleteStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class HandoffStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


ApprovalStatusLiteral = Literal["PENDING", "APPROVED", "REJECTED"]
RemoteDeleteStatusLiteral = Literal["PENDING", "DONE", "FAILED"]
HandoffStatusLiteral = Literal["PENDING", "DONE", "FAILED"]


__all__ = [
    "ApprovalStatus",
    "RemoteDeleteStatus",
    "HandoffStatus",
    "ApprovalStatusLiteral",
    "RemoteDeleteStatusLiteral",
    "HandoffStatusLiteral",
]
