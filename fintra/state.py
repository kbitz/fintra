from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DashboardState:
    equities: List[Dict[str, Any]] = field(default_factory=list)
    crypto: List[Dict[str, Any]] = field(default_factory=list)
    indices: List[Dict[str, Any]] = field(default_factory=list)
    treasury: Dict[str, Optional[float]] = field(default_factory=dict)
    labor: Dict[str, Optional[float]] = field(default_factory=dict)
    inflation: Dict[str, Optional[float]] = field(default_factory=dict)

    market_updated: Optional[float] = None
    crypto_updated: Optional[float] = None
    crypto_data_date: Optional[str] = None  # date of the crypto agg bar (basic plan)
    economy_updated: Optional[float] = None

    market_stale: bool = False
    economy_stale: bool = False
    market_error: str = ""
    economy_error: str = ""

    prev_closes: Dict[str, float] = field(default_factory=dict)
    ytd_closes: Dict[str, float] = field(default_factory=dict)  # Dec 31 close for YTD calc
    ticker_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # static data from get_ticker_details

    extended_hours: bool = False    # pre-market or after-hours session active
    market_is_open: bool = False   # US equities (NYSE/NASDAQ)
    indices_group_status: Dict[str, str] = field(default_factory=dict)  # group → "open"/"closed"
    rate_limited: bool = False
    ws_connected: bool = False
    quit_flag: bool = False

    switch_watchlist: bool = False
    watchlist_error: str = ""
    active_watchlist_name: str = ""
