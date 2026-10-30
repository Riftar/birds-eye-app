from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from birds_eye.core.contracts import RunInputs
from birds_eye.core.inputs import load_inputs, make_context

router = APIRouter(prefix="/meta")


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
def run(request: Request, inputs: RunInputs | None = None):
    make_context(resolve(request, inputs))
    return JSONResponse(
        status_code=501,
        content={
            "code": "PIPELINE_NOT_IMPLEMENTED",
            "message": "The Meta pipeline is a stub.",
        },
    )
