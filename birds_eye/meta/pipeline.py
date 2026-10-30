from birds_eye.core.contracts import RunContext, RunResult
from birds_eye.meta.agents import plan, review, write
from birds_eye.providers.router import ModelRouter


async def run_meta(ctx: RunContext, router: ModelRouter) -> RunResult:
    content_plan = await plan(ctx, router)
    draft = await write(ctx, content_plan, router)
    verdict = await review(ctx, content_plan, draft, router)
    return RunResult(
        stages=[
            {
                "stage": "Planner",
                "output": content_plan.summary,
                "attempts": content_plan.attempts,
            },
            {"stage": "Writer", "output": draft.content, "attempts": draft.attempts},
            {
                "stage": "Reviewer",
                "output": verdict.output,
                "attempts": verdict.attempts,
                "decision": verdict.decision,
                "findings": [f.model_dump() for f in verdict.findings],
            },
        ]
    )
