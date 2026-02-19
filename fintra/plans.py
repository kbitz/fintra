import json
import os
from dataclasses import dataclass

from massive import RESTClient

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


def _probe_plans(client: RESTClient, api_key: str) -> PlanInfo:
    """Probe API endpoints to detect plan tier for each asset class."""
    plans = PlanInfo()

    # Probe stocks: try snapshot
    try:
        snaps = list(client.list_universal_snapshots(ticker_any_of=["AAPL"]))
        has_snap = any(not getattr(s, "error", None) for s in snaps)
        if has_snap:
            plans.stocks = "starter"  # at minimum
    except Exception:
        pass

    # Probe indices: try snapshot
    try:
        snaps = list(client.list_universal_snapshots(ticker_any_of=["I:SPX"]))
        has_snap = any(not getattr(s, "error", None) for s in snaps)
        if has_snap:
            plans.indices = "starter"
    except Exception:
        pass

    # Probe currencies: try snapshot
    try:
        snaps = list(client.list_universal_snapshots(ticker_any_of=["X:BTCUSD"]))
        has_snap = any(not getattr(s, "error", None) for s in snaps)
        if has_snap:
            plans.currencies = "starter"
    except Exception:
        pass

    return plans


def load_plans(client: RESTClient, api_key: str) -> PlanInfo:
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
    plans = _probe_plans(client, api_key)
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
