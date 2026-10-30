from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from birds_eye.config import Settings
from birds_eye.meta.routes import router as meta_router
from birds_eye.tencent.routes import router as tencent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings or Settings()
    app.include_router(meta_router)
    app.include_router(tencent_router)

    @app.exception_handler(OSError)
    @app.exception_handler(ValidationError)
    @app.exception_handler(ValueError)
    async def invalid_inputs(request: Request, exc: Exception):
        return JSONResponse(
            status_code=422,
            content={
                "code": "INVALID_INPUTS",
                "message": "Scenario inputs could not be loaded or validated.",
            },
        )

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    return app
