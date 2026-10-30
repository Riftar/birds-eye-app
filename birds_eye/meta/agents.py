import json
import re

from pydantic import BaseModel, ValidationError

from birds_eye.core.contracts import (
    ContentPlan,
    Draft,
    Finding,
    ReviewVerdict,
    RunContext,
)
from birds_eye.meta.prompts import load_prompts
from birds_eye.meta.schemas import ContentPlanOut, DraftOut, VerdictOut
from birds_eye.providers.contracts import ModelRequest
from birds_eye.providers.router import ModelRouter

# Versioned stage prompts, loaded once at startup.
PROMPTS = load_prompts()

SCHEMAS: dict[str, tuple[str, type[BaseModel]]] = {
    "planner": ("content_plan", ContentPlanOut),
    "writer": ("draft", DraftOut),
    "reviewer": ("verdict", VerdictOut),
}


def context_text(ctx):
    brief = (
        ctx.user_brief
        if ctx.user_brief is not None
        else ctx.inputs.creator_brief.model_dump_json()
    )
    return (
        f"Creator brief (primary input):\n{brief}\n\n"
        f"Product sheet (secondary constraints where applicable):\n{ctx.inputs.product_sheet.model_dump_json()}\n\n"
        f"Rulebook (secondary house rules where applicable):\n{ctx.inputs.rulebook.model_dump_json()}"
    )


def parse_structured(model: type[BaseModel], text: str) -> tuple[dict | None, bool]:
    """Parse model output into a typed schema.

    Returns (structured_dict, parse_error). On failure the raw text is kept
    by the caller with structured=None and parse_error=True; never raises.
    """
    try:
        return model.model_validate_json(text).model_dump(mode="json"), False
    except ValidationError:
        pass
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return model.model_validate_json(cleaned).model_dump(mode="json"), False
    except ValidationError:
        return None, True


async def call(ctx, router, stage, inputs, extra=""):
    prompt = PROMPTS[stage]
    schema_name, schema_model = SCHEMAS[stage]
    return await router.call(
        ModelRequest(
            run_id=str(ctx.run_id),
            stage=stage,
            call_id=stage,
            logical_model="muse-spark",
            operation="text",
            prompt=inputs,
            instructions=prompt["text"] + extra,
            max_tokens=getattr(router.settings, f"{stage}_max_tokens"),
            json_schema_name=schema_name,
            json_schema=schema_model.model_json_schema(),
        )
    )


async def plan(ctx: RunContext, router: ModelRouter) -> ContentPlan:
    response = await call(
        ctx,
        router,
        "planner",
        context_text(ctx),
    )
    structured, parse_error = parse_structured(ContentPlanOut, response.output)
    return ContentPlan(
        summary=response.output,
        attempts=response.metadata,
        structured=structured,
        prompt_version=PROMPTS["planner"]["version"],
        parse_error=parse_error,
    )


async def write(
    ctx: RunContext,
    plan: ContentPlan,
    router: ModelRouter,
    feedback: ReviewVerdict | None = None,
) -> Draft:
    inputs = (
        context_text(ctx)
        + f"\n\nPlan: {plan.summary}"
        + (f"\nFeedback: {feedback.output}" if feedback else "")
    )
    response = await call(
        ctx,
        router,
        "writer",
        inputs,
    )
    structured, parse_error = parse_structured(DraftOut, response.output)
    return Draft(
        content=response.output,
        attempts=response.metadata,
        structured=structured,
        prompt_version=PROMPTS["writer"]["version"],
        parse_error=parse_error,
    )


async def review(
    ctx: RunContext, plan: ContentPlan, draft: Draft, router: ModelRouter
) -> ReviewVerdict:
    response = await call(
        ctx,
        router,
        "reviewer",
        context_text(ctx) + f"\n\nDraft: {draft.content}",
    )
    structured, parse_error = parse_structured(VerdictOut, response.output)
    return parse_verdict(
        response.output,
        response.metadata,
        structured=structured,
        parse_error=parse_error,
        prompt_version=PROMPTS["reviewer"]["version"],
    )


def parse_verdict(
    text: str,
    attempts: list[dict],
    structured: dict | None = None,
    parse_error: bool = False,
    prompt_version: int = 1,
) -> ReviewVerdict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
        decision = str(data["decision"]).lower()
        if decision not in ("approve", "revise") or not isinstance(
            data.get("findings", []), list
        ):
            raise ValueError
        findings = [
            Finding.model_validate(item)
            if isinstance(item, dict)
            else Finding(message=str(item))
            for item in data.get("findings", [])
        ]
    except (ValueError, TypeError, KeyError):
        match = re.search(
            r'"decision"\s*:\s*"(approve|revise)"', cleaned, re.IGNORECASE
        )
        if not match:
            return ReviewVerdict(
                decision="revise",
                findings=[Finding(message=text)],
                output=text,
                attempts=attempts,
                structured=structured,
                prompt_version=prompt_version,
                parse_error=parse_error,
            )
        decision = match.group(1).lower()
        findings = []
        array = re.search(r'"findings"\s*:\s*\[', cleaned, re.IGNORECASE)
        if array:
            remainder = cleaned[array.end() :].lstrip()
            decoder = json.JSONDecoder()
            while remainder.startswith('"'):
                try:
                    item, end = decoder.raw_decode(remainder)
                except ValueError:
                    break
                findings.append(Finding(message=item))
                remainder = remainder[end:].lstrip()
                if not remainder.startswith(","):
                    break
                remainder = remainder[1:].lstrip()
    output = json.dumps(
        {"decision": decision, "findings": [finding.message for finding in findings]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ReviewVerdict(
        decision=decision,
        findings=findings,
        output=output,
        attempts=attempts,
        structured=structured,
        prompt_version=prompt_version,
        parse_error=parse_error,
    )
