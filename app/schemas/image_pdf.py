"""Pydantic schemas for image -> PDF APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class ImagePdfHealthResponse(BaseModel):
    supported_extensions: list[str]
    heic_supported: bool
    pillow_version: str
    max_files: int = Field(..., ge=1)
    max_per_file_mb: int = Field(..., ge=1)
    max_total_mb: int = Field(..., ge=1)


class ImagePdfConvertOptions(BaseModel):
    bw: bool = False
    white: int = Field(default=200, ge=0, le=255)
    black: int = Field(default=80, ge=0, le=255)
    quality: int = Field(default=85, ge=1, le=100)
    preserve_dpi: bool = False
    output_name: str | None = None

    @model_validator(mode="after")
    def validate_thresholds(self):
        if self.white <= self.black:
            raise ValueError("white must be greater than black")
        return self

    @field_validator("output_name")
    @classmethod
    def validate_output_name(cls, value: str | None):
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if ".." in normalized or "/" in normalized or "\\" in normalized:
            raise ValueError("output_name must not contain path separators")
        return normalized
