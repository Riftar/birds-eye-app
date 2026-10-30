from typing import Literal

from pydantic import BaseModel, Field


def strict_json_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()

    def transform(node: dict) -> None:
        node.pop("title", None)
        node.pop("default", None)
        if "oneOf" in node or "allOf" in node:
            raise ValueError("Meta structured output does not support oneOf or allOf")
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for key in ("properties", "$defs"):
            for child in node.get(key, {}).values():
                transform(child)
        if isinstance(node.get("items"), dict):
            transform(node["items"])
        for child in node.get("anyOf", []):
            transform(child)

    if any(key in schema for key in ("anyOf", "oneOf", "allOf", "enum", "not")):
        raise ValueError("Meta structured output requires an object root")
    transform(schema)
    return schema


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
