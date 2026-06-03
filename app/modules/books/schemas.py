"""Books module Pydantic schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Disposal = Literal["undecided", "keep", "sell", "scan", "discard", "review"]
Condition = Literal["mint", "good", "fair", "poor", "damaged", "marked"]
AccessState = Literal["yes", "no", "check"]
SellStatus = Literal["none", "ready", "listed", "sold", "canceled", "unsellable"]
ScanStatus = Literal["none", "ready", "in_progress", "done", "canceled"]
DiscardStatus = Literal["none", "ready", "discarded", "canceled"]
ScanPurpose = Literal["guillotine", "non_destructive"]
BuybackGrade = Literal["최상", "상", "중"]
BuybackAvailability = Literal["yes", "no", "check", "error"]


class HighlightCreate(BaseModel):
    page: int = Field(default=0, ge=0)
    quote: str = Field(..., min_length=1)
    memo: str | None = None
    tags: list[str] = Field(default_factory=list)
    importance: int = Field(default=3, ge=1, le=5)
    photo: str | None = None


class HighlightResponse(HighlightCreate):
    id: int
    book_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BuybackQuoteResponse(BaseModel):
    id: int | None = None
    provider: str = "aladin"
    grade: BuybackGrade
    price: int | None = Field(None, ge=0)
    currency: str = "KRW"
    availability: BuybackAvailability = "check"
    raw_status: str = "unknown"
    message: str | None = None
    checked_at: datetime | None = None


class BuybackRecommendation(BaseModel):
    grade: BuybackGrade | None = None
    price: int | None = Field(None, ge=0)
    action: Literal["sell", "user_review", "no_buyback", "unknown"] = "unknown"
    message: str


class BookCreate(BaseModel):
    isbn: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=240)
    author: str = Field(..., min_length=1, max_length=160)
    publisher: str = ""
    published_year: int | None = Field(None, ge=0, le=3000)
    price: int | None = Field(None, ge=0)
    category: str = ""
    cover_url: str | None = None
    condition: Condition = "good"
    location: str = ""
    purchased_where: str | None = None
    purchased_used: bool | None = None
    purchased_price: int | None = Field(None, ge=0)
    reason: str | None = None
    reread_intent: int = Field(default=3, ge=1, le=5)
    notes: str | None = None
    accessibility_library: AccessState = "check"
    accessibility_millie: AccessState = "check"
    accessibility_ebook: AccessState = "check"
    accessibility_used_buyback: AccessState = "check"
    used_buyback_price: int | None = Field(None, ge=0)
    last_checked_at: str | None = None
    recommendation: Disposal = "undecided"
    disposal: Disposal = "undecided"
    sell_status: SellStatus = "none"
    scan_status: ScanStatus = "none"
    discard_status: DiscardStatus = "none"
    scan_purpose: ScanPurpose | None = None
    review_date: str | None = None
    highlights: list[HighlightCreate] = Field(default_factory=list)

    @field_validator("last_checked_at", "review_date")
    @classmethod
    def validate_iso_date(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise ValueError("date must be YYYY-MM-DD")
        return value


class BookUpdate(BaseModel):
    isbn: str | None = Field(None, min_length=1, max_length=32)
    title: str | None = Field(None, min_length=1, max_length=240)
    author: str | None = Field(None, min_length=1, max_length=160)
    publisher: str | None = None
    published_year: int | None = Field(None, ge=0, le=3000)
    price: int | None = Field(None, ge=0)
    category: str | None = None
    cover_url: str | None = None
    condition: Condition | None = None
    location: str | None = None
    purchased_where: str | None = None
    purchased_used: bool | None = None
    purchased_price: int | None = Field(None, ge=0)
    reason: str | None = None
    reread_intent: int | None = Field(None, ge=1, le=5)
    notes: str | None = None
    accessibility_library: AccessState | None = None
    accessibility_millie: AccessState | None = None
    accessibility_ebook: AccessState | None = None
    accessibility_used_buyback: AccessState | None = None
    used_buyback_price: int | None = Field(None, ge=0)
    last_checked_at: str | None = None
    recommendation: Disposal | None = None
    disposal: Disposal | None = None
    sell_status: SellStatus | None = None
    scan_status: ScanStatus | None = None
    discard_status: DiscardStatus | None = None
    scan_purpose: ScanPurpose | None = None
    review_date: str | None = None


class BookResponse(BaseModel):
    id: int
    isbn: str
    title: str
    author: str
    publisher: str
    published_year: int | None
    price: int | None
    category: str
    cover_url: str | None
    condition: Condition
    location: str
    purchased_where: str | None
    purchased_used: bool | None
    purchased_price: int | None
    reason: str | None
    reread_intent: int
    notes: str | None
    accessibility_library: AccessState
    accessibility_millie: AccessState
    accessibility_ebook: AccessState
    accessibility_used_buyback: AccessState
    used_buyback_price: int | None
    last_checked_at: str | None
    recommendation: Disposal
    disposal: Disposal
    sell_status: SellStatus
    scan_status: ScanStatus
    discard_status: DiscardStatus
    scan_purpose: ScanPurpose | None
    review_date: str | None
    highlights: list[HighlightResponse] = []
    buyback_quotes: list[BuybackQuoteResponse] = Field(default_factory=list)
    buyback_recommendation: BuybackRecommendation | None = None
    created_at: datetime
    updated_at: datetime


class BookListResponse(BaseModel):
    items: list[BookResponse]
    total: int
    offset: int
    limit: int


class BuybackRefreshResponse(BaseModel):
    book: BookResponse
    quotes: list[BuybackQuoteResponse] = Field(default_factory=list)
    availability: BuybackAvailability
    message: str | None = None

