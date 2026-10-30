from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from birds_eye.core.contracts import RunInputs
from birds_eye.core.inputs import load_inputs, make_context
from birds_eye.meta.pipeline import run_meta
from birds_eye.providers.contracts import RoutingError
from birds_eye.providers.router import ModelRouter, NoCostBudget
from birds_eye.providers.transport import LiveTransport

router = APIRouter(prefix="/meta")


class BriefRequest(BaseModel):
    brief: str = Field(min_length=1, max_length=4000)


def resolve(request: Request, inputs: RunInputs | None) -> RunInputs:
    return (
        inputs
        if inputs is not None
        else load_inputs(request.app.state.settings.default_scenario_dir)
    )


@router.get("")
def entry(request: Request):
    inputs = resolve(request, None)
    return {
        "status": "PLACEHOLDER",
        "sample_input_labels": [
            inputs.creator_brief.label,
            inputs.product_sheet.label,
            inputs.rulebook.label,
        ],
    }


@router.post("/runs")
async def run(request: Request, inputs: BriefRequest | RunInputs | None = None):
    settings = request.app.state.settings
    scenario = resolve(request, inputs if isinstance(inputs, RunInputs) else None)
    if isinstance(inputs, BriefRequest):
        scenario = scenario.model_copy(
            update={
                "creator_brief": scenario.creator_brief.model_copy(
                    update={"goal": inputs.brief, "label": "User creator brief"}
                )
            }
        )
    context = make_context(scenario)
    if settings.provider_mode == "stub":
        return JSONResponse(
            status_code=501,
            content={
                "code": "PIPELINE_NOT_IMPLEMENTED",
                "message": "The Meta pipeline is a stub.",
            },
        )
    if not isinstance(inputs, BriefRequest):
        return JSONResponse(
            status_code=422,
            content={
                "code": "INVALID_INPUTS",
                "message": "A creator brief is required.",
            },
        )
    transport = getattr(request.app.state, "transport", None) or LiveTransport(settings)
    try:
        return (
            await run_meta(context, ModelRouter(settings, transport, NoCostBudget()))
        ).model_dump(mode="json")
    except RoutingError as exc:
        return JSONResponse(
            status_code=429 if exc.code == "RUN_BUDGET_EXCEEDED" else 502,
            content={
                "code": exc.code,
                "message": exc.message,
                "attempts": exc.attempts,
            },
        )
