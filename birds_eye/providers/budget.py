import fcntl
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from birds_eye.config import Settings
from birds_eye.providers.contracts import ProviderError, ProviderId, Reservation
from birds_eye.providers.logging import logger

TEXT_PRICES = {
    "muse-spark-1.3-contributor": (Decimal("0.10"), Decimal("0.002"), Decimal("0.20")),
    "muse-spark-1.3": (Decimal("1.25"), Decimal("0.15"), Decimal("4.25")),
    "meta-models/muse-spark-open-1026": (Decimal("1.25"), None, Decimal("4.25")),
}
IMAGE_PRICES = {"sam-3.1": Decimal("0.0025"), "muse-image-1.0": Decimal("0.01")}


def cost_for_frames(frames: int) -> Decimal:
    if frames < 0:
        raise ValueError("Frame count must be nonnegative")
    return Decimal(max(frames, 50)) * Decimal("0.20") / Decimal(1000)


class LedgerBudgetGuard:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.ledger_path
        self.open = {}
        self.totals = {provider: Decimal(0) for provider in ProviderId}
        if self.path.exists():
            with self.path.open() as ledger:
                fcntl.flock(ledger, fcntl.LOCK_SH)
                try:
                    for line_no, line in enumerate(ledger, 1):
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                            provider = ProviderId(entry["provider"])
                            cost = Decimal(str(entry["cost_usd"]))
                            if not cost.is_finite() or cost < 0:
                                raise ValueError("Invalid cost")
                        except (ValueError, TypeError, KeyError, InvalidOperation):
                            logger.warning(
                                json.dumps(
                                    {"event": "ledger_corrupt_line", "line_no": line_no}
                                )
                            )
                            continue
                        self.totals[provider] += cost
                finally:
                    fcntl.flock(ledger, fcntl.LOCK_UN)

    def prices(self, provider, model=None):
        prefix = f"price_{provider.value}"
        defaults = TEXT_PRICES.get(model, (None, None, None))
        # Preserve provider overrides for existing deployments.
        input_override = getattr(self.settings, prefix + "_input_per_mtok_usd")
        output_override = getattr(self.settings, prefix + "_output_per_mtok_usd")
        input_price = input_override if input_override is not None else defaults[0]
        output_price = output_override if output_override is not None else defaults[2]
        cached_override = getattr(
            self.settings, prefix + "_cached_input_per_mtok_usd", None
        )
        cached_price = cached_override if cached_override is not None else defaults[1]
        if input_price is None or output_price is None:
            raise ProviderError("PRICE_NOT_CONFIGURED")
        return (
            input_price,
            cached_price if cached_price is not None else input_price,
            output_price,
        )

    def cap(self, provider):
        return getattr(self.settings, f"{provider.value}_budget_cap_usd")

    def summary(self):
        return {
            p.value: {
                "spent_usd": float(self.totals[p]),
                "cap_usd": float(self.cap(p)) if self.cap(p) is not None else None,
            }
            for p in ProviderId
        }

    async def reserve(self, provider, max_cost_usd):
        cap = self.cap(provider)
        pending = sum(
            (cost for p, cost in self.open.values() if p == provider), Decimal(0)
        )
        if cap is not None and self.totals[provider] + pending + max_cost_usd > cap:
            raise ProviderError("BUDGET_EXHAUSTED")
        reservation = Reservation(id=str(uuid4()))
        self.open[reservation.id] = (provider, max_cost_usd)
        return reservation

    async def settle(self, reservation, actual_cost_usd):
        provider, worst = self.open.pop(reservation.id)
        self.totals[provider] += worst if actual_cost_usd is None else actual_cost_usd

    async def settle_attempt(
        self, reservation, request, model, usage, status, error_code
    ):
        provider, worst = self.open[reservation.id]
        prompt = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
        valid = all(
            isinstance(n, int) and not isinstance(n, bool) and n >= 0
            for n in (prompt, completion)
        )
        if valid:
            input_price, cached_price, output_price = self.prices(provider, model)
            details = usage.get("prompt_tokens_details")
            cached = details.get("cached_tokens") if isinstance(details, dict) else 0
            if (
                not isinstance(cached, int)
                or isinstance(cached, bool)
                or not 0 <= cached <= prompt
            ):
                cached = 0
            cost = (
                (prompt - cached) * input_price
                + cached * cached_price
                + completion * output_price
            ) / Decimal(1_000_000)
        elif status == "success" or error_code == "TIMEOUT":
            cost = worst
        else:
            cost = Decimal(0)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": request.run_id,
            "stage": request.stage,
            "provider": provider.value,
            "model": model,
            "cost_usd": str(cost),
            "prompt_tokens": prompt if valid else None,
            "completion_tokens": completion if valid else None,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as ledger:
            fcntl.flock(ledger, fcntl.LOCK_EX)
            ledger.write(json.dumps(entry) + "\n")
            ledger.flush()
            fcntl.flock(ledger, fcntl.LOCK_UN)
        await self.settle(reservation, cost)
        return cost
