from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RequestProfileLiteral = Literal["A", "B", "C"]
FallbackStrategyLiteral = Literal["reinforce", "random_rotate"]


class PopupRequestOptions(BaseModel):
    """Popup monitor HTTP request options."""

    request_profile: RequestProfileLiteral = Field(default="A")
    fallback_strategy: FallbackStrategyLiteral = Field(default="reinforce")

