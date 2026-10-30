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


async def call(ctx, router, stage, instructions, inputs):
    return await router.call(
        ModelRequest(
            run_id=str(ctx.run_id),
            stage=stage,
            call_id=stage,
            logical_model="muse-spark",
            operation="text",
            prompt=inputs,
            instructions=instructions
            + " The creator brief defines the business, brand, product, audience and format. The product sheet and rulebook only add constraints where applicable; never replace the brief's brand or subject.",
            max_tokens=getattr(router.settings, f"{stage}_max_tokens"),
        )
    )


async def plan(ctx: RunContext, router: ModelRouter) -> ContentPlan:
    response = await call(
        ctx,
        router,
        "planner",
        "Create a concise plan in short labelled sections: hook, format, key points, CTA. At most 150 words.",
        context_text(ctx),
    )
    return ContentPlan(summary=response.output, attempts=response.metadata)


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
        "Write the final script or slides, at most 180 words. Return only the draft.",
        inputs,
    )
    return Draft(content=response.output, attempts=response.metadata)


async def review(
    ctx: RunContext, plan: ContentPlan, draft: Draft, router: ModelRouter
) -> ReviewVerdict:
    response = await call(
        ctx,
        router,
        "reviewer",
        'Check the draft against the creator brief first, then the rulebook and product sheet. Output only compact JSON {"decision":"approve"|"revise","findings":[...]}, at most 4 findings of at most 20 words each. No markdown.',
        context_text(ctx) + f"\n\nDraft: {draft.content}",
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
