import json
import logging

FIELDS = (
    "run_id",
    "stage",
    "call_id",
    "attempt",
    "logical_model",
    "provider",
    "concrete_model",
    "status",
    "error_code",
    "latency_ms",
    "requested_max_tokens",
    "effective_max_tokens",
    "usage",
    "cost_usd",
)
logger = logging.getLogger("birds_eye.model_calls")


def log_attempt(record: dict) -> None:
    logger.info(json.dumps({key: record.get(key) for key in FIELDS}, default=str))
