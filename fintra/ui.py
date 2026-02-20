import sys
import time
from datetime import datetime
from typing import Any, Dict, List

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fintra.config import Config
from fintra.constants import (
    EQUITY_COLUMNS, INDEX_COLUMNS, CRYPTO_COLUMNS,
    ALL_YIELD_FIELDS, DEFAULT_YIELD_KEYS,
    ALL_ECONOMY_FIELDS, DEFAULT_ECONOMY_KEYS,
)
from fintra.formatting import (
    fmt_price, fmt_change, fmt_pct, fmt_volume, fmt_market_cap, fmt_yield_val,
    fmt_ext_chg, fmt_ext_pct, fmt_ext_price, display_name,
)
from fintra.plans import PlanInfo
from fintra.state import DashboardState


def _get_ext_hours(item: Dict[str, Any]) -> tuple:
    """Return (ext_change, ext_change_pct, label) for extended hours, or Nones."""
    ah_chg = item.get("after_hours_change")
    ah_pct = item.get("after_hours_change_pct")
    if ah_chg is not None or ah_pct is not None:
        return (ah_chg, ah_pct, "AH")
    pm_chg = item.get("pre_market_change")
    pm_pct = item.get("pre_market_change_pct")
    if pm_chg is not None or pm_pct is not None:
        return (pm_chg, pm_pct, "PM")
    return (None, None, None)


def _apply_flash(result: Text, item: Dict[str, Any]) -> Text:
    """If flash is active, override style with flash background."""
    if time.time() < item.get("_flash_until", 0):
        bg = "on dark_green" if item.get("_flash_up") else "on dark_red"
        return Text(result.plain, style=f"bold white {bg}")
    return result


def _regular_close(item: Dict[str, Any]):
    """Compute regular session close: prev_close + regular_change, or fall back to last."""
    reg_chg = item.get("regular_change")
    prev = item.get("prev_close")
    if reg_chg is not None and prev is not None:
        return prev + reg_chg
    return None


def _cell_value(col_key: str, item: Dict[str, Any], state: DashboardState, large: bool = False):
    """Return the formatted cell value for a given column key and data item."""
    if col_key == "symbol":
        return item["ticker"]
    elif col_key == "name":
        return display_name(item["ticker"])
    elif col_key == "last":
        if not state.market_is_open:
            ext_chg, ext_pct, label = _get_ext_hours(item)
            if label is not None and ext_chg is not None:
                reg_close = _regular_close(item) or item.get("last")
                ext_price = reg_close + ext_chg if reg_close is not None else None
                if state.extended_hours:
                    style = "green" if ext_chg >= 0 else "red"
                else:
                    style = "cyan"
                return fmt_price(ext_price, large=large, style=style)
            return fmt_price(item.get("last"), large=large)
        chg = item.get("change")
        style = "green" if chg is not None and chg >= 0 else "red" if chg is not None else "cyan"
        return fmt_price(item.get("last"), large=large, style=style)
    elif col_key == "chg":
        if not state.market_is_open:
            ext_chg, ext_pct, label = _get_ext_hours(item)
            if label is not None:
                main_chg = item.get("regular_change") or item.get("change")
                result = fmt_change(main_chg, large=large)
                ext_ann = fmt_ext_chg(ext_chg, large=large)
                if ext_ann:
                    result.append_text(ext_ann)
                return _apply_flash(result, item)
        result = fmt_change(item.get("change"), large=large)
        return _apply_flash(result, item)
    elif col_key == "chg%":
        if not state.market_is_open:
            ext_chg, ext_pct, label = _get_ext_hours(item)
            if label is not None:
                main_pct = item.get("regular_change_pct") or item.get("change_pct")
                result = fmt_pct(main_pct)
                ext_ann = fmt_ext_pct(ext_pct)
                if ext_ann:
                    result.append_text(ext_ann)
                return _apply_flash(result, item)
        result = fmt_pct(item.get("change_pct"))
        return _apply_flash(result, item)
    elif col_key == "open_close":
        if state.market_is_open:
            return fmt_price(item.get("open"), large=large)
        else:
            reg_close = _regular_close(item)
            return fmt_price(reg_close or item.get("last"), large=large)
    elif col_key == "open":
        return fmt_price(item.get("open"), large=large)
    elif col_key == "high":
        return fmt_price(item.get("high"), large=large)
    elif col_key == "low":
        return fmt_price(item.get("low"), large=large)
    elif col_key == "vol":
        return fmt_volume(item.get("volume"))
    elif col_key == "mktcap":
        ticker = item.get("ticker", "")
        details = state.ticker_details.get(ticker, {})
        return fmt_market_cap(details.get("market_cap"))
    elif col_key == "ytd%":
        ticker = item.get("ticker", "")
        ytd_close = state.ytd_closes.get(ticker)
        last = item.get("last")
        if ytd_close and last:
            pct = ((last - ytd_close) / ytd_close) * 100
            return fmt_pct(pct)
        return Text("—", style="dim")
    return "—"


def _build_market_table(items: List[Dict[str, Any]], col_keys: List[str],
                        col_defs: dict, state: DashboardState, large: bool = False) -> Table:
    """Build a Rich Table from data items using the given column configuration."""
    table = Table(expand=True, box=None, padding=(0, 1))

    for key in col_keys:
        if key not in col_defs:
            continue
        label, justify, min_width = col_defs[key]
        # Toggle open_close header based on market status
        if key == "open_close":
            label = "Open" if state.market_is_open else "Close"
        style = "bold white" if justify == "left" else None
        table.add_column(label, justify=justify, min_width=min_width, style=style)

    if not items:
        table.add_row(*["—"] * len(col_keys))
    else:
        for item in items:
            row = [_cell_value(k, item, state, large=large) for k in col_keys if k in col_defs]
            table.add_row(*row)

    return table


def _data_freshness(plan_tier: str, market: str = "stocks") -> str:
    """Return the data freshness label based on plan tier and market.

    Currencies Starter is real-time, not 15min delayed like Stocks/Indices Starter.
    """
    if plan_tier == "advanced":
        return "real-time"
    elif plan_tier in ("starter", "developer"):
        if market == "crypto":
            return "real-time"
        return "15m delayed"
    else:
        return "end of day"


def _format_date(date_val, fmt: str = "%b %d, %Y") -> str:
    """Format a date value using the given strftime format.

    Converts to a naive date first to avoid timezone shifts.
    """
    if not date_val:
        return ""
    # Extract the bare YYYY-MM-DD string to avoid timezone adjustments
    date_str = str(date_val)[:10]
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return str(date_val)


def _market_subtitle(freshness: str, state: DashboardState, streaming: bool = False,
                     show_extended: bool = True) -> str:
    """Build the subtitle string for a market section panel."""
    parts = [freshness]
    if streaming:
        parts.append("streaming")
    if state.market_stale:
        parts.append("stale")
    if not state.market_is_open:
        if show_extended and state.extended_hours:
            parts.append("extended hours")
        else:
            parts.append("market closed")
    return ", ".join(parts)


def build_equities_table(state: DashboardState, config: Config, plans: PlanInfo) -> Panel:
    freshness = _data_freshness(plans.stocks)
    streaming = state.ws_connected and plans.stocks_has_ws
    subtitle = _market_subtitle(freshness, state, streaming=streaming)

    table = _build_market_table(state.equities, config.equity_cols, EQUITY_COLUMNS, state)
    return Panel(table, title="[bold grey70]EQUITIES[/bold grey70]", subtitle=f"[grey46]{subtitle}[/grey46]",
                 subtitle_align="right", border_style="grey70")


def build_crypto_table(state: DashboardState, config: Config, plans: PlanInfo) -> Panel:
    freshness = _data_freshness(plans.currencies, market="crypto")
    if plans.currencies_has_snapshots:
        # Starter plan: real-time polling
        parts = [freshness]
        if state.crypto_updated:
            ago = int(time.time() - state.crypto_updated)
            parts.append(f"polled {ago}s ago" if ago < 60 else f"polled {ago // 60}m ago")
        subtitle = ", ".join(parts)
    else:
        # Basic plan: daily aggs — show the data date
        subtitle = state.crypto_data_date or freshness

    table = _build_market_table(state.crypto, config.crypto_cols, CRYPTO_COLUMNS, state, large=True)
    return Panel(table, title="[bold grey70]CRYPTO[/bold grey70]", subtitle=f"[grey46]{subtitle}[/grey46]",
                 subtitle_align="right", border_style="grey70")


def build_indices_table(state: DashboardState, config: Config, plans: PlanInfo) -> Panel:
    freshness = _data_freshness(plans.indices)
    streaming = state.ws_connected and plans.indices_has_ws
    subtitle = _market_subtitle(freshness, state, streaming=streaming, show_extended=False)

    table = _build_market_table(state.indices, config.index_cols, INDEX_COLUMNS, state, large=True)
    return Panel(table, title="[bold grey70]INDICES[/bold grey70]", subtitle=f"[grey46]{subtitle}[/grey46]",
                 subtitle_align="right", border_style="grey70")


def build_treasury_panel(state: DashboardState, watchlist: Dict[str, List[str]]) -> Panel:
    treas_date = state.treasury.get("date", "")
    yield_keys = watchlist.get("treasury") or DEFAULT_YIELD_KEYS

    table = Table(expand=True, box=None, padding=(0, 1), show_header=False)
    table.add_column("Maturity", style="bold white", no_wrap=True)
    table.add_column("Yield", justify="right", no_wrap=True)

    for key in yield_keys:
        attr = ALL_YIELD_FIELDS.get(key.upper())
        if attr:
            val = state.treasury.get(attr)
            table.add_row(key.upper(), fmt_yield_val(val))

    subtitle = _format_date(treas_date, fmt="%Y-%m-%d") or "loading..."
    return Panel(table, title="[bold grey70]TREASURY YIELDS[/bold grey70]", subtitle=f"[grey46]{subtitle}[/grey46]",
                 subtitle_align="right", border_style="grey70")


def build_economy_panel(state: DashboardState, watchlist: Dict[str, List[str]]) -> Panel:
    labor_date = state.labor.get("date", "")
    inflation_date = state.inflation.get("date", "")
    date_str = labor_date or inflation_date or ""
    economy_keys = watchlist.get("economy") or DEFAULT_ECONOMY_KEYS

    table = Table(expand=True, box=None, padding=(0, 1), show_header=False)
    table.add_column("Indicator", style="bold white", no_wrap=True)
    table.add_column("Value", justify="right", no_wrap=True)

    def pct_or_dash(val):
        return Text(f"{val:.1f}%", style="cyan") if val is not None else Text("—", style="dim")

    def dollar_or_dash(val):
        return Text(f"${val:,.2f}", style="cyan") if val is not None else Text("—", style="dim")

    def num_or_dash(val):
        return Text(f"{val:,.3f}", style="cyan") if val is not None else Text("—", style="dim")

    formatters = {"pct": pct_or_dash, "dollar": dollar_or_dash, "num": num_or_dash}

    # Merge labor + inflation into one lookup dict
    econ_data = {}
    econ_data.update(state.labor)
    econ_data.update(state.inflation)
    for key in economy_keys:
        meta = ALL_ECONOMY_FIELDS.get(key.lower())
        if meta:
            label, attr, fmt_type = meta
            val = econ_data.get(attr)
            table.add_row(label, formatters[fmt_type](val))

    subtitle = _format_date(date_str, fmt="%b %Y") or "loading..."
    return Panel(table, title="[bold grey70]ECONOMY[/bold grey70]", subtitle=f"[grey46]{subtitle}[/grey46]",
                 subtitle_align="right", border_style="grey70")


def make_header(state: DashboardState) -> Panel:
    now = datetime.now().strftime("%H:%M:%S")

    left = Text()
    if state.active_watchlist_name:
        left.append(state.active_watchlist_name, style="bold cyan")
        left.append("  ")
    if state.watchlist_error:
        left.append(f"\u26a0 {state.watchlist_error}", style="bold yellow")
        left.append("  ")
    if state.market_error:
        left.append(f"\u26a0 {state.market_error}", style="bold yellow")
    if state.rate_limited:
        if left.plain:
            left.append("[rate limited]", style="bold red")
        else:
            left.append("    [rate limited]", style="bold red")

    right = Text(f"{now}  [l] List  [q] Quit", style="dim")

    header_table = Table(expand=True, box=None, show_header=False, padding=0)
    header_table.add_column("left")
    header_table.add_column("right", justify="right")
    header_table.add_row(left, right)

    return Panel(header_table, title="[bold grey70]FINTRA[/bold grey70]", border_style="grey70")


def build_layout(state: DashboardState, watchlist: Dict[str, List[str]],
                 config: Config, plans: PlanInfo) -> Layout:
    layout = Layout()

    # Panel border = 2 rows (top+bottom), so content rows = size - 2
    eq_rows = max(len(state.equities), 1) + 1  # +1 for header row
    cr_rows = max(len(state.crypto), 1) + 1
    ix_rows = max(len(state.indices), 1) + 1

    # Bottom panels: one item per row
    yield_keys = watchlist.get("treasury") or DEFAULT_YIELD_KEYS
    economy_keys = watchlist.get("economy") or DEFAULT_ECONOMY_KEYS
    bottom_rows = max(len(yield_keys), len(economy_keys)) + 2  # +2 for panel border

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="indices", size=ix_rows + 2),
        Layout(name="equities", size=eq_rows + 2),
        Layout(name="crypto", size=cr_rows + 2),
        Layout(name="bottom", size=bottom_rows),
    )

    layout["header"].update(make_header(state))
    layout["indices"].update(build_indices_table(state, config, plans))
    layout["equities"].update(build_equities_table(state, config, plans))
    layout["crypto"].update(build_crypto_table(state, config, plans))

    bottom = Layout()
    bottom.split_row(
        Layout(name="treasury"),
        Layout(name="economy"),
    )
    bottom["treasury"].update(build_treasury_panel(state, watchlist))
    bottom["economy"].update(build_economy_panel(state, watchlist))
    layout["bottom"].update(bottom)

    return layout


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
                elif ch in ("l", "L"):
                    state.switch_watchlist = True
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        # Fallback: just wait for quit_flag (Ctrl+C handled in main)
        while not state.quit_flag:
            time.sleep(0.5)
