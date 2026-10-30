from typing import Literal

from pydantic import BaseModel, Field


class ContentPlanOut(BaseModel):
    hook: str = Field(min_length=1)
    format: Literal["short_video", "carousel"]
    key_points: list[str] = Field(min_length=1, max_length=5)
    cta: str = Field(min_length=1)
    segment_subject: str | None = None


class Beat(BaseModel):
    label: str = Field(min_length=1)
    text: str = Field(min_length=1)


class DraftOut(BaseModel):
    format: Literal["short_video", "carousel"]
    beats: list[Beat] = Field(min_length=1, max_length=8)
    caption: str = Field(min_length=1)


class FindingOut(BaseModel):
    rule_id: str | None = None
    message: str = Field(min_length=1)


class VerdictOut(BaseModel):
    decision: Literal["approve", "revise"]
    findings: list[FindingOut] = Field(default_factory=list, max_length=4)
