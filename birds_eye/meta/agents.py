import json
import re

from birds_eye.core.contracts import (
    ContentPlan,
    Draft,
    Finding,
    ReviewVerdict,
    RunContext,
)
from birds_eye.providers.contracts import ModelRequest
from birds_eye.providers.router import ModelRouter


async def call(ctx, router, stage, prompt):
    return await router.call(
        ModelRequest(
            run_id=str(ctx.run_id),
            stage=stage,
            call_id=stage,
            logical_model="muse-spark",
            operation="text",
            prompt=prompt,
        )
    )


async def plan(ctx: RunContext, router: ModelRouter) -> ContentPlan:
    inputs = ctx.inputs
    response = await call(
        ctx,
        router,
        "planner",
        f"Create a content plan for a short video or carousel in at most 150 words.\nBrief: {inputs.creator_brief.model_dump_json()}\nProduct sheet: {inputs.product_sheet.model_dump_json()}\nRulebook: {inputs.rulebook.model_dump_json()}",
    )
    return ContentPlan(summary=response.output, attempts=response.metadata)


async def write(
    ctx: RunContext,
    plan: ContentPlan,
    router: ModelRouter,
    feedback: ReviewVerdict | None = None,
) -> Draft:
    response = await call(
        ctx,
        router,
        "writer",
        f"Write the short-video script or carousel specified by this plan. Return only the draft, at most 180 words.\nPlan: {plan.summary}"
        + (f"\nFeedback: {feedback.output}" if feedback else ""),
    )
    return Draft(content=response.output, attempts=response.metadata)


async def review(
    ctx: RunContext, plan: ContentPlan, draft: Draft, router: ModelRouter
) -> ReviewVerdict:
    response = await call(
        ctx,
        router,
        "reviewer",
        f'Review this draft against the product sheet and rulebook. Output ONLY compact JSON {{"decision":"approve"|"revise","findings":[...]}}, with at most 4 findings of at most 20 words each. No markdown.\nDraft: {draft.content}\nProduct sheet: {ctx.inputs.product_sheet.model_dump_json()}\nRulebook: {ctx.inputs.rulebook.model_dump_json()}',
    )
    return parse_verdict(response.output, response.metadata)


def parse_verdict(text: str, attempts: list[dict]) -> ReviewVerdict:
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
        decision=decision, findings=findings, output=output, attempts=attempts
    )
