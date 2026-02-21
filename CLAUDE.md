# Fintra — Implementation Reference

## Git Commits

Do NOT include `Co-Authored-By` trailers in commit messages. Attribution is in the README.

## Linting

`ruff` is configured via `ruff.toml`. Run `ruff check fintra/` to catch unused imports, undefined names, etc. Rules: F (pyflakes), E/W (pycodestyle) minus E501 (line length).

## File Layout

```
Fintra/                        # project root
├── README.md
├── CLAUDE.md
├── config.ini                 # refresh intervals, column config
├── ruff.toml                  # ruff linter config
├── screenshot.png             # dashboard screenshot for README
├── watchlists/                # ticker watchlist files (.txt), press `l` to cycle
│   └── watchlist.txt          # default watchlist
├── requirements.txt           # massive, rich
├── setup.sh                   # creates venv, installs deps
├── .env                       # MASSIVE_API_KEY=... (gitignored)
├── .env.example               # template for users (no real key)
├── .plans.json                # cached API plan detection (gitignored)
├── .econ_cache.json           # cached economy data, invalidated after market close (gitignored)
├── .gitignore
└── fintra/                    # Python package
    ├── __init__.py            # version, docstring
    ├── __main__.py            # python -m fintra entry point
    ├── constants.py           # yield/economy fields, column defs, paths
    ├── config.py              # Config dataclass, parse_config, parse_interval, parse_watchlist
    ├── state.py               # DashboardState dataclass
    ├── plans.py               # PlanInfo dataclass, probe/load/save plans
    ├── provider.py            # MassiveProvider — sole module importing from massive SDK
    ├── formatting.py          # fmt_price, fmt_change, fmt_pct, fmt_volume, fmt_yield_val
    ├── data.py                # Data fetching orchestration: market, crypto, economy, YTD, caching
    ├── websocket.py           # WS streaming: start/stop feeds, _update_ticker, message handler
    ├── ui.py                  # Table/panel builders, layout, header, key_listener
    └── app.py                 # main() orchestration loop
```

Run with: `python -m fintra`

## Module Architecture

### `constants.py`
- `PROJECT_ROOT` — resolved via `os.path.dirname(os.path.dirname(__file__))`, all config/data files are relative to this
- `CONFIG_PATH`, `WATCHLISTS_DIR`, `DEFAULT_WATCHLIST`, `PLANS_PATH`, `ECON_CACHE_PATH`
- `ALL_YIELD_FIELDS`, `DEFAULT_YIELD_KEYS` — treasury yield maturity mappings
- `ALL_ECONOMY_FIELDS`, `DEFAULT_ECONOMY_KEYS` — economy indicator definitions (label, API attr, format type)
- `EQUITY_COLUMNS`, `INDEX_COLUMNS`, `CRYPTO_COLUMNS` — column definitions per section (symbol column is not included — it is always prepended automatically by the UI)
- `SYMBOL_MIN_WIDTH` — per-section min-width for the auto-prepended symbol column (`equity: 6`, `index: 8`, `crypto: 10`)
- `DEFAULT_EQUITY_COLS`, `DEFAULT_INDEX_COLS`, `DEFAULT_CRYPTO_COLS` — default column lists (no `symbol` or `name`)

### `config.py`
- `parse_interval()` — converts `10s`/`1m`/`1h`/`1d` to seconds
- `Config` dataclass — refresh/economy intervals + column lists per section
- `parse_config()` — reads config.ini into `Config`, validates column names against available columns
- `_parse_col_list()` — silently strips `symbol` and `name` from user-provided column lists (symbol is always prepended by UI)
- `parse_watchlist(path)` — reads a watchlist file into `{equities: [], crypto: [], indices: [], treasury: [], economy: [], equity_groups: []}`. Within `[equities]`, lines starting with `## ` define named sub-groups. The flat `equities` list always contains every ticker regardless of grouping. `equity_groups` is a list of `(group_name, [tickers])` tuples preserving order.
- `validate_watchlist(path)` — quick check for valid `[section]` headers
- `list_watchlists()` — scans `WATCHLISTS_DIR` for valid `.txt` watchlist files, returns sorted absolute paths

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
  - `switch_watchlist` — flag set by `l` key to trigger watchlist cycle
  - `watchlist_error`, `active_watchlist_name` — watchlist status for header display
  - `market_stale`, `economy_stale`, `market_error`, `economy_error` — status tracking

### `plans.py`
- `PlanInfo` dataclass — detected API plan per asset class (stocks, indices, currencies)
  - Properties: `stocks_has_snapshots`, `stocks_has_ws`, `stocks_realtime`, `indices_has_snapshots`, `indices_has_ws`, `indices_realtime`, `currencies_has_snapshots`, `currencies_has_ws`, `currencies_unlimited`
- `_probe_plans(provider)` — calls `provider.probe_snapshots()` to detect plan tier
- `load_plans(provider)` / `save_plans()` — cached in `.plans.json`

### `provider.py`
- **Only module that imports from `massive`** — all SDK types (`RESTClient`, `WebSocketClient`, `Feed`, `Market`, message models) are isolated here
- `MassiveProvider` class — wraps the Massive SDK; all other modules receive a provider instance and work with plain dicts
  - `fetch_snapshots(tickers)` → list of flat dicts (`ticker`, `name`, `last`, `open`, `high`, `low`, `volume`, `change`, `change_pct`, `prev_close`)
  - `fetch_aggs(ticker, multiplier, timespan, from_date, to_date)` → list of bar dicts (`open`, `high`, `low`, `close`, `volume`, `timestamp`)
  - `fetch_market_status()` → `{"market_is_open": bool, "indices_groups": dict}`
  - `fetch_treasury_yields()` → dict with `yield_*` keys + `"date"`
  - `fetch_labor_market()` → dict with `unemployment_rate`, `participation_rate`, `avg_hourly_earnings`, `date`
  - `fetch_inflation(limit=13)` → list of dicts with `cpi`, `cpi_core`, `date`
  - `fetch_ticker_details(ticker)` → `{"market_cap": float|None}`
  - `probe_snapshots(ticker)` → bool (used by plans.py for plan detection)
  - `create_ws_feed(market, feed_type, tickers, on_update)` → `WsFeed` with `.run()` / `.close()`
- `WsFeed` class — thin wrapper around `WebSocketClient`; `.run()` dispatches parsed messages via `on_update(ticker, price, extras_dict)` callback
- `_normalize_snapshot()` — static method; converts SDK snapshot objects to flat dicts. Extracts `name` from the snapshot object (API-provided display name, falls back to ticker). Extracts extended hours fields: `pre_market_change`, `pre_market_change_pct`, `after_hours_change`, `after_hours_change_pct`, `regular_change`, `regular_change_pct` from the session's early/late/regular trading attributes

### `formatting.py`
- `fmt_price(val, large)` — returns cyan `Text`; uses comma separator when `large=True`
- `fmt_change(val, large)` — returns green/red `Text` with +/- sign
- `fmt_pct(val)` — returns green/red `Text` with % suffix
- `fmt_volume(val)` — returns cyan `Text` with B/M/K suffixes
- `fmt_market_cap(val)` — returns cyan `Text` with T/B/M suffixes
- `fmt_yield_val(val)` — returns cyan `Text` with % suffix
- `fmt_ext_chg(val, large)` — returns dim parenthesized change text for extended hours, e.g. ` (+1.50)`; returns None if val is None
- `fmt_ext_pct(val)` — returns dim parenthesized change percent text for extended hours, e.g. ` (+0.85%)`; returns None if val is None

### `data.py`
- Does **not** import from `massive` — all API calls go through `provider: MassiveProvider`
- `_normalize_crypto_agg()` — converts crypto agg dict + previous close dict to flat dict (uses `dict.get()`)
- `_fetch_via_aggs(provider, ...)` — fallback for Basic plan: calls `provider.fetch_aggs()` instead of snapshots
- `_market_lock` — `threading.Lock()`, non-blocking acquire prevents overlapping threaded fetches
- `fetch_market_data(provider, ...)` — calls `provider.fetch_snapshots()` (Starter+) or aggs fallback (Basic). Reads `prev_close` from returned dicts. Names come from the API snapshot's `name` field. Guarded by `_market_lock`; skips if another fetch is already running.
- `fetch_crypto_data(provider, ...)` — calls `provider.fetch_snapshots()` (Starter) or `provider.fetch_aggs()` (Basic). Lock prevents overlapping fetches. Atomic swap on full success, merge on partial. Stores `crypto_data_date` from agg timestamp (UTC) for basic plan.
- `fetch_ytd_closes(provider, ...)` — calls `provider.fetch_aggs()`, reads `agg["close"]`
- `fetch_ticker_details(provider, ...)` — calls `provider.fetch_ticker_details()`
- `_fetch_with_timeout()` — wraps callable in thread with timeout to prevent hanging on 429 retries
- `_fetch_economy_endpoint()` — retry wrapper for economy endpoints
- `_last_market_close()` — returns Unix timestamp of the most recent NYSE close (4 PM ET), skipping weekends
- `_load_econ_cache()` / `_save_econ_cache()` — disk cache for economy data in `.econ_cache.json`, invalidated after market close
- `fetch_economy_data(provider, ...)` — checks cache first; if stale, calls `provider.fetch_treasury_yields()`, `.fetch_labor_market()`, `.fetch_inflation()` spaced 15s apart

### `websocket.py`
- Does **not** import from `massive` — WS feeds created via `provider.create_ws_feed()`
- `_connected_feeds` / `_connected_lock` — set + lock tracking which feeds are currently connected; `_set_connected()` updates the set and `state.ws_connected` atomically
- `WsFeedHandle` — handle for a WS feed with automatic reconnection; holds a `_stopped` flag and a lock-protected `_current_feed` reference. `.close()` sets the stop flag and closes the current feed.
- `_update_ticker()` — updates a ticker dict in state with new price, recalculates change/change_pct from `prev_closes`, updates high/low/volume with min/max logic. Sets `_flash_until` and `_flash_up` when change value differs from previous
- `_run_feed_with_reconnect(handle, provider, ...)` — reconnection loop: creates feed via `provider.create_ws_feed()`, runs it, and on disconnect backs off exponentially (1s → 2s → 4s → ... → 60s cap) before reconnecting. Exits when `handle.stopped` or `state.quit_flag` is set. Checks stop flag in 0.5s increments during backoff for responsive shutdown.
- `start_ws_feeds(provider, ...)` — creates a `WsFeedHandle` per entitled asset class, starts `_run_feed_with_reconnect` in a daemon thread for each. Returns list of handles.
- `stop_ws_feeds(feeds)` — calls `.close()` on each `WsFeedHandle`, which stops the reconnection loop and closes the active feed

### `ui.py`
- `_get_ext_hours(item)` — returns `(ext_change, ext_change_pct, label)` where label is `"AH"` or `"PM"`, or all Nones if no extended hours data
- `_apply_flash(result, item)` — if `_flash_until` is in the future, overrides Text style with bold white on dark_green/dark_red background
- `_regular_close(item)` — computes regular session close from `prev_close + regular_change`; returns None if fields missing
- `_cell_value()` — returns formatted cell value for a column key + data item. Does not handle `symbol` or `name` (those are prepended by the table builders). "open_close" toggles between open/close based on `market_is_open`. When market is closed and extended hours data is present: "last" shows regular close with extended price in dim parens, "chg"/"chg%" show regular change with extended change in dim parens. Flash background applied to "chg"/"chg%" when `_flash_until` is active.
- `_build_market_table()` — generic Rich Table builder from column config. Always prepends a symbol column (no header) using `item["ticker"]` with `I:`/`X:` prefixes stripped for display. Accepts `symbol_width` parameter.
- `_build_grouped_equities_table()` — equities table builder with sub-group support. When `equity_groups` is provided, inserts a padding row and a dim bold group name row before each group's tickers. Symbol column prepended same as `_build_market_table`.
- `_data_freshness(plan_tier, market)` — returns freshness label: "real-time" (advanced or crypto starter), "15m delayed" (starter), "end of day" (basic)
- `_format_date(date_val, fmt)` — date formatter with configurable strftime format
- `_market_subtitle(freshness, state, streaming)` — builds subtitle: freshness + "streaming" (if WS) + "stale" (if stale) + "market closed" (if closed)
- `build_equities_table()` — accepts optional `equity_groups` param; dispatches to `_build_grouped_equities_table` when groups exist, otherwise `_build_market_table`
- `build_indices_table()` — section Panel with freshness + market closed subtitle
- `build_crypto_table()` — starter: "real-time, polled Xs ago"; basic: shows `crypto_data_date`
- `build_treasury_panel()` — subtitle shows data date in `YYYY-MM-DD` format
- `build_economy_panel()` — subtitle shows date in `Mon YYYY` format
- `make_header()` — shows active watchlist name, errors, rate limit warnings, time, `[l] List` + `[q] Quit` hints
- `build_layout()` — Rich Layout: header → indices → equities → crypto → bottom split (treasury | economy). Extracts `equity_groups` from watchlist and passes to equities builder. Adjusts equities panel height to account for group name rows and padding rows.
- `key_listener()` — background thread, `tty.setcbreak()` for 'q' (quit) and 'l' (cycle watchlist) detection

**Visual styling:** All panel borders `grey70`, titles `[bold grey70]`, subtitles `[grey46]`. Neutral values (prices, volume, yields, economy) in cyan; changes green/red. Group names in dim bold.

### `app.py`
- Does **not** import from `massive` — creates `MassiveProvider` and passes it to all modules
- `main()`:
  - Loads `.env` manually (no python-dotenv dependency)
  - Creates `MassiveProvider(api_key)` — single provider instance shared across all modules
  - Saves original termios settings, restores on exit
  - Suppresses urllib3 SSL warning for LibreSSL
  - Shows dashboard immediately with blank values
  - Kicks off `_init_market` thread (market status → snapshots → crypto → WS feeds)
  - Kicks off `fetch_economy_data` thread (3 calls spaced 15s apart)
  - Optionally kicks off YTD close fetch after economy finishes (if ytd% column configured)
  - **Delayed grace period:** delayed (non-realtime) feeds continue for 15 minutes after market close (`DELAYED_GRACE = 15 * 60`). Real-time feeds stop immediately on close.
  - `_check_market_status()` — calls `provider.fetch_market_status()`, reads dict keys into state
  - `_all_realtime()` — returns True if all entitled feeds are real-time (determines if grace period needed)
  - **Non-blocking data fetches:** all `fetch_market_data` and `fetch_crypto_data` calls run in daemon threads; `_market_lock` / `_crypto_lock` prevent overlapping fetches. A hung API request cannot freeze the render loop.
  - **Crypto polling:** Starter plan polls at `effective_refresh` interval; Basic plan (end-of-day aggs) polls hourly (`3600s`) since data only changes once per day. Both gated by `last_crypto_fetch` timestamp.
  - `eq_active` flag — True when market open OR in delayed grace period; gates equities/indices REST polling
  - **Rate-limit backoff** — `effective_refresh` checked every iteration; backs off to `min(interval * 4, 120s)` when `state.rate_limited` is set, resets when a fetch succeeds
  - Handles market open/close transitions (start/stop WS feeds)
  - Handles watchlist switch: stops WS, resets state, re-kicks data fetches
  - Main loop renders at 2fps from shared `DashboardState`

## API Compatibility

These are the underlying Massive SDK calls used inside `provider.py`. No other module calls these directly.

| Feature | Plan Needed | SDK Call (in provider.py) | Key Gotchas |
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

- **Provider isolation** — only `provider.py` imports from `massive`; all other modules work with plain dicts. `MassiveProvider` translates SDK types → dicts; no retry logic, caching, or state mutation inside the provider
- **API-sourced display names** — ticker names come from the API snapshot's `name` field (extracted in `_normalize_snapshot`), not from a hardcoded mapping. The UI symbol column strips `I:`/`X:` prefixes from raw tickers for display.
- **Symbol column always present** — the symbol column is automatically prepended by the table builders, cannot be removed via config. `symbol` and `name` are silently stripped from user-provided column lists.
- **Equity sub-groups** — `## Group Name` headers in the `[equities]` section of watchlist files create named groups. `parse_watchlist()` returns both the flat `equities` list (for API/WS consumers) and an `equity_groups` list of `(name, [tickers])` tuples (for UI only). Groups render with a padding row and dim bold title above each group's tickers.
- **Never blank data on failure** — state lists only overwritten when new data is fetched successfully
- **Background-first startup** — dashboard renders immediately, all API calls happen in background threads
- **Rate limit awareness** — crypto enforces `num_tickers * 12s` minimum interval; economy spaces calls 15s apart; REST polls back off 4x on 429
- **WS reconnection with backoff** — WS feeds automatically reconnect on disconnect with exponential backoff (1s → 60s cap). Each feed runs in a `_run_feed_with_reconnect` loop managed by a `WsFeedHandle`; calling `.close()` on the handle stops reconnection and closes the active feed. `_connected_feeds` set tracks per-feed connection state so `state.ws_connected` is accurate across multiple feeds.
- **WS as enhancement, REST as baseline** — WS provides per-second updates; REST polls on configured interval as safety net. All REST fetches run in daemon threads with non-blocking locks so a hung API call cannot freeze the main render loop.
- **Delayed grace period** — non-realtime (delayed) feeds continue updating for 15 minutes after market close to capture final settlement prices; real-time feeds stop immediately
- **Plan-aware crypto polling** — Starter plan (real-time snapshots) polls at `effective_refresh` interval; Basic plan (end-of-day aggs) polls hourly and only while US equities market is active since data only changes once per day
- **Per-section status** — each market panel shows its own freshness and "market closed" status in the subtitle
- **No python-dotenv dependency** — `.env` loaded with simple manual parser in `main()`
- **Terminal safety** — original termios saved at startup, restored in `finally` block to prevent broken terminal on Ctrl+C
- **Path resolution** — all config/data files resolve relative to `PROJECT_ROOT` (parent of `fintra/` package dir), not the package itself
- **Extended hours data** — when market is closed, equities show regular session values as main display with pre-market or after-hours changes in dim parentheses. After-hours takes priority over pre-market. Regular session close computed from `prev_close + regular_change`. Graceful fallback: if extended hours fields are None, display is unchanged
- **Flash on change** — `_flash_until` timestamp + `_flash_up` direction flag set on ticker dicts by both WS updates and REST fetches. UI checks flash state on "chg"/"chg%" columns and overrides style with `bold white on dark_green/dark_red` for ~1 second (2 render cycles at 2fps). Threshold of 0.001 prevents floating-point noise from triggering flashes on REST updates
- **Unified visual styling** — light grey (`grey70`) borders and titles, darker grey (`grey46`) subtitles, cyan for neutral values, green/red for changes

## Known Bugs

- Economy "loading..." can persist ~45s on startup due to 15s spacing between API calls
- `indicesGroups` from `get_market_status()` can report groups as "open" when indices are not actually updating; indices use `market_is_open` (overall US market status) instead

## TODO

- **Period change columns** — 3mo chg %, 1yr chg %, YTD chg % for equities and indices; also 1yr high, 1yr low, YTD high, YTD low; check if Massive API provides these directly before calculating manually from historical aggs
