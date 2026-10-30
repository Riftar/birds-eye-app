import json
import logging
import sys

FIELDS = (
    "event",
    "run_id",
    "stage",
    "call_id",
    "attempt",
    "logical_model",
    "provider",
    "model",
    "concrete_model",
    "status",
    "error_code",
    "latency_ms",
    "requested_max_tokens",
    "effective_max_tokens",
    "max_completion_tokens",
    "reasoning_effort",
    "usage",
    "cost_usd",
    "finish_reason",
    "truncated",
)
logger = logging.getLogger("birds_eye.model_calls")


def configure_logging():
    if not any(
        getattr(handler, "birds_eye_stdout", False) for handler in logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.birds_eye_stdout = True
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_attempt(record: dict) -> None:
    logger.info(json.dumps({key: record.get(key) for key in FIELDS}, default=str))
