import os

# Project root: parent of the fintra/ package directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.ini")
WATCHLIST_PATH = os.path.join(PROJECT_ROOT, "watchlist.txt")
PLANS_PATH = os.path.join(PROJECT_ROOT, ".plans.json")

DEFAULT_REFRESH = 10
DEFAULT_ECONOMY = 86400  # 1 day — economy data changes at most daily

DISPLAY_NAMES = {
    "I:SPX": "S&P 500",
    "I:DJI": "Dow Jones",
    "I:DJA": "Dow Jones",
    "I:NDX": "Nasdaq 100",
    "I:VIX": "VIX",
    "X:BTCUSD": "BTC/USD",
    "X:ETHUSD": "ETH/USD",
    "X:SOLUSD": "SOL/USD",
    "X:XRPUSD": "XRP/USD",
}

# Map index tickers to their indicesGroups key from get_market_status()
INDEX_GROUPS = {
    "I:SPX": "s_and_p",
    "I:DJI": "dow_jones",
    "I:DJA": "dow_jones",
    "I:NDX": "nasdaq",
    "I:COMP": "nasdaq",
    "I:VIX": "s_and_p",
    "I:RUT": "ftse_russell",
}

ALL_YIELD_FIELDS = {
    "1M": "yield_1_month",
    "3M": "yield_3_month",
    "6M": "yield_6_month",
    "1Y": "yield_1_year",
    "2Y": "yield_2_year",
    "5Y": "yield_5_year",
    "10Y": "yield_10_year",
    "30Y": "yield_30_year",
}

# Default order when no [treasury] section in watchlist
DEFAULT_YIELD_KEYS = ["1M", "3M", "1Y", "2Y", "5Y", "10Y", "30Y"]

ALL_ECONOMY_FIELDS = {
    "unemployment": ("Unemployment", "unemployment_rate", "pct"),
    "participation": ("Participation", "participation_rate", "pct"),
    "avg_hourly_wage": ("Avg Hourly Wage", "avg_hourly_earnings", "dollar"),
    "cpi": ("CPI", "cpi", "num"),
    "core_cpi": ("Core CPI", "cpi_core", "num"),
}

DEFAULT_ECONOMY_KEYS = ["unemployment", "participation", "avg_hourly_wage", "cpi", "core_cpi"]

# Column definitions per section
# Each column: (header_label, justify, min_width)
EQUITY_COLUMNS = {
    "symbol":     ("Symbol", "left", 6),
    "name":       ("Name", "left", 10),
    "last":       ("Last", "right", 9),
    "chg":        ("Chg", "right", 9),
    "chg%":       ("Chg%", "right", 8),
    "open_close": ("Open", "right", 9),  # header toggles to "Close" when market closed
    "open":       ("Open", "right", 9),
    "high":       ("High", "right", 9),
    "low":        ("Low", "right", 9),
    "vol":        ("Vol", "right", 7),
    "ytd%":       ("YTD%", "right", 8),
}

INDEX_COLUMNS = {
    "symbol":     ("Symbol", "left", 8),
    "name":       ("Name", "left", 20),
    "last":       ("Last", "right", 12),
    "chg":        ("Chg", "right", 10),
    "chg%":       ("Chg%", "right", 8),
    "open_close": ("Open", "right", 10),
    "open":       ("Open", "right", 10),
    "high":       ("High", "right", 10),
    "low":        ("Low", "right", 10),
    "ytd%":       ("YTD%", "right", 8),
}

CRYPTO_COLUMNS = {
    "symbol": ("Symbol", "left", 10),
    "name":   ("Name", "left", 10),
    "last":   ("Last", "right", 14),
    "chg":    ("Chg", "right", 12),
    "chg%":   ("Chg%", "right", 8),
}

DEFAULT_EQUITY_COLS = ["symbol", "last", "chg", "chg%", "open_close", "high", "low", "vol"]
DEFAULT_INDEX_COLS = ["name", "last", "chg", "chg%"]
DEFAULT_CRYPTO_COLS = ["name", "last", "chg", "chg%"]
