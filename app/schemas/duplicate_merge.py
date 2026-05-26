"""Schemas for event duplicate review and manual merge APIs."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EntityType = Literal["event"]
FieldSource = Literal["primary", "secondary"]

MERGE_FIELD_WHITELIST = {
    "title",
    "event_url",
    "url_type",
    "additional_urls",
    "event_start",
    "event_end",
    "announcement_date",
    "organizer",
    "summary",
    "body_text",
    "prizes",
    "winner_count",
    "purchase_required",
    "location_venue",
    "location_address",
    "source_url",
    "source_note",
    "user_note",
    "is_offline",
}


class EventDuplicateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str | None = None
    organizer: str | None = None
    event_url: str | None = None
    event_start: date | None = None
    event_end: date | None = None
    source_type: str | None = None
    source_count: int = 0
    created_at: datetime | None = None


class DuplicateCandidateResponse(BaseModel):
    entity_type: EntityType = "event"
    entity1_id: int
    entity2_id: int
    similarity: float
    matched_fields: list[str]
    primary: EventDuplicateSummary
    secondary: EventDuplicateSummary


class MergeFieldComparison(BaseModel):
    field: str
    label: str
    primary_value: Any = None
    secondary_value: Any = None
    selected_source: FieldSource = "primary"


class MergePreviewResponse(BaseModel):
    entity_type: EntityType = "event"
    primary_id: int
    secondary_id: int
    similarity: float
    matched_fields: list[str]
    primary: EventDuplicateSummary
    secondary: EventDuplicateSummary
    fields: list[MergeFieldComparison]
    primary_source_count: int
    secondary_source_count: int


class MergeExecuteRequest(BaseModel):
    entity_type: EntityType = "event"
    primary_id: int = Field(..., gt=0)
    secondary_id: int = Field(..., gt=0)
    field_selections: dict[str, FieldSource] = Field(default_factory=dict)

    @field_validator("field_selections")
    @classmethod
    def validate_field_selections(cls, value: dict[str, FieldSource]) -> dict[str, FieldSource]:
        unknown = sorted(set(value) - MERGE_FIELD_WHITELIST)
        if unknown:
            raise ValueError(f"Unsupported merge fields: {', '.join(unknown)}")
        return value

    @model_validator(mode="after")
    def validate_distinct_ids(self) -> "MergeExecuteRequest":
        if self.primary_id == self.secondary_id:
            raise ValueError("primary_id and secondary_id must be different")
        return self


class MergeExecuteResponse(BaseModel):
    entity_type: EntityType = "event"
    merged_id: int
    disabled_id: int
    source_count: int
    moved_source_count: int
    merged_from: list[int]
    updated_fields: list[str]
    secondary_status: str
    primary: EventDuplicateSummary


class DismissDuplicateRequest(BaseModel):
    entity_type: EntityType = "event"
    entity1_id: int = Field(..., gt=0)
    entity2_id: int = Field(..., gt=0)
    dismissed_by: str | None = None

    @model_validator(mode="after")
    def validate_distinct_ids(self) -> "DismissDuplicateRequest":
        if self.entity1_id == self.entity2_id:
            raise ValueError("entity1_id and entity2_id must be different")
        return self


class DismissDuplicateResponse(BaseModel):
    entity_type: EntityType = "event"
    entity1_id: int
    entity2_id: int
    dismissed: bool
