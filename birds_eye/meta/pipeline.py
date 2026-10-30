from birds_eye.core.contracts import RunContext, RunResult
from birds_eye.meta.agents import plan, review, write
from birds_eye.providers.contracts import RoutingError
from birds_eye.providers.router import ModelRouter


async def run_meta(ctx: RunContext, router: ModelRouter) -> RunResult:
    stages = []
    stage = "Planner"
    try:
        content_plan = await plan(ctx, router)
        stages.append(
            {
                "stage": stage,
                "output": content_plan.summary,
                "attempts": content_plan.attempts,
                "truncated": content_plan.attempts[-1]["truncated"],
                "structured": content_plan.structured,
                "prompt_version": content_plan.prompt_version,
                "parse_error": content_plan.parse_error,
            }
        )
        stage = "Writer"
        draft = await write(ctx, content_plan, router)
        stages.append(
            {
                "stage": stage,
                "output": draft.content,
                "attempts": draft.attempts,
                "truncated": draft.attempts[-1]["truncated"],
                "structured": draft.structured,
                "prompt_version": draft.prompt_version,
                "parse_error": draft.parse_error,
            }
        )
        stage = "Reviewer"
        verdict = await review(ctx, content_plan, draft, router)
        stages.append(
            {
                "stage": stage,
                "output": verdict.output,
                "attempts": verdict.attempts,
                "truncated": verdict.attempts[-1]["truncated"],
                "decision": verdict.decision,
                "findings": [f.model_dump() for f in verdict.findings],
                "structured": verdict.structured,
                "prompt_version": verdict.prompt_version,
                "parse_error": verdict.parse_error,
            }
        )
    except RoutingError as exc:
        exc.stages = stages
        exc.failed_stage = stage
        raise
    return RunResult(stages=stages)
