import json
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from fintra.constants import ALL_YIELD_FIELDS, ECON_CACHE_PATH
from fintra.formatting import display_name
from fintra.plans import PlanInfo
from fintra.state import DashboardState


def _last_market_close() -> float:
    """Return the Unix timestamp of the most recent NYSE close (4 PM ET)."""
    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)
    close = dt_time(16, 0)

    if now_et.weekday() < 5 and now_et >= datetime.combine(now_et.date(), close, tzinfo=et):
        return datetime.combine(now_et.date(), close, tzinfo=et).timestamp()

    # Walk back to the previous weekday
    candidate = now_et.date()
    if now_et.weekday() < 5:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return datetime.combine(candidate, close, tzinfo=et).timestamp()


def _load_econ_cache(state: DashboardState) -> bool:
    """Load economy data from cache if it was fetched after the last market close."""
    try:
        with open(ECON_CACHE_PATH, "r") as f:
            cache = json.load(f)
        if cache.get("fetched_at", 0) > _last_market_close():
            state.treasury = cache.get("treasury", {})
            state.labor = cache.get("labor", {})
            state.inflation = cache.get("inflation", {})
            state.economy_updated = cache["fetched_at"]
            state.economy_error = ""
            return True
    except Exception:
        pass
    return False


def _save_econ_cache(state: DashboardState):
    """Persist economy data to disk for fast startup."""
    try:
        cache = {
            "fetched_at": time.time(),
            "treasury": state.treasury,
            "labor": state.labor,
            "inflation": state.inflation,
        }
        with open(ECON_CACHE_PATH, "w") as f:
            json.dump(cache, f, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
    except Exception:
        pass


def _normalize_crypto_agg(agg: Dict[str, Any], prev_agg: Dict[str, Any],
                          ticker: str) -> Dict[str, Any]:
    """Convert crypto agg dict + previous close dict into a flat dict for rendering."""
    d: Dict[str, Any] = {"ticker": ticker, "name": display_name(ticker)}
    d["last"] = agg.get("close")
    d["open"] = agg.get("open")
    d["high"] = agg.get("high")
    d["low"] = agg.get("low")
    d["volume"] = agg.get("volume")

    if prev_agg and d["last"] is not None:
        prev_close = prev_agg.get("close")
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


def _fetch_via_aggs(provider, tickers: List[str], state: DashboardState) -> List[Dict[str, Any]]:
    """Fallback: fetch stock/index data via get_aggs for Basic plan users."""
    today = datetime.now().strftime("%Y-%m-%d")
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    results = []
    for ticker in tickers:
        try:
            aggs = provider.fetch_aggs(ticker, 1, "day", three_days_ago, today)
            if aggs and len(aggs) >= 2:
                results.append(_normalize_crypto_agg(aggs[-1], aggs[-2], ticker))
                if aggs[-2].get("close") is not None:
                    state.prev_closes[ticker] = aggs[-2]["close"]
            elif aggs:
                results.append(_normalize_crypto_agg(aggs[-1], None, ticker))
        except Exception:
            pass
        time.sleep(1)
    return results


_market_lock = threading.Lock()


def fetch_market_data(provider, watchlist: Dict[str, List[str]],
                      state: DashboardState, plans: PlanInfo):
    """Fetch data for stocks/indices. Uses snapshots if available, else aggs fallback."""
    if not _market_lock.acquire(blocking=False):
        return
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

        # Snapshot old change values for flash-on-change detection
        old_eq_changes = {item["ticker"]: item.get("change") for item in state.equities}
        old_ix_changes = {item["ticker"]: item.get("change") for item in state.indices}

        # Fetch via snapshots where available
        if snap_tickers:
            snap_list = provider.fetch_snapshots(snap_tickers)
            snap_map: Dict[str, Dict] = {d["ticker"]: d for d in snap_list}

            if plans.stocks_has_snapshots:
                new_eq = []
                for t in watchlist["equities"]:
                    if t in snap_map:
                        d = snap_map[t]
                        d["name"] = display_name(t)
                        old_chg = old_eq_changes.get(t)
                        new_chg = d.get("change")
                        if old_chg is not None and new_chg is not None and abs(new_chg - old_chg) > 0.001:
                            d["_flash_until"] = time.time() + 1.0
                            d["_flash_up"] = (new_chg - old_chg) > 0
                        new_eq.append(d)
                if new_eq:
                    state.equities = new_eq
            if plans.indices_has_snapshots:
                new_ix = []
                for t in watchlist["indices"]:
                    if t in snap_map:
                        d = snap_map[t]
                        d["name"] = display_name(t)
                        old_chg = old_ix_changes.get(t)
                        new_chg = d.get("change")
                        if old_chg is not None and new_chg is not None and abs(new_chg - old_chg) > 0.001:
                            d["_flash_until"] = time.time() + 1.0
                            d["_flash_up"] = (new_chg - old_chg) > 0
                        new_ix.append(d)
                if new_ix:
                    state.indices = new_ix

            # Cache previous closes for WS change calculations
            for t, d in snap_map.items():
                prev = d.get("prev_close")
                if prev is not None:
                    state.prev_closes[t] = prev

        # Fetch via aggs fallback for Basic plan tickers
        if agg_eq_tickers:
            new_eq = _fetch_via_aggs(provider, agg_eq_tickers, state)
            if new_eq:
                state.equities = new_eq
        if agg_ix_tickers:
            new_ix = _fetch_via_aggs(provider, agg_ix_tickers, state)
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
    finally:
        _market_lock.release()


# Crypto fetch state — lock prevents overlapping fetches from racing
_crypto_lock = threading.Lock()
_last_crypto_fetch: float = 0.0


def fetch_crypto_data(provider, watchlist: Dict[str, List[str]],
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
        old_crypto_changes = {item["ticker"]: item.get("change") for item in state.crypto}
        crypto_data = []

        if plans.currencies_has_snapshots:
            # Starter plan: use snapshots (unlimited, no rate limit concerns)
            try:
                snap_list = provider.fetch_snapshots(crypto_tickers)
                for d in snap_list:
                    t = d["ticker"]
                    d["name"] = display_name(t)
                    old_chg = old_crypto_changes.get(t)
                    new_chg = d.get("change")
                    if old_chg is not None and new_chg is not None and abs(new_chg - old_chg) > 0.001:
                        d["_flash_until"] = time.time() + 1.0
                        d["_flash_up"] = (new_chg - old_chg) > 0
                    crypto_data.append(d)
                    prev = d.get("prev_close")
                    if prev is not None:
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
                    aggs = provider.fetch_aggs(ticker, 1, "day", three_days_ago, today)
                    if aggs and len(aggs) >= 2:
                        cur = aggs[-1]
                        prev = aggs[-2]
                        crypto_data.append(_normalize_crypto_agg(cur, prev, ticker))
                        if prev.get("close") is not None:
                            state.prev_closes[ticker] = prev["close"]
                    elif aggs:
                        cur = aggs[-1]
                        crypto_data.append(_normalize_crypto_agg(cur, None, ticker))
                    # Store the data date from the most recent agg
                    if aggs:
                        ts = aggs[-1].get("timestamp")
                        if ts:
                            state.crypto_data_date = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
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


def fetch_ytd_closes(provider, watchlist: Dict[str, List[str]], state: DashboardState):
    """Fetch Dec 31 closing prices for YTD % calculation."""
    year = datetime.now().year
    # Try Dec 31 of previous year, then work backwards to find a trading day
    end_date = f"{year - 1}-12-31"
    start_date = f"{year - 1}-12-26"  # go back a few days in case Dec 31 was a weekend

    for ticker in watchlist["equities"] + watchlist["indices"]:
        if ticker in state.ytd_closes:
            continue
        try:
            aggs = provider.fetch_aggs(ticker, 1, "day", start_date, end_date)
            if aggs:
                state.ytd_closes[ticker] = aggs[-1]["close"]
        except Exception:
            pass
        time.sleep(0.5)  # gentle rate limiting


def fetch_ticker_details(provider, watchlist: Dict[str, List[str]], state: DashboardState):
    """Fetch static ticker details (market cap) once at startup."""
    for ticker in watchlist["equities"]:
        if ticker in state.ticker_details:
            continue
        try:
            d = provider.fetch_ticker_details(ticker)
            state.ticker_details[ticker] = d
        except Exception:
            pass
        time.sleep(0.5)


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


def fetch_economy_data(provider, state: DashboardState):
    """Fetch treasury yields, labor market, and inflation data.

    Checks disk cache first — skips API calls if data was fetched after the
    last NYSE close (4 PM ET).  Spaces API calls 15s apart to stay within
    5 calls/min rate limits.
    """
    if _load_econ_cache(state):
        return

    had_error = False

    # Treasury yields
    try:
        y = _fetch_economy_endpoint(lambda: provider.fetch_treasury_yields())
        if y:
            state.treasury = y
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "timed out" not in err_str.lower():
            state.economy_error = f"Treasury: {err_str[:60]}"
        had_error = True

    time.sleep(15)  # space calls to avoid 429

    # Labor market
    try:
        lm = _fetch_economy_endpoint(lambda: provider.fetch_labor_market())
        if lm:
            state.labor = lm
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "timed out" not in err_str.lower():
            state.economy_error = f"Labor: {err_str[:60]}"
        had_error = True

    time.sleep(15)  # space calls to avoid 429

    # Inflation — fetch 13 months for YoY calculation
    try:
        records = _fetch_economy_endpoint(lambda: provider.fetch_inflation(limit=13))
        if records:
            cur = records[0]
            state.inflation = {
                "cpi": cur.get("cpi"),
                "cpi_core": cur.get("cpi_core"),
                "date": cur.get("date"),
                "cpi_year_over_year": None,
            }
            # Calculate CPI YoY from current vs 12-month-ago record
            if len(records) >= 13:
                cur_cpi = cur.get("cpi")
                yago_cpi = records[-1].get("cpi")
                if cur_cpi and yago_cpi:
                    state.inflation["cpi_year_over_year"] = ((cur_cpi - yago_cpi) / yago_cpi) * 100
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
        _save_econ_cache(state)
