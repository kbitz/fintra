import os

# Project root: parent of the fintra/ package directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.ini")
WATCHLISTS_DIR = os.path.join(PROJECT_ROOT, "watchlists")
DEFAULT_WATCHLIST = "watchlist.txt"
PLANS_PATH = os.path.join(PROJECT_ROOT, ".plans.json")
ECON_CACHE_PATH = os.path.join(PROJECT_ROOT, ".econ_cache.json")

DEFAULT_REFRESH = 10
DEFAULT_ECONOMY = 86400  # 1 day — economy data changes at most daily

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
    "cpi_yoy": ("CPI YoY", "cpi_year_over_year", "pct"),
}

DEFAULT_ECONOMY_KEYS = ["unemployment", "participation", "avg_hourly_wage", "cpi", "core_cpi"]

# Column definitions per section
# Each column: (header_label, justify, min_width)
# Column definitions per section (symbol is always prepended automatically)
# Each column: (header_label, justify, min_width)
EQUITY_COLUMNS = {
    "last":       ("Last", "right", 9),
    "chg":        ("Chg", "right", 9),
    "chg%":       ("Chg%", "right", 8),
    "open_close": ("Open", "right", 9),  # header toggles to "Close" when market closed
    "open":       ("Open", "right", 9),
    "high":       ("High", "right", 9),
    "low":        ("Low", "right", 9),
    "vol":        ("Vol", "right", 7),
    "mktcap":     ("Mkt Cap", "right", 9),
    "ytd%":       ("YTD%", "right", 8),
}

INDEX_COLUMNS = {
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
    "last":   ("Last", "right", 14),
    "chg":    ("Chg", "right", 12),
    "chg%":   ("Chg%", "right", 8),
}

# Symbol min-widths per section (symbol column is always first, no header)
SYMBOL_MIN_WIDTH = {"equity": 6, "index": 8, "crypto": 10}

DEFAULT_EQUITY_COLS = ["last", "chg", "chg%", "open_close", "high", "low", "vol"]
DEFAULT_INDEX_COLS = ["last", "chg", "chg%"]
DEFAULT_CRYPTO_COLS = ["last", "chg", "chg%"]
