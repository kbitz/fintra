import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from massive import RESTClient

from fintra.constants import ALL_YIELD_FIELDS
from fintra.formatting import display_name
from fintra.plans import PlanInfo
from fintra.state import DashboardState


def normalize_snapshot(snap: Any, ticker: str) -> Dict[str, Any]:
    """Convert an API snapshot object to a flat dict for rendering."""
    d: Dict[str, Any] = {"ticker": ticker, "name": display_name(ticker)}

    session = getattr(snap, "session", None)
    if session:
        d["last"] = getattr(session, "close", None) or getattr(session, "price", None)
        d["open"] = getattr(session, "open", None)
        d["high"] = getattr(session, "high", None)
        d["low"] = getattr(session, "low", None)
        d["volume"] = getattr(session, "volume", None)
        d["change"] = getattr(session, "change", None)
        d["change_pct"] = getattr(session, "change_percent", None)
    else:
        d["last"] = getattr(snap, "value", None) or getattr(snap, "price", None)
        d["open"] = getattr(snap, "open", None)
        d["high"] = getattr(snap, "high", None)
        d["low"] = getattr(snap, "low", None)
        d["volume"] = getattr(snap, "volume", None)
        d["change"] = getattr(snap, "change", None)
        d["change_pct"] = getattr(snap, "change_percent", None)

    # Some responses nest under last_trade / last_quote
    if d["last"] is None:
        lt = getattr(snap, "last_trade", None)
        if lt:
            d["last"] = getattr(lt, "price", None) or getattr(lt, "p", None)

    if d["last"] is None:
        lq = getattr(snap, "last_quote", None)
        if lq:
            mid_a = getattr(lq, "ask", None) or getattr(lq, "P", None)
            mid_b = getattr(lq, "bid", None) or getattr(lq, "p", None)
            if mid_a and mid_b:
                d["last"] = (mid_a + mid_b) / 2

    # Fallback: try top-level price/value
    if d["last"] is None:
        d["last"] = getattr(snap, "price", None) or getattr(snap, "value", None)

    return d


def _normalize_crypto_agg(agg: Any, prev_agg: Any, ticker: str) -> Dict[str, Any]:
    """Convert crypto agg + previous close into a flat dict for rendering."""
    d: Dict[str, Any] = {"ticker": ticker, "name": display_name(ticker)}
    d["last"] = getattr(agg, "close", None)
    d["open"] = getattr(agg, "open", None)
    d["high"] = getattr(agg, "high", None)
    d["low"] = getattr(agg, "low", None)
    d["volume"] = getattr(agg, "volume", None)

    if prev_agg and d["last"] is not None:
        prev_close = getattr(prev_agg, "close", None)
        if prev_close:
            d["change"] = d["last"] - prev_close
            d["change_pct"] = (d["change"] / prev_close) * 100
        else:
            d["change"] = None
            d["change_pct"] = None
    else:
        d["change"] = None
        d["change_pct"] = None

    return d


def _fetch_via_aggs(client: RESTClient, tickers: List[str], state: DashboardState) -> List[Dict[str, Any]]:
    """Fallback: fetch stock/index data via get_aggs for Basic plan users."""
    today = datetime.now().strftime("%Y-%m-%d")
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    results = []
    for ticker in tickers:
        try:
            aggs = client.get_aggs(ticker, 1, "day", three_days_ago, today)
            if aggs and len(aggs) >= 2:
                results.append(_normalize_crypto_agg(aggs[-1], aggs[-2], ticker))
                if aggs[-2].close is not None:
                    state.prev_closes[ticker] = aggs[-2].close
            elif aggs:
                results.append(_normalize_crypto_agg(aggs[-1], None, ticker))
        except Exception:
            pass
        time.sleep(1)
    return results


def fetch_market_data(client: RESTClient, watchlist: Dict[str, List[str]],
                      state: DashboardState, plans: PlanInfo):
    """Fetch data for stocks/indices. Uses snapshots if available, else aggs fallback."""
    try:
        # Determine which tickers can use snapshots
        snap_tickers = []
        agg_eq_tickers = []
        agg_ix_tickers = []

        if plans.stocks_has_snapshots:
            snap_tickers.extend(watchlist["equities"])
        else:
            agg_eq_tickers = watchlist["equities"]

        if plans.indices_has_snapshots:
            snap_tickers.extend(watchlist["indices"])
        else:
            agg_ix_tickers = watchlist["indices"]

        # Fetch via snapshots where available
        if snap_tickers:
            snapshots = list(client.list_universal_snapshots(ticker_any_of=snap_tickers))
            snap_map: Dict[str, Any] = {}
            for s in snapshots:
                t = getattr(s, "ticker", None)
                if t and not getattr(s, "error", None):
                    snap_map[t] = s

            if plans.stocks_has_snapshots:
                new_eq = [normalize_snapshot(snap_map[t], t) for t in watchlist["equities"] if t in snap_map]
                if new_eq:
                    state.equities = new_eq
            if plans.indices_has_snapshots:
                new_ix = [normalize_snapshot(snap_map[t], t) for t in watchlist["indices"] if t in snap_map]
                if new_ix:
                    state.indices = new_ix

            # Cache previous closes for WS change calculations
            for t, s in snap_map.items():
                session = getattr(s, "session", None)
                if session:
                    prev = getattr(session, "previous_close", None)
                    if prev:
                        state.prev_closes[t] = prev
                    else:
                        close = getattr(session, "close", None)
                        change = getattr(session, "change", None)
                        if close is not None and change is not None:
                            state.prev_closes[t] = close - change

        # Fetch via aggs fallback for Basic plan tickers
        if agg_eq_tickers:
            new_eq = _fetch_via_aggs(client, agg_eq_tickers, state)
            if new_eq:
                state.equities = new_eq
        if agg_ix_tickers:
            new_ix = _fetch_via_aggs(client, agg_ix_tickers, state)
            if new_ix:
                state.indices = new_ix

        state.market_updated = time.time()
        state.market_stale = False
        state.market_error = ""
        state.rate_limited = False

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate" in err_str.lower():
            state.rate_limited = True
            state.market_error = "Rate limited"
        else:
            state.market_error = str(e)[:80]
        state.market_stale = True


# Crypto fetch state — lock prevents overlapping fetches from racing
_crypto_lock = threading.Lock()
_last_crypto_fetch: float = 0.0


def fetch_crypto_data(client: RESTClient, watchlist: Dict[str, List[str]],
                      state: DashboardState, plans: PlanInfo):
    """Fetch crypto data. Uses snapshots if Starter plan, daily aggs if Basic."""
    global _last_crypto_fetch
    crypto_tickers = watchlist["crypto"]
    if not crypto_tickers:
        return

    # Skip if another fetch is already running
    if not _crypto_lock.acquire(blocking=False):
        return

    try:
        crypto_data = []

        if plans.currencies_has_snapshots:
            # Starter plan: use snapshots (unlimited, no rate limit concerns)
            try:
                snaps = list(client.list_universal_snapshots(ticker_any_of=crypto_tickers))
                for s in snaps:
                    t = getattr(s, "ticker", None)
                    if t and not getattr(s, "error", None):
                        crypto_data.append(normalize_snapshot(s, t))
                        session = getattr(s, "session", None)
                        if session:
                            prev = getattr(session, "previous_close", None)
                            if prev:
                                state.prev_closes[t] = prev
            except Exception:
                pass
            _last_crypto_fetch = time.time()
        else:
            # Basic plan: use get_aggs with rate limiting
            min_interval = max(len(crypto_tickers) * 12, 15)
            now = time.time()
            if _last_crypto_fetch and (now - _last_crypto_fetch) < min_interval:
                return  # too soon, skip this cycle
            _last_crypto_fetch = now

            today = datetime.now().strftime("%Y-%m-%d")
            three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            for ticker in crypto_tickers:
                try:
                    aggs = client.get_aggs(ticker, 1, "day", three_days_ago, today)
                    if aggs and len(aggs) >= 2:
                        cur = aggs[-1]
                        prev = aggs[-2]
                        crypto_data.append(_normalize_crypto_agg(cur, prev, ticker))
                        if prev.close is not None:
                            state.prev_closes[ticker] = prev.close
                    elif aggs:
                        cur = aggs[-1]
                        crypto_data.append(_normalize_crypto_agg(cur, None, ticker))
                    # Store the data date from the most recent agg
                    if aggs:
                        ts = getattr(aggs[-1], "timestamp", None)
                        if ts:
                            state.crypto_data_date = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
                except Exception:
                    pass
                time.sleep(1)

        # Atomic swap — only overwrite if we got ALL tickers
        if len(crypto_data) == len(crypto_tickers):
            state.crypto = crypto_data
            state.crypto_updated = time.time()
            state.market_updated = state.market_updated or time.time()
        elif crypto_data:
            # Partial success — merge into existing data rather than replacing
            existing = {d["ticker"]: d for d in state.crypto}
            for d in crypto_data:
                existing[d["ticker"]] = d
            state.crypto = [existing[t] for t in crypto_tickers if t in existing]
            state.crypto_updated = time.time()
            state.market_updated = state.market_updated or time.time()
    finally:
        _crypto_lock.release()


def fetch_ytd_closes(client: RESTClient, watchlist: Dict[str, List[str]], state: DashboardState):
    """Fetch Dec 31 closing prices for YTD % calculation."""
    year = datetime.now().year
    # Try Dec 31 of previous year, then work backwards to find a trading day
    end_date = f"{year - 1}-12-31"
    start_date = f"{year - 1}-12-26"  # go back a few days in case Dec 31 was a weekend

    for ticker in watchlist["equities"] + watchlist["indices"]:
        if ticker in state.ytd_closes:
            continue
        try:
            aggs = client.get_aggs(ticker, 1, "day", start_date, end_date)
            if aggs:
                state.ytd_closes[ticker] = aggs[-1].close
        except Exception:
            pass
        time.sleep(0.5)  # gentle rate limiting


def _fetch_with_timeout(fn, timeout=10):
    """Run a data fetch in a thread with a timeout to avoid hanging on 429 retries."""
    result = [None]
    error = [None]

    def _run():
        try:
            result[0] = fn()
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError("Request timed out")
    if error[0]:
        raise error[0]
    return result[0]


def _fetch_economy_endpoint(fn, timeout=20, retries=2):
    """Try fetching an economy endpoint with retries on timeout/429."""
    for attempt in range(retries + 1):
        try:
            return _fetch_with_timeout(fn, timeout=timeout)
        except (TimeoutError, Exception) as e:
            err_str = str(e)
            if attempt < retries and ("429" in err_str or "timed out" in err_str.lower()):
                time.sleep(15)  # wait and retry
                continue
            raise


def fetch_economy_data(client: RESTClient, state: DashboardState):
    """Fetch treasury yields, labor market, and inflation data.

    Spaces calls 15s apart to stay within 5 calls/min rate limits.
    """
    had_error = False

    # Treasury yields — use next(iter()) to avoid pagination burning rate limit
    try:
        y = _fetch_economy_endpoint(
            lambda: next(iter(client.list_treasury_yields(sort="date.desc", limit=1))),
        )
        if y:
            state.treasury = {
                attr: getattr(y, attr, None) for attr in ALL_YIELD_FIELDS.values()
            }
            state.treasury["date"] = getattr(y, "date", None)
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "timed out" not in err_str.lower():
            state.economy_error = f"Treasury: {err_str[:60]}"
        had_error = True

    time.sleep(15)  # space calls to avoid 429

    # Labor market
    try:
        lm = _fetch_economy_endpoint(
            lambda: next(iter(client.list_labor_market_indicators(sort="date.desc", limit=1))),
        )
        if lm:
            state.labor = {
                "unemployment_rate": getattr(lm, "unemployment_rate", None),
                "participation_rate": getattr(lm, "labor_force_participation_rate", None),
                "avg_hourly_earnings": getattr(lm, "avg_hourly_earnings", None),
                "date": getattr(lm, "date", None),
            }
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "timed out" not in err_str.lower():
            state.economy_error = f"Labor: {err_str[:60]}"
        had_error = True

    time.sleep(15)  # space calls to avoid 429

    # Inflation
    try:
        i = _fetch_economy_endpoint(
            lambda: next(iter(client.list_inflation(sort="date.desc", limit=1))),
        )
        if i:
            state.inflation = {
                "cpi": getattr(i, "cpi", None),
                "cpi_core": getattr(i, "cpi_core", None),
                "date": getattr(i, "date", None),
            }
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "timed out" not in err_str.lower():
            state.economy_error = f"Inflation: {err_str[:60]}"
        had_error = True

    if had_error:
        state.economy_stale = True
    else:
        state.economy_stale = False
        state.economy_updated = time.time()
        state.economy_error = ""
