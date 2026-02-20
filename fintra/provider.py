"""Massive API provider — the only module that imports from massive."""

import threading
from typing import Any, Callable, Dict, List, Optional

from massive import RESTClient
from massive import WebSocketClient
from massive.websocket import Feed, Market
from massive.websocket.models import CurrencyAgg, EquityAgg, IndexValue

from fintra.constants import ALL_YIELD_FIELDS


class WsFeed:
    """Thin wrapper around WebSocketClient for lifecycle management."""

    def __init__(self, ws_client: WebSocketClient, on_update: Callable, market: str):
        self._ws = ws_client
        self._on_update = on_update
        self._market = market

    def run(self):
        """Blocking — runs the WS event loop, dispatching parsed updates."""
        self._ws.run(lambda msgs: self._handle(msgs))

    def close(self):
        self._ws.close()

    def _handle(self, msgs):
        for msg in msgs:
            if isinstance(msg, EquityAgg) and msg.symbol and msg.close is not None:
                self._on_update(msg.symbol, msg.close,
                                {"high": msg.high, "low": msg.low,
                                 "volume": msg.accumulated_volume})
            elif isinstance(msg, IndexValue) and msg.ticker and msg.value is not None:
                self._on_update(msg.ticker, msg.value, {})
            elif isinstance(msg, CurrencyAgg) and msg.pair and msg.close is not None:
                self._on_update(msg.pair, msg.close,
                                {"high": msg.high, "low": msg.low,
                                 "volume": msg.volume})


_MARKET_MAP = {"stocks": Market.Stocks, "indices": Market.Indices, "crypto": Market.Crypto}
_FEED_MAP = {"realtime": Feed.RealTime, "delayed": Feed.Delayed}
_SUB_PREFIX = {"stocks": "A", "indices": "V", "crypto": "XA"}


class MassiveProvider:
    """Wraps the Massive SDK so no other module needs to import from massive."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = RESTClient(api_key=api_key)

    # -- Snapshots / Aggs ------------------------------------------------

    def fetch_snapshots(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Fetch universal snapshots, return normalised dicts."""
        raw = list(self._client.list_universal_snapshots(ticker_any_of=tickers))
        results = []
        for snap in raw:
            t = getattr(snap, "ticker", None)
            if not t or getattr(snap, "error", None):
                continue
            results.append(self._normalize_snapshot(snap, t))
        return results

    def fetch_aggs(self, ticker: str, multiplier: int, timespan: str,
                   from_date: str, to_date: str) -> List[Dict[str, Any]]:
        """Fetch aggregate bars for a single ticker."""
        raw = self._client.get_aggs(ticker, multiplier, timespan, from_date, to_date)
        if not raw:
            return []
        return [
            {
                "open": getattr(a, "open", None),
                "high": getattr(a, "high", None),
                "low": getattr(a, "low", None),
                "close": getattr(a, "close", None),
                "volume": getattr(a, "volume", None),
                "timestamp": getattr(a, "timestamp", None),
            }
            for a in raw
        ]

    # -- Market status ---------------------------------------------------

    def fetch_market_status(self) -> Dict[str, Any]:
        """Return market open/closed status and per-group indices status."""
        ms = self._client.get_market_status()
        is_open = getattr(ms, "market", "") == "open"

        groups: Dict[str, str] = {}
        ig = getattr(ms, "indices_groups", None) or getattr(ms, "indicesGroups", None)
        if ig:
            if isinstance(ig, dict):
                groups = ig
            else:
                for g in ("s_and_p", "dow_jones", "nasdaq", "ftse_russell",
                          "societe_generale", "msci", "cccy"):
                    val = getattr(ig, g, None)
                    if val:
                        groups[g] = val

        return {"market_is_open": is_open, "indices_groups": groups}

    # -- Economy ---------------------------------------------------------

    def fetch_treasury_yields(self) -> Dict[str, Any]:
        """Single call for the latest treasury yields row."""
        y = next(iter(self._client.list_treasury_yields(sort="date.desc", limit=1)))
        result: Dict[str, Any] = {}
        for attr in ALL_YIELD_FIELDS.values():
            result[attr] = getattr(y, attr, None)
        result["date"] = getattr(y, "date", None)
        return result

    def fetch_labor_market(self) -> Dict[str, Any]:
        """Single call for the latest labor-market indicators row."""
        lm = next(iter(self._client.list_labor_market_indicators(sort="date.desc", limit=1)))
        return {
            "unemployment_rate": getattr(lm, "unemployment_rate", None),
            "participation_rate": getattr(lm, "labor_force_participation_rate", None),
            "avg_hourly_earnings": getattr(lm, "avg_hourly_earnings", None),
            "date": getattr(lm, "date", None),
        }

    def fetch_inflation(self, limit: int = 13) -> List[Dict[str, Any]]:
        """Fetch recent inflation records (default 13 for YoY calc)."""
        records = [
            r for _, r in zip(range(limit),
                              self._client.list_inflation(sort="date.desc", limit=limit))
        ]
        return [
            {
                "cpi": getattr(r, "cpi", None),
                "cpi_core": getattr(r, "cpi_core", None),
                "date": getattr(r, "date", None),
            }
            for r in records
        ]

    # -- Ticker details --------------------------------------------------

    def fetch_ticker_details(self, ticker: str) -> Dict[str, Any]:
        """Return static details (market cap) for a single ticker."""
        d = self._client.get_ticker_details(ticker)
        return {"market_cap": getattr(d, "market_cap", None)}

    # -- Plan probing ----------------------------------------------------

    def probe_snapshots(self, ticker: str) -> bool:
        """Test whether the API key has snapshot access for a ticker."""
        try:
            snaps = list(self._client.list_universal_snapshots(ticker_any_of=[ticker]))
            return any(not getattr(s, "error", None) for s in snaps)
        except Exception:
            return False

    # -- WebSocket feeds -------------------------------------------------

    def create_ws_feed(self, market: str, feed_type: str,
                       tickers: List[str],
                       on_update: Callable[[str, float, Dict], None]) -> WsFeed:
        """Create a WsFeed wrapping the SDK WebSocketClient.

        market:    "stocks" / "indices" / "crypto"
        feed_type: "realtime" / "delayed"
        on_update: callback(ticker, price, extras_dict)
        """
        prefix = _SUB_PREFIX[market]
        subs = [f"{prefix}.{t}" for t in tickers]
        ws = WebSocketClient(
            api_key=self._api_key,
            feed=_FEED_MAP[feed_type],
            market=_MARKET_MAP[market],
            subscriptions=subs,
        )
        return WsFeed(ws, on_update, market)

    # -- Internal helpers ------------------------------------------------

    @staticmethod
    def _normalize_snapshot(snap: Any, ticker: str) -> Dict[str, Any]:
        """Convert an API snapshot object to a flat dict."""
        d: Dict[str, Any] = {"ticker": ticker}

        session = getattr(snap, "session", None)
        if session:
            d["last"] = getattr(session, "close", None) or getattr(session, "price", None)
            d["open"] = getattr(session, "open", None)
            d["high"] = getattr(session, "high", None)
            d["low"] = getattr(session, "low", None)
            d["volume"] = getattr(session, "volume", None)
            d["change"] = getattr(session, "change", None)
            d["change_pct"] = getattr(session, "change_percent", None)
            d["prev_close"] = getattr(session, "previous_close", None)
            # Derive prev_close from close - change if not directly available
            if d["prev_close"] is None and d["last"] is not None and d["change"] is not None:
                d["prev_close"] = d["last"] - d["change"]
        else:
            d["last"] = getattr(snap, "value", None) or getattr(snap, "price", None)
            d["open"] = getattr(snap, "open", None)
            d["high"] = getattr(snap, "high", None)
            d["low"] = getattr(snap, "low", None)
            d["volume"] = getattr(snap, "volume", None)
            d["change"] = getattr(snap, "change", None)
            d["change_pct"] = getattr(snap, "change_percent", None)
            d["prev_close"] = None

        # Fallback: last_trade
        if d["last"] is None:
            lt = getattr(snap, "last_trade", None)
            if lt:
                d["last"] = getattr(lt, "price", None) or getattr(lt, "p", None)

        # Fallback: last_quote midpoint
        if d["last"] is None:
            lq = getattr(snap, "last_quote", None)
            if lq:
                mid_a = getattr(lq, "ask", None) or getattr(lq, "P", None)
                mid_b = getattr(lq, "bid", None) or getattr(lq, "p", None)
                if mid_a and mid_b:
                    d["last"] = (mid_a + mid_b) / 2

        # Fallback: top-level price/value
        if d["last"] is None:
            d["last"] = getattr(snap, "price", None) or getattr(snap, "value", None)

        return d
