from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from birds_eye.config import Settings
from birds_eye.meta.routes import router as meta_router
from birds_eye.tencent.routes import router as tencent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from birds_eye.providers.logging import configure_logging

    configure_logging()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings or Settings()
    from birds_eye.providers.budget import LedgerBudgetGuard
    from birds_eye.providers.router import NoCostBudget

    if app.state.settings.provider_mode == "live":
        app.state.budget = LedgerBudgetGuard(app.state.settings)
        app.state.ledger = app.state.budget.summary()
    else:
        app.state.budget = NoCostBudget()
        app.state.ledger = {}
    design_dir = Path(__file__).resolve().parent.parent / "design"
    app.mount("/design", StaticFiles(directory=design_dir), name="design")
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

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    return app
