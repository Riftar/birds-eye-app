from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from birds_eye.core.contracts import RunInputs
from birds_eye.core.inputs import make_context
from birds_eye.meta.routes import resolve

router = APIRouter(prefix="/tencent")


@router.get("")
def entry():
    return {
        "status": "PLACEHOLDER",
        "owner": "WorkBuddy",
        "description": "WorkBuddy owns the Tencent pipeline integration.",
    }


@router.post("/runs")
def run(request: Request, inputs: RunInputs | None = None):
    make_context(resolve(request, inputs))
    return JSONResponse(
        status_code=501,
        content={
            "code": "WORKBUDDY_PIPELINE_NOT_CONNECTED",
            "message": "The WorkBuddy pipeline is not connected.",
        },
    )
