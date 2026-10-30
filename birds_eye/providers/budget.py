import fcntl
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from birds_eye.config import Settings
from birds_eye.providers.contracts import ProviderError, ProviderId, Reservation
from birds_eye.providers.logging import logger


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

    def prices(self, provider):
        prefix = f"price_{provider.value}"
        prices = (
            getattr(self.settings, prefix + "_input_per_mtok_usd"),
            getattr(self.settings, prefix + "_output_per_mtok_usd"),
        )
        if None in prices:
            raise ProviderError("PRICE_NOT_CONFIGURED")
        return prices

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
        self.prices(provider)
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
            input_price, output_price = self.prices(provider)
            cost = (prompt * input_price + completion * output_price) / Decimal(
                1_000_000
            )
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
