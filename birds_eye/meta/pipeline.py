from birds_eye.core.contracts import RunContext, RunResult, SafeError
from birds_eye.providers.router import ModelRouter


class PipelineNotImplemented(SafeError):
    def __init__(self):
        super().__init__("PIPELINE_NOT_IMPLEMENTED", "The Meta pipeline is a stub.")


async def run_meta(ctx: RunContext, router: ModelRouter) -> RunResult:
    raise PipelineNotImplemented()
