from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Document(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: str = Field(min_length=1)
    label: str = Field(min_length=1)


class CreatorBrief(Document):
    creator: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    formats: tuple[str, ...] = Field(min_length=1)


class ProductSheet(Document):
    offerings: tuple[str, ...] = Field(min_length=1)
    supported_claims: dict[str, str] = Field(min_length=1)


class Rulebook(Document):
    voice: str = Field(min_length=1)
    formats: tuple[str, ...] = Field(min_length=1)
    prohibited_claims: tuple[str, ...] = Field(min_length=1)
    review_rules: dict[str, str] = Field(min_length=1)


class RunInputs(BaseModel):
    model_config = ConfigDict(frozen=True)
    creator_brief: CreatorBrief
    product_sheet: ProductSheet
    rulebook: Rulebook


class RunContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID = Field(default_factory=uuid4)
    inputs: RunInputs
    input_hashes: dict[str, str]
    user_brief: str | None = None


class ContentPlan(BaseModel):
    summary: str
    attempts: list[dict] = Field(default_factory=list)
    structured: dict | None = None
    prompt_version: int = 1
    parse_error: bool = False


class Draft(BaseModel):
    content: str
    attempts: list[dict] = Field(default_factory=list)
    structured: dict | None = None
    prompt_version: int = 1
    parse_error: bool = False


class Finding(BaseModel):
    message: str
    rule_id: str | None = None
    product_claim: str | None = None


class ReviewVerdict(BaseModel):
    decision: Literal["approve", "revise"]
    findings: list[Finding] = Field(default_factory=list)
    output: str = ""
    attempts: list[dict] = Field(default_factory=list)
    structured: dict | None = None
    prompt_version: int = 1
    parse_error: bool = False


class StageEvent(BaseModel):
    stage: str
    status: Literal["stub", "started", "completed", "failed"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_references: list[str] = Field(default_factory=list)
    model_call_metadata: list[dict] = Field(default_factory=list)


class RunResult(BaseModel):
    stages: list[dict] = Field(default_factory=list)
    events: list[StageEvent] = Field(default_factory=list)


class SafeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
