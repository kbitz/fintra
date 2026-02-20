import configparser
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List

from fintra.constants import (
    CONFIG_PATH, WATCHLISTS_DIR, DEFAULT_WATCHLIST,
    DEFAULT_REFRESH, DEFAULT_ECONOMY,
    EQUITY_COLUMNS, INDEX_COLUMNS, CRYPTO_COLUMNS,
    DEFAULT_EQUITY_COLS, DEFAULT_INDEX_COLS, DEFAULT_CRYPTO_COLS,
)


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


@dataclass
class Config:
    refresh_interval: int = DEFAULT_REFRESH
    economy_interval: int = DEFAULT_ECONOMY
    equity_cols: List[str] = field(default_factory=lambda: list(DEFAULT_EQUITY_COLS))
    index_cols: List[str] = field(default_factory=lambda: list(DEFAULT_INDEX_COLS))
    crypto_cols: List[str] = field(default_factory=lambda: list(DEFAULT_CRYPTO_COLS))


def _parse_col_list(value: str, available: dict, default: List[str]) -> List[str]:
    """Parse a comma-separated column list, validating against available columns."""
    cols = [c.strip().lower() for c in value.split(",") if c.strip()]
    valid = [c for c in cols if c in available]
    return valid if valid else default


def parse_config() -> Config:
    """Read config.ini and return a Config object."""
    cfg_obj = Config()
    if not os.path.exists(CONFIG_PATH):
        print("[notice] config.ini not found, using defaults")
        return cfg_obj

    cfg = configparser.RawConfigParser()
    cfg.read(CONFIG_PATH)
    sect = cfg["dashboard"] if "dashboard" in cfg else {}
    cfg_obj.refresh_interval = parse_interval(sect.get("refresh_interval", "10s"), DEFAULT_REFRESH)
    cfg_obj.economy_interval = parse_interval(sect.get("economy_interval", "1d"), DEFAULT_ECONOMY)

    if "equities_columns" in sect:
        cfg_obj.equity_cols = _parse_col_list(sect["equities_columns"], EQUITY_COLUMNS, DEFAULT_EQUITY_COLS)
    if "indices_columns" in sect:
        cfg_obj.index_cols = _parse_col_list(sect["indices_columns"], INDEX_COLUMNS, DEFAULT_INDEX_COLS)
    if "crypto_columns" in sect:
        cfg_obj.crypto_cols = _parse_col_list(sect["crypto_columns"], CRYPTO_COLUMNS, DEFAULT_CRYPTO_COLS)

    return cfg_obj


VALID_SECTIONS = {"equities", "crypto", "indices", "treasury", "economy"}


def parse_watchlist(path: str = "") -> Dict[str, List[str]]:
    """Parse a watchlist file into {equities: [], crypto: [], indices: [], treasury: [], economy: []}."""
    if not path:
        path = os.path.join(WATCHLISTS_DIR, DEFAULT_WATCHLIST)
    result: Dict[str, List[str]] = {"equities": [], "crypto": [], "indices": [], "treasury": [], "economy": []}
    if not os.path.exists(path):
        print(f"[error] {path} not found")
        sys.exit(1)

    current_section = None
    with open(path, "r") as f:
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


def validate_watchlist(path: str) -> bool:
    """Quick check that a file has at least one recognized [section] header."""
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    if line[1:-1].lower() in VALID_SECTIONS:
                        return True
    except OSError:
        return False
    return False


def list_watchlists() -> List[str]:
    """Scan WATCHLISTS_DIR for valid .txt watchlist files. Returns sorted absolute paths."""
    if not os.path.isdir(WATCHLISTS_DIR):
        return []
    paths = []
    for name in sorted(os.listdir(WATCHLISTS_DIR)):
        if not name.endswith(".txt"):
            continue
        full = os.path.join(WATCHLISTS_DIR, name)
        if os.path.isfile(full) and validate_watchlist(full):
            paths.append(full)
    return paths
