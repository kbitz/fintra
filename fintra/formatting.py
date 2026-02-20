from typing import Optional

from rich.text import Text

from fintra.constants import DISPLAY_NAMES


def fmt_price(val: Optional[float], large: bool = False) -> Text:
    if val is None:
        return Text("—", style="dim")
    if large:
        return Text(f"{val:,.2f}", style="cyan")
    return Text(f"{val:.2f}", style="cyan")


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


def fmt_volume(val: Optional[float]) -> Text:
    if val is None:
        return Text("—", style="dim")
    if val >= 1_000_000_000:
        s = f"{val / 1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        s = f"{val / 1_000_000:.1f}M"
    elif val >= 1_000:
        s = f"{val / 1_000:.1f}K"
    else:
        s = str(int(val))
    return Text(s, style="cyan")


def fmt_market_cap(val: Optional[float]) -> Text:
    if val is None:
        return Text("—", style="dim")
    if val >= 1_000_000_000_000:
        s = f"${val / 1_000_000_000_000:.2f}T"
    elif val >= 1_000_000_000:
        s = f"${val / 1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        s = f"${val / 1_000_000:.0f}M"
    else:
        s = f"${val:,.0f}"
    return Text(s, style="cyan")


def fmt_yield_val(val: Optional[float]) -> Text:
    if val is None:
        return Text("—", style="dim")
    return Text(f"{val:.2f}%", style="cyan")


def display_name(ticker: str) -> str:
    return DISPLAY_NAMES.get(ticker, ticker)
