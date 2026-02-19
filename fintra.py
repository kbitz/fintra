#!/usr/bin/env python3
"""Fintra — Terminal Market Dashboard"""

import configparser
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from massive import RESTClient, WebSocketClient
from massive.websocket import Feed, Market
from massive.websocket.models import CurrencyAgg, EquityAgg, IndexValue
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Constants ────────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")

DEFAULT_REFRESH = 10
DEFAULT_ECONOMY = 86400  # 1 day — economy data changes at most daily

DISPLAY_NAMES = {
    "I:SPX": "S&P 500",
    "I:DJI": "Dow Jones",
    "I:NDX": "Nasdaq 100",
    "I:VIX": "VIX",
    "X:BTCUSD": "BTC/USD",
    "X:ETHUSD": "ETH/USD",
    "X:SOLUSD": "SOL/USD",
    "X:XRPUSD": "XRP/USD",
}

YIELD_FIELDS = [
    ("1M", "yield_1_month"),
    ("3M", "yield_3_month"),
    ("6M", "yield_6_month"),
    ("1Y", "yield_1_year"),
    ("2Y", "yield_2_year"),
    ("5Y", "yield_5_year"),
    ("10Y", "yield_10_year"),
    ("30Y", "yield_30_year"),
]


# ── Config Parsing ───────────────────────────────────────────────────────────

def parse_interval(value: str, default: int) -> int:
    """Convert interval string like '10s', '1m', '5m', '1h', '1d' to seconds."""
    value = value.strip().lower()
    m = re.match(r"^(\d+)\s*(s|m|h|d)$", value)
    if not m:
        print(f"[warning] Invalid interval '{value}', using {default}s")
        return default
    num, unit = int(m.group(1)), m.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return num * multipliers[unit]


def parse_config() -> tuple[int, int]:
    """Read config.ini and return (refresh_seconds, economy_seconds)."""
    if not os.path.exists(CONFIG_PATH):
        print("[notice] config.ini not found, using defaults (10s market, 1d economy)")
        return DEFAULT_REFRESH, DEFAULT_ECONOMY

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    sect = cfg["dashboard"] if "dashboard" in cfg else {}
    refresh = parse_interval(sect.get("refresh_interval", "10s"), DEFAULT_REFRESH)
    economy = parse_interval(sect.get("economy_interval", "1d"), DEFAULT_ECONOMY)
    return refresh, economy


# ── Watchlist Parsing ────────────────────────────────────────────────────────

def parse_watchlist() -> Dict[str, List[str]]:
    """Parse watchlist.txt into {equities: [], crypto: [], indices: []}."""
    result: Dict[str, List[str]] = {"equities": [], "crypto": [], "indices": []}
    if not os.path.exists(WATCHLIST_PATH):
        print(f"[error] {WATCHLIST_PATH} not found")
        sys.exit(1)

    current_section = None
    with open(WATCHLIST_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].lower()
                if section in result:
                    current_section = section
                continue
            if current_section:
                result[current_section].append(line)
    return result


# ── Dashboard State ──────────────────────────────────────────────────────────

@dataclass
class DashboardState:
    equities: List[Dict[str, Any]] = field(default_factory=list)
    crypto: List[Dict[str, Any]] = field(default_factory=list)
    indices: List[Dict[str, Any]] = field(default_factory=list)
    treasury: Dict[str, Optional[float]] = field(default_factory=dict)
    labor: Dict[str, Optional[float]] = field(default_factory=dict)
    inflation: Dict[str, Optional[float]] = field(default_factory=dict)

    market_updated: Optional[float] = None
    economy_updated: Optional[float] = None

    market_stale: bool = False
    economy_stale: bool = False
    market_error: str = ""
    economy_error: str = ""

    prev_closes: Dict[str, float] = field(default_factory=dict)

    market_is_open: bool = False
    rate_limited: bool = False
    ws_connected: bool = False
    quit_flag: bool = False


# ── Formatting Helpers ───────────────────────────────────────────────────────

def fmt_price(val: Optional[float], large: bool = False) -> str:
    if val is None:
        return "—"
    if large:
        return f"{val:,.2f}"
    return f"{val:.2f}"


def fmt_change(val: Optional[float], large: bool = False) -> Text:
    if val is None:
        return Text("—", style="dim")
    sign = "+" if val >= 0 else ""
    s = f"{sign}{val:,.2f}" if large else f"{sign}{val:.2f}"
    style = "green" if val >= 0 else "red"
    return Text(s, style=style)


def fmt_pct(val: Optional[float]) -> Text:
    if val is None:
        return Text("—", style="dim")
    sign = "+" if val >= 0 else ""
    s = f"{sign}{val:.2f}%"
    style = "green" if val >= 0 else "red"
    return Text(s, style=style)


def fmt_volume(val: Optional[float]) -> str:
    if val is None:
        return "—"
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return str(int(val))


def fmt_yield_val(val: Optional[float]) -> Text:
    if val is None:
        return Text("—", style="dim")
    return Text(f"{val:.2f}%", style="cyan")


def display_name(ticker: str) -> str:
    return DISPLAY_NAMES.get(ticker, ticker)


# ── Snapshot Normalization ───────────────────────────────────────────────────

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


# ── Data Fetching ────────────────────────────────────────────────────────────

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


def fetch_market_data(client: RESTClient, watchlist: Dict[str, List[str]], state: DashboardState):
    """Fetch snapshots for all tickers in one unified call."""
    stock_index_tickers = watchlist["equities"] + watchlist["indices"]
    crypto_tickers = watchlist["crypto"]

    if not stock_index_tickers and not crypto_tickers:
        return

    # Fetch stocks + indices via universal snapshots (pass list, not string)
    if stock_index_tickers:
        try:
            snapshots = list(client.list_universal_snapshots(ticker_any_of=stock_index_tickers))
            snap_map: Dict[str, Any] = {}
            for s in snapshots:
                t = getattr(s, "ticker", None)
                # Skip NOT_ENTITLED tickers
                if t and not getattr(s, "error", None):
                    snap_map[t] = s

            state.equities = [normalize_snapshot(snap_map[t], t) for t in watchlist["equities"] if t in snap_map]
            state.indices = [normalize_snapshot(snap_map[t], t) for t in watchlist["indices"] if t in snap_map]

            # Cache previous closes for WS change calculations
            for t, s in snap_map.items():
                session = getattr(s, "session", None)
                if session:
                    prev = getattr(session, "previous_close", None)
                    if prev:
                        state.prev_closes[t] = prev
                    else:
                        # Derive prev close from current close - change
                        close = getattr(session, "close", None)
                        change = getattr(session, "change", None)
                        if close is not None and change is not None:
                            state.prev_closes[t] = close - change

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

    # Fetch crypto via get_aggs (snapshots not entitled on most plans)
    # Get last 2 daily bars to calculate change
    if crypto_tickers:
        try:
            from datetime import timedelta
            today = datetime.now().strftime("%Y-%m-%d")
            three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            crypto_data = []
            for ticker in crypto_tickers:
                try:
                    aggs = client.get_aggs(ticker, 1, "day", three_days_ago, today)
                    if aggs and len(aggs) >= 2:
                        cur = aggs[-1]
                        prev = aggs[-2]
                        crypto_data.append(_normalize_crypto_agg(cur, prev, ticker))
                        # Cache prev close for WS
                        if prev.close is not None:
                            state.prev_closes[ticker] = prev.close
                    elif aggs:
                        cur = aggs[-1]
                        crypto_data.append(_normalize_crypto_agg(cur, None, ticker))
                except Exception:
                    pass

            state.crypto = crypto_data
            if not state.market_updated:
                state.market_updated = time.time()

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate" in err_str.lower():
                state.rate_limited = True
            state.market_stale = True


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


def fetch_economy_data(client: RESTClient, state: DashboardState):
    """Fetch treasury yields, labor market, and inflation data."""
    had_error = False

    # Treasury yields
    try:
        yields = _fetch_with_timeout(
            lambda: list(client.list_treasury_yields(sort="date.desc", limit=1))
        )
        if yields:
            y = yields[0]
            state.treasury = {
                attr: getattr(y, attr, None) for _, attr in YIELD_FIELDS
            }
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "timed out" not in err_str.lower():
            state.economy_error = f"Treasury: {err_str[:60]}"
        had_error = True

    # Labor market
    try:
        labor = _fetch_with_timeout(
            lambda: list(client.list_labor_market_indicators(sort="date.desc", limit=1))
        )
        if labor:
            lm = labor[0]
            state.labor = {
                "unemployment_rate": getattr(lm, "unemployment_rate", None),
                "participation_rate": getattr(lm, "participation_rate", None),
                "nonfarm_payrolls": getattr(lm, "nonfarm_payrolls", None),
            }
    except Exception as e:
        err_str = str(e)
        if "429" not in err_str and "timed out" not in err_str.lower():
            state.economy_error = f"Labor: {err_str[:60]}"
        had_error = True

    # Inflation
    try:
        inf = _fetch_with_timeout(
            lambda: list(client.list_inflation(sort="date.desc", limit=1))
        )
        if inf:
            i = inf[0]
            state.inflation = {
                "cpi_yoy": getattr(i, "cpi_year_over_year", None),
                "pce": getattr(i, "pce", None),
                "pce_core": getattr(i, "pce_core", None),
                "cpi_core": getattr(i, "cpi_core", None),
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


# ── WebSocket Streaming ─────────────────────────────────────────────────────

def _update_ticker(items: List[Dict[str, Any]], ticker: str, last: float,
                   prev_closes: Dict[str, float], **extra):
    """Update a ticker dict in a list with new price data."""
    for item in items:
        if item["ticker"] == ticker:
            item["last"] = last
            prev = prev_closes.get(ticker)
            if prev:
                item["change"] = last - prev
                item["change_pct"] = (item["change"] / prev) * 100
            for k, v in extra.items():
                if v is not None:
                    if k in ("high",) and item.get(k) is not None:
                        item[k] = max(item[k], v)
                    elif k in ("low",) and item.get(k) is not None:
                        item[k] = min(item[k], v)
                    else:
                        item[k] = v
            return True
    return False


def start_ws_feeds(api_key: str, watchlist: Dict[str, List[str]], state: DashboardState):
    """Start WebSocket feeds for real-time price updates in background threads."""

    def _run_ws(ws_client, label):
        try:
            state.ws_connected = True
            ws_client.run(lambda msgs: _on_ws_msgs(msgs, state, label))
        except Exception:
            pass
        finally:
            state.ws_connected = False

    def _on_ws_msgs(msgs, state, label):
        for msg in msgs:
            if isinstance(msg, EquityAgg) and msg.symbol and msg.close is not None:
                _update_ticker(state.equities, msg.symbol, msg.close, state.prev_closes,
                               high=msg.high, low=msg.low, volume=msg.accumulated_volume)
                state.market_updated = time.time()

            elif isinstance(msg, IndexValue) and msg.ticker and msg.value is not None:
                _update_ticker(state.indices, msg.ticker, msg.value, state.prev_closes)
                state.market_updated = time.time()

            elif isinstance(msg, CurrencyAgg) and msg.pair and msg.close is not None:
                _update_ticker(state.crypto, msg.pair, msg.close, state.prev_closes,
                               high=msg.high, low=msg.low, volume=msg.volume)
                state.market_updated = time.time()

    # Stocks feed — second aggregates on Delayed feed
    if watchlist["equities"]:
        stock_subs = [f"A.{t}" for t in watchlist["equities"]]
        stock_ws = WebSocketClient(
            api_key=api_key, feed=Feed.Delayed,
            market=Market.Stocks, subscriptions=stock_subs,
        )
        threading.Thread(target=_run_ws, args=(stock_ws, "stocks"), daemon=True).start()

    # Indices feed — real-time index values on Delayed feed
    if watchlist["indices"]:
        index_subs = [f"V.{t}" for t in watchlist["indices"]]
        index_ws = WebSocketClient(
            api_key=api_key, feed=Feed.Delayed,
            market=Market.Indices, subscriptions=index_subs,
        )
        threading.Thread(target=_run_ws, args=(index_ws, "indices"), daemon=True).start()


# ── Table Builders ───────────────────────────────────────────────────────────

def build_equities_table(state: DashboardState) -> Panel:
    title = "EQUITIES"
    if state.market_stale:
        title += " (stale)"

    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("Symbol", style="bold white", min_width=8)
    table.add_column("Last", justify="right", min_width=9)
    table.add_column("Chg", justify="right", min_width=9)
    table.add_column("Chg%", justify="right", min_width=8)
    table.add_column("Open", justify="right", min_width=9)
    table.add_column("High", justify="right", min_width=9)
    table.add_column("Low", justify="right", min_width=9)
    table.add_column("Vol", justify="right", min_width=7)

    if not state.equities:
        table.add_row("—", "—", "—", "—", "—", "—", "—", "—")
    else:
        for eq in state.equities:
            table.add_row(
                eq["name"],
                fmt_price(eq.get("last")),
                fmt_change(eq.get("change")),
                fmt_pct(eq.get("change_pct")),
                fmt_price(eq.get("open")),
                fmt_price(eq.get("high")),
                fmt_price(eq.get("low")),
                fmt_volume(eq.get("volume")),
            )

    return Panel(table, title=f"[bold]{title}[/bold]", border_style="blue")


def build_crypto_table(state: DashboardState) -> Panel:
    title = "CRYPTO"
    if state.market_stale:
        title += " (stale)"

    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("Symbol", style="bold white", min_width=10)
    table.add_column("Last", justify="right", min_width=14)
    table.add_column("Chg", justify="right", min_width=12)
    table.add_column("Chg%", justify="right", min_width=8)

    if not state.crypto:
        table.add_row("—", "—", "—", "—")
    else:
        for c in state.crypto:
            table.add_row(
                c["name"],
                fmt_price(c.get("last"), large=True),
                fmt_change(c.get("change"), large=True),
                fmt_pct(c.get("change_pct")),
            )

    return Panel(table, title=f"[bold]{title}[/bold]", border_style="yellow")


def build_indices_table(state: DashboardState) -> Panel:
    title = "INDICES"
    if state.market_stale:
        title += " (stale)"

    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("Symbol", style="bold white", min_width=12)
    table.add_column("Last", justify="right", min_width=12)
    table.add_column("Chg", justify="right", min_width=10)
    table.add_column("Chg%", justify="right", min_width=8)

    if not state.indices:
        table.add_row("—", "—", "—", "—")
    else:
        for idx in state.indices:
            table.add_row(
                idx["name"],
                fmt_price(idx.get("last"), large=True),
                fmt_change(idx.get("change"), large=True),
                fmt_pct(idx.get("change_pct")),
            )

    return Panel(table, title=f"[bold]{title}[/bold]", border_style="green")


def build_treasury_panel(state: DashboardState) -> Panel:
    title = "TREASURY YIELDS"
    if state.economy_stale:
        title += " (stale)"

    table = Table(expand=True, box=None, padding=(0, 1), show_header=False)
    table.add_column("Label", style="bold white", min_width=4)
    table.add_column("Value", justify="right", min_width=7)
    table.add_column("Label2", style="bold white", min_width=4)
    table.add_column("Value2", justify="right", min_width=7)

    # Display as two-column pairs
    pairs = []
    for label, attr in YIELD_FIELDS:
        val = state.treasury.get(attr)
        pairs.append((label, val))

    # Arrange: left column = short maturities, right = long
    half = len(pairs) // 2
    left = pairs[:half]
    right = pairs[half:]

    for i in range(max(len(left), len(right))):
        l_label = left[i][0] if i < len(left) else ""
        l_val = fmt_yield_val(left[i][1]) if i < len(left) else Text("")
        r_label = right[i][0] if i < len(right) else ""
        r_val = fmt_yield_val(right[i][1]) if i < len(right) else Text("")
        table.add_row(l_label, l_val, r_label, r_val)

    return Panel(table, title=f"[bold]{title}[/bold]", border_style="cyan")


def build_economy_panel(state: DashboardState) -> Panel:
    title = "ECONOMY"
    if state.economy_stale:
        title += " (stale)"

    table = Table(expand=True, box=None, padding=(0, 1), show_header=False)
    table.add_column("Indicator", style="bold white", min_width=16)
    table.add_column("Value", justify="right", min_width=8)

    unemp = state.labor.get("unemployment_rate")
    partic = state.labor.get("participation_rate")
    cpi = state.inflation.get("cpi_yoy")
    pce = state.inflation.get("pce")
    pce_core = state.inflation.get("pce_core")
    nonfarm = state.labor.get("nonfarm_payrolls")

    def pct_or_dash(val):
        return f"{val:.1f}%" if val is not None else "—"

    def num_or_dash(val):
        if val is None:
            return "—"
        return f"{val:,.0f}K" if val >= 1000 else f"{val:,.0f}"

    table.add_row("Unemployment", pct_or_dash(unemp))
    table.add_row("Participation", pct_or_dash(partic))
    table.add_row("CPI YoY", pct_or_dash(cpi))
    table.add_row("PCE", pct_or_dash(pce))
    table.add_row("Core PCE", pct_or_dash(pce_core))
    if nonfarm is not None:
        table.add_row("Nonfarm Payrolls", num_or_dash(nonfarm))

    return Panel(table, title=f"[bold]{title}[/bold]", border_style="magenta")


# ── Layout ───────────────────────────────────────────────────────────────────

def make_header(state: DashboardState) -> Panel:
    now = datetime.now().strftime("%H:%M:%S")

    if state.market_updated:
        ago = int(time.time() - state.market_updated)
        if ago < 60:
            refresh_str = f"{ago}s ago"
        else:
            refresh_str = f"{ago // 60}m ago"
    else:
        refresh_str = "never"

    is_open = state.market_is_open
    market_status = Text("Open", style="bold green") if is_open else Text("Closed", style="bold red")

    ws_status = Text("WS", style="bold green") if state.ws_connected else Text("REST", style="dim")
    left = Text.assemble("Market: ", market_status, "    ", ws_status, f"    Last: {refresh_str}")

    if state.market_error:
        left.append(f"    ⚠ {state.market_error}", style="bold yellow")
    if state.rate_limited:
        left.append("    [rate limited]", style="bold red")

    right = Text(f"{now}  [q] Quit", style="dim")

    header_table = Table(expand=True, box=None, show_header=False, padding=0)
    header_table.add_column("left")
    header_table.add_column("right", justify="right")
    header_table.add_row(left, right)

    return Panel(header_table, title="[bold white]FINTRA[/bold white]", border_style="bright_white")


def build_layout(state: DashboardState) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="equities", size=3 + max(len(state.equities), 1) + 1),
        Layout(name="crypto", size=3 + max(len(state.crypto), 1) + 1),
        Layout(name="indices", size=3 + max(len(state.indices), 1) + 1),
        Layout(name="bottom", size=9),
    )

    layout["header"].update(make_header(state))
    layout["equities"].update(build_equities_table(state))
    layout["crypto"].update(build_crypto_table(state))
    layout["indices"].update(build_indices_table(state))

    bottom = Layout()
    bottom.split_row(
        Layout(name="treasury"),
        Layout(name="economy"),
    )
    bottom["treasury"].update(build_treasury_panel(state))
    bottom["economy"].update(build_economy_panel(state))
    layout["bottom"].update(bottom)

    return layout


# ── Key Listener ─────────────────────────────────────────────────────────────

def key_listener(state: DashboardState):
    """Background thread that listens for 'q' to quit."""
    try:
        import tty
        import termios

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not state.quit_flag:
                ch = sys.stdin.read(1)
                if ch in ("q", "Q"):
                    state.quit_flag = True
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        # Fallback: just wait for quit_flag (Ctrl+C handled in main)
        while not state.quit_flag:
            time.sleep(0.5)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Load .env file if present
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

    # Validate API key
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        print("[error] MASSIVE_API_KEY environment variable not set.")
        print("  export MASSIVE_API_KEY='your_key'")
        sys.exit(1)

    # Parse config and watchlist
    refresh_interval, economy_interval = parse_config()
    watchlist = parse_watchlist()

    total_tickers = sum(len(v) for v in watchlist.values())
    if total_tickers == 0:
        print("[error] watchlist.txt has no tickers.")
        sys.exit(1)

    print(f"[fintra] Refresh: {refresh_interval}s market, {economy_interval}s economy")
    print(f"[fintra] Watching {total_tickers} tickers")

    client = RESTClient(api_key=api_key)
    state = DashboardState()

    # Start key listener thread
    listener = threading.Thread(target=key_listener, args=(state,), daemon=True)
    listener.start()

    # Fetch market status
    try:
        ms = client.get_market_status()
        state.market_is_open = getattr(ms, "market", "") == "open"
    except Exception:
        pass

    # Initial data fetch (REST baseline)
    fetch_market_data(client, watchlist, state)
    fetch_economy_data(client, state)

    # Start WebSocket feeds for real-time updates
    print("[fintra] Starting WebSocket feeds...")
    start_ws_feeds(api_key, watchlist, state)

    last_market_fetch = time.time()
    last_economy_fetch = time.time()

    effective_refresh = refresh_interval

    console = Console()

    try:
        with Live(build_layout(state), console=console, screen=True, refresh_per_second=2) as live:
            while not state.quit_flag:
                now = time.time()

                # Market data refresh
                if now - last_market_fetch >= effective_refresh:
                    fetch_market_data(client, watchlist, state)
                    last_market_fetch = now
                    # Update market status
                    try:
                        ms = client.get_market_status()
                        state.market_is_open = getattr(ms, "market", "") == "open"
                    except Exception:
                        pass
                    # Handle rate limiting: double interval temporarily
                    if state.rate_limited:
                        effective_refresh = min(refresh_interval * 4, 120)
                    else:
                        effective_refresh = refresh_interval

                # Economy data refresh
                if now - last_economy_fetch >= economy_interval:
                    fetch_economy_data(client, state)
                    last_economy_fetch = now

                live.update(build_layout(state))
                time.sleep(0.5)

    except KeyboardInterrupt:
        pass
    finally:
        state.quit_flag = True
        console.clear()
        print("[fintra] Goodbye.")


if __name__ == "__main__":
    main()
