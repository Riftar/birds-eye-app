from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    def home():
        return "<!doctype html><html><head><title>Birds Eye — Meta demo</title></head><body>\n<h1>Birds Eye — Meta single-brief demo</h1><p>Product sheet and rulebook: MOCK data. This demo does not publish content.</p>\n<form id=\"form\"><label for=\"brief\">Creator brief</label><br><textarea id=\"brief\" required maxlength=\"4000\" rows=\"8\" cols=\"70\"></textarea><br><button>Run pipeline</button></form><div id=\"result\"></div>\n<script>\nconst form = document.querySelector('#form'), result = document.querySelector('#result');\nform.addEventListener('submit', async e => { e.preventDefault(); result.textContent = 'Running…';\ntry { const response = await fetch('/meta/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({brief:document.querySelector('#brief').value})}); const data = await response.json(); result.replaceChildren();\nif (!response.ok) { const error = document.createElement('p'); error.textContent = data.code + ': ' + data.message; result.append(error); if (data.failed_stage) data.stages.push({stage: data.failed_stage, attempts: data.attempts, output: ''}); }\nfor (const stage of data.stages) { const section = document.createElement('section'), title = document.createElement('h2'), attempts = document.createElement('p'), output = document.createElement('pre'); title.textContent = stage.stage; attempts.textContent = stage.attempts.map(a => `${a.provider} ${a.concrete_model || ''} attempt ${a.attempt} ${a.status}${a.error_code ? ' (' + a.error_code + ')' : ''}, ${(a.latency_ms / 1000).toFixed(2)}s`).join(' → '); output.textContent = stage.output + (stage.truncated ? '\n(output truncated at token limit)' : ''); section.append(title, attempts, output); result.append(section); }\n} catch (_) { result.textContent = 'Unable to complete the run.'; } });\n</script></body></html>\n"

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    return app
