from birds_eye.core.contracts import (
    ContentPlan,
    Draft,
    ReviewVerdict,
    RunContext,
    SafeError,
)
from birds_eye.providers.router import ModelRouter


class StageNotImplemented(SafeError):
    def __init__(self):
        super().__init__("STAGE_NOT_IMPLEMENTED", "This stage is a stub.")


async def plan(ctx: RunContext, router: ModelRouter) -> ContentPlan:
    raise StageNotImplemented()


async def write(
    ctx: RunContext,
    plan: ContentPlan,
    router: ModelRouter,
    feedback: ReviewVerdict | None = None,
) -> Draft:
    raise StageNotImplemented()


async def review(
    ctx: RunContext, plan: ContentPlan, draft: Draft, router: ModelRouter
) -> ReviewVerdict:
    raise StageNotImplemented()
