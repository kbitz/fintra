# Fintra — Implementation Reference

## Git Commits

Do NOT include `Co-Authored-By` trailers in commit messages. Attribution is in the README.

## File Layout

```
Fintra/                        # project root
├── README.md
├── CLAUDE.md
├── config.ini                 # refresh intervals, column config
├── watchlist.txt              # ticker lists by section (equities, crypto, indices, treasury, economy)
├── requirements.txt           # massive, rich
├── setup.sh                   # creates venv, installs deps
├── .env                       # MASSIVE_API_KEY=... (gitignored)
├── .env.example               # template for users (no real key)
├── .plans.json                # cached API plan detection (gitignored)
├── .gitignore
└── fintra/                    # Python package
    ├── __init__.py            # version, docstring
    ├── __main__.py            # python -m fintra entry point
    ├── constants.py           # display names, yield/economy fields, column defs, paths
    ├── config.py              # Config dataclass, parse_config, parse_interval, parse_watchlist
    ├── state.py               # DashboardState dataclass
    ├── plans.py               # PlanInfo dataclass, probe/load/save plans
    ├── formatting.py          # fmt_price, fmt_change, fmt_pct, fmt_volume, fmt_yield_val, display_name
    ├── data.py                # All data fetching: market, crypto, economy, YTD, normalization helpers
    ├── websocket.py           # WS streaming: start/stop feeds, _update_ticker, message handler
    ├── ui.py                  # Table/panel builders, layout, header, key_listener
    └── app.py                 # main() orchestration loop
```

Run with: `python -m fintra`

## Module Architecture

### `constants.py`
- `PROJECT_ROOT` — resolved via `os.path.dirname(os.path.dirname(__file__))`, all config/data files are relative to this
- `CONFIG_PATH`, `WATCHLIST_PATH`, `PLANS_PATH`
- `DISPLAY_NAMES` — ticker → friendly name mapping
- `INDEX_GROUPS` — ticker → `indicesGroups` API key mapping (e.g. `"I:SPX"` → `"s_and_p"`)
- `ALL_YIELD_FIELDS`, `DEFAULT_YIELD_KEYS` — treasury yield maturity mappings
- `ALL_ECONOMY_FIELDS`, `DEFAULT_ECONOMY_KEYS` — economy indicator definitions (label, API attr, format type)
- `EQUITY_COLUMNS`, `INDEX_COLUMNS`, `CRYPTO_COLUMNS` — column definitions per section, each with "symbol" (raw ticker) and "name" (display name) columns
- `DEFAULT_EQUITY_COLS` — uses "symbol"; `DEFAULT_INDEX_COLS`, `DEFAULT_CRYPTO_COLS` — use "name"

### `config.py`
- `parse_interval()` — converts `10s`/`1m`/`1h`/`1d` to seconds
- `Config` dataclass — refresh/economy intervals + column lists per section
- `parse_config()` — reads config.ini into `Config`, validates column names against available columns
- `parse_watchlist()` — reads watchlist.txt into `{equities: [], crypto: [], indices: [], treasury: [], economy: []}`

### `state.py`
- `DashboardState` dataclass — shared mutable state:
  - `equities`, `crypto`, `indices` — lists of flat dicts with `ticker`, `name`, `last`, `change`, `change_pct`, `open`, `high`, `low`, `volume`
  - `treasury`, `labor`, `inflation` — dicts of latest values + `date` key
  - `prev_closes` — cached previous session closes for WS change calc
  - `ytd_closes` — Dec 31 closes for YTD % calculation
  - `market_updated`, `crypto_updated`, `economy_updated` — timestamps
  - `crypto_data_date` — date string of the crypto agg bar (basic plan only, shown in subtitle)
  - `market_is_open` — overall US equity market status (NYSE/NASDAQ)
  - `indices_group_status` — per-group open/closed from `get_market_status().indicesGroups`
  - `ws_connected`, `rate_limited`, `quit_flag` — flags
  - `market_stale`, `economy_stale`, `market_error`, `economy_error` — status tracking

### `plans.py`
- `PlanInfo` dataclass — detected API plan per asset class (stocks, indices, currencies)
  - Properties: `stocks_has_snapshots`, `stocks_has_ws`, `stocks_realtime`, `indices_has_snapshots`, `indices_has_ws`, `indices_realtime`, `currencies_has_snapshots`, `currencies_has_ws`, `currencies_unlimited`
- `_probe_plans()` — probes snapshot endpoints to detect plan tier
- `load_plans()` / `save_plans()` — cached in `.plans.json`

### `formatting.py`
- `fmt_price(val, large)` — returns cyan `Text`; uses comma separator when `large=True`
- `fmt_change(val, large)` — returns green/red `Text` with +/- sign
- `fmt_pct(val)` — returns green/red `Text` with % suffix
- `fmt_volume(val)` — returns cyan `Text` with B/M/K suffixes
- `fmt_yield_val(val)` — returns cyan `Text` with % suffix
- `display_name(ticker)` — ticker → friendly name via `DISPLAY_NAMES`

### `data.py`
- `normalize_snapshot()` — converts REST snapshot to flat dict; tries `session.close`, then `last_trade.price`, then `last_quote` midpoint, then top-level `price`/`value`
- `_normalize_crypto_agg()` — converts crypto agg + previous close to flat dict
- `_fetch_via_aggs()` — fallback for Basic plan: fetch via `get_aggs` instead of snapshots
- `fetch_market_data()` — REST snapshots (Starter+) or aggs fallback (Basic) for stocks+indices. Caches `prev_closes`.
- `fetch_crypto_data()` — snapshots (Starter) or rate-limited `get_aggs` (Basic). Lock prevents overlapping fetches. Atomic swap on full success, merge on partial. Stores `crypto_data_date` from agg timestamp for basic plan.
- `fetch_ytd_closes()` — fetches Dec 31 closing prices for YTD % column
- `_fetch_with_timeout()` — wraps callable in thread with timeout to prevent hanging on 429 retries
- `_fetch_economy_endpoint()` — retry wrapper for economy endpoints
- `fetch_economy_data()` — 3 sequential REST calls (treasury, labor, inflation) spaced 15s apart. Uses `next(iter(...))` NOT `list()`.

### `websocket.py`
- `_update_ticker()` — updates a ticker dict in state with new price, recalculates change/change_pct from `prev_closes`, updates high/low/volume with min/max logic
- `start_ws_feeds()` — launches WS background threads per entitled asset class. Stocks use `A.<ticker>` (second aggs), indices use `V.<ticker>` (index values), crypto uses `XA.<ticker>`. Feed type selected based on plan (Delayed vs RealTime). Returns client list for lifecycle management.
- `stop_ws_feeds()` — closes all WS client connections

### `ui.py`
- `_cell_value()` — returns formatted cell value for a column key + data item. "symbol" returns raw ticker, "name" returns `display_name()`. "open_close" toggles between open/close based on `market_is_open`.
- `_build_market_table()` — generic Rich Table builder from column config
- `_data_freshness(plan_tier, market)` — returns freshness label: "real-time" (advanced or crypto starter), "15m delayed" (starter), "end of day" (basic)
- `_format_date(date_val, fmt)` — date formatter with configurable strftime format
- `_market_subtitle(freshness, state, streaming)` — builds subtitle: freshness + "streaming" (if WS) + "stale" (if stale) + "market closed" (if closed)
- `build_equities_table()`, `build_indices_table()` — section Panels with freshness + market closed subtitles
- `build_crypto_table()` — starter: "real-time, polled Xs ago"; basic: shows `crypto_data_date`
- `build_treasury_panel()` — subtitle shows data date in `YYYY-MM-DD` format
- `build_economy_panel()` — subtitle shows date in `Mon YYYY` format
- `make_header()` — shows errors, rate limit warnings, time, quit hint
- `build_layout()` — Rich Layout: header → indices → equities → crypto → bottom split (treasury | economy)
- `key_listener()` — background thread, `tty.setcbreak()` for 'q' detection

**Visual styling:** All panel borders `grey70`, titles `[bold grey70]`, subtitles `[grey46]`. Neutral values (prices, volume, yields, economy) in cyan; changes green/red.

### `app.py`
- `main()`:
  - Loads `.env` manually (no python-dotenv dependency)
  - Saves original termios settings, restores on exit
  - Suppresses urllib3 SSL warning for LibreSSL
  - Shows dashboard immediately with blank values
  - Kicks off `_init_market` thread (market status → snapshots → crypto → WS feeds)
  - Kicks off `fetch_economy_data` thread (3 calls spaced 15s apart)
  - Optionally kicks off YTD close fetch after economy finishes (if ytd% column configured)
  - **Delayed grace period:** delayed (non-realtime) feeds continue for 15 minutes after market close (`DELAYED_GRACE = 15 * 60`). Real-time feeds stop immediately on close.
  - `_check_market_status()` — polls market status every 60s, parses `indicesGroups` into `state.indices_group_status`
  - `_all_realtime()` — returns True if all entitled feeds are real-time (determines if grace period needed)
  - **Crypto polling:** Starter plan (real-time snapshots) polls 24/7. Basic plan (end-of-day aggs) only polls while US equities market is active.
  - `eq_active` flag — True when market open OR in delayed grace period; gates equities/indices REST polling
  - Handles market open/close transitions (start/stop WS feeds)
  - Main loop renders at 2fps from shared `DashboardState`

## API Compatibility

| Feature | Plan Needed | Client Call | Key Gotchas |
|---------|------------|-------------|-------------|
| Stock/index snapshots | Stocks/Indices Starter | `list_universal_snapshots(ticker_any_of=<list>)` | Must pass Python list, NOT comma-separated string |
| Stock WS second aggs | Stocks Starter | `WebSocketClient(Feed.Delayed, Market.Stocks)` → `A.*` | `Feed.StarterFeed` returns "not authorized"; must use `Feed.Delayed` |
| Index WS values | Indices Starter | `WebSocketClient(Feed.Delayed, Market.Indices)` → `V.*` | Sub-second updates |
| Crypto snapshots | Currencies Starter | `list_universal_snapshots(ticker_any_of=<list>)` | Unlimited calls, real-time data |
| Crypto daily aggs | Currencies Basic (Free) | `get_aggs(ticker, 1, "day", from, to)` | 5 calls/min limit; snapshots return NOT_ENTITLED |
| Treasury yields | Free | `list_treasury_yields(sort="date.desc", limit=1)` | Use `next(iter())` not `list()` — pagination burns rate limit |
| Labor market | Free | `list_labor_market_indicators(sort="date.desc", limit=1)` | Field is `labor_force_participation_rate` not `participation_rate` |
| Inflation | Free | `list_inflation(sort="date.desc", limit=1)` | `cpi_year_over_year` and `pce` are None; use raw `cpi` and `cpi_core` |
| Market status | Free | `get_market_status()` | Returns `market="open"/"closed"`; `indicesGroups` can be unreliable |

## Key Design Decisions

- **Never blank data on failure** — state lists only overwritten when new data is fetched successfully
- **Background-first startup** — dashboard renders immediately, all API calls happen in background threads
- **Rate limit awareness** — crypto enforces `num_tickers * 12s` minimum interval; economy spaces calls 15s apart; REST polls back off 4x on 429
- **WS as enhancement, REST as baseline** — WS provides per-second updates; REST polls on configured interval as safety net
- **Delayed grace period** — non-realtime (delayed) feeds continue updating for 15 minutes after market close to capture final settlement prices; real-time feeds stop immediately
- **Plan-aware crypto polling** — Starter plan (real-time snapshots) polls 24/7; Basic plan (end-of-day aggs) stops when US equities market closes since no new data is available
- **Per-section status** — each market panel shows its own freshness and "market closed" status in the subtitle
- **No python-dotenv dependency** — `.env` loaded with simple manual parser in `main()`
- **Terminal safety** — original termios saved at startup, restored in `finally` block to prevent broken terminal on Ctrl+C
- **Path resolution** — all config/data files resolve relative to `PROJECT_ROOT` (parent of `fintra/` package dir), not the package itself
- **Unified visual styling** — light grey (`grey70`) borders and titles, darker grey (`grey46`) subtitles, cyan for neutral values, green/red for changes

## Known Bugs

- Economy "loading..." can persist ~45s on startup due to 15s spacing between API calls
- `indicesGroups` from `get_market_status()` can report groups as "open" when indices are not actually updating; indices use `market_is_open` (overall US market status) instead

## TODO

- **Watchlist switcher** — press `l` to show a list of available watchlist files, select one to swap the active view; support multiple `.txt` watchlists in the project directory
- **CLI install** — add `pyproject.toml` with a `[project.scripts]` entry so `pip install .` creates a `fintra` command runnable from anywhere
