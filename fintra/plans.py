import json
import os
from dataclasses import dataclass

from fintra.constants import PLANS_PATH


@dataclass
class PlanInfo:
    """Detected API plan capabilities per asset class."""
    # Stocks: "basic", "starter", "developer", "advanced"
    stocks: str = "basic"
    # Indices: "basic", "starter", "advanced"
    indices: str = "basic"
    # Currencies: "basic", "starter"
    currencies: str = "basic"

    @property
    def stocks_has_snapshots(self) -> bool:
        return self.stocks in ("starter", "developer", "advanced")

    @property
    def stocks_has_ws(self) -> bool:
        return self.stocks in ("starter", "developer", "advanced")

    @property
    def stocks_realtime(self) -> bool:
        return self.stocks == "advanced"

    @property
    def indices_has_snapshots(self) -> bool:
        return self.indices in ("starter", "advanced")

    @property
    def indices_has_ws(self) -> bool:
        return self.indices in ("starter", "advanced")

    @property
    def indices_realtime(self) -> bool:
        return self.indices == "advanced"

    @property
    def currencies_has_snapshots(self) -> bool:
        return self.currencies == "starter"

    @property
    def currencies_has_ws(self) -> bool:
        return self.currencies == "starter"

    @property
    def currencies_unlimited(self) -> bool:
        return self.currencies == "starter"


def _probe_plans(provider) -> PlanInfo:
    """Probe API endpoints to detect plan tier for each asset class."""
    plans = PlanInfo()

    if provider.probe_snapshots("AAPL"):
        plans.stocks = "starter"

    if provider.probe_snapshots("I:SPX"):
        plans.indices = "starter"

    if provider.probe_snapshots("X:BTCUSD"):
        plans.currencies = "starter"

    return plans


def load_plans(provider) -> PlanInfo:
    """Load cached plan info or probe if not cached."""
    if os.path.exists(PLANS_PATH):
        try:
            with open(PLANS_PATH, "r") as f:
                data = json.load(f)
            plans = PlanInfo(
                stocks=data.get("stocks", "basic"),
                indices=data.get("indices", "basic"),
                currencies=data.get("currencies", "basic"),
            )
            return plans
        except Exception:
            pass

    # No cache — probe and save
    print("[fintra] Detecting API plan entitlements...")
    plans = _probe_plans(provider)
    save_plans(plans)
    print(f"[fintra] Detected: stocks={plans.stocks}, indices={plans.indices}, currencies={plans.currencies}")
    return plans


def save_plans(plans: PlanInfo):
    """Save plan info to cache file."""
    data = {
        "stocks": plans.stocks,
        "indices": plans.indices,
        "currencies": plans.currencies,
    }
    try:
        with open(PLANS_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
