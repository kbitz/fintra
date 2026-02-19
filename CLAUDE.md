# Fintra — Implementation Reference

## File Layout

| File | Purpose |
|------|---------|
| `fintra.py` | Single-file app (~850 lines), all logic |
| `config.ini` | Refresh intervals (10s market, 1d economy) |
| `watchlist.txt` | Ticker lists by section (equities, crypto, indices) |
| `.env` | `MASSIVE_API_KEY=...` (gitignored) |
| `requirements.txt` | `massive`, `rich` |
| `setup.sh` | Creates venv, installs deps |

## Architecture (fintra.py)

Components in order:

1. **Constants** — `CONFIG_PATH`, `WATCHLIST_PATH`, `DISPLAY_NAMES`, `YIELD_FIELDS`
2. **`parse_interval()`** — converts `10s`/`1m`/`1h`/`1d` to seconds
3. **`parse_config()`** — reads config.ini, returns `(refresh_seconds, economy_seconds)`
4. **`parse_watchlist()`** — reads watchlist.txt into `{equities: [], crypto: [], indices: []}`
5. **`DashboardState` dataclass** — shared mutable state:
   - `equities`, `crypto`, `indices` — lists of flat dicts with `ticker`, `name`, `last`, `change`, `change_pct`, `open`, `high`, `low`, `volume`
   - `treasury`, `labor`, `inflation` — dicts of latest values + `date` key
   - `prev_closes` — cached previous session closes for WS change calc
   - `market_updated`, `crypto_updated`, `economy_updated` — timestamps
   - `market_is_open`, `ws_connected`, `rate_limited`, `quit_flag` — flags
6. **Formatting helpers** — `fmt_price`, `fmt_change`, `fmt_pct`, `fmt_volume`, `fmt_yield_val`
7. **`normalize_snapshot()`** — converts REST snapshot to flat dict; tries `session.close`, then `last_trade.price`, then `last_quote` midpoint, then top-level `price`/`value`
8. **`fetch_market_data()`** — REST: `list_universal_snapshots(ticker_any_of=<list>)` for stocks+indices. Only overwrites state if data was returned. Caches `prev_closes` by deriving `close - change`.
9. **`fetch_crypto_data()`** — REST: `get_aggs(ticker, 1, "day", 3_days_ago, today)` per ticker. Rate-limited internally: `min_interval = max(num_tickers * 12, 15)` seconds. 1s delay between individual ticker calls. Never blanks existing data on failure.
10. **`_fetch_with_timeout()`** — wraps a callable in a thread with configurable timeout (default 10s) to prevent hanging on 429 retry loops
11. **`fetch_economy_data()`** — 3 sequential REST calls with 15s delays between them:
    - `list_treasury_yields` → `state.treasury` (yield curves + date)
    - `list_labor_market_indicators` → `state.labor` (unemployment, participation, avg hourly earnings + date)
    - `list_inflation` → `state.inflation` (CPI, core CPI + date)
    - Uses `next(iter(...))` NOT `list()` — `list()` triggers pagination and burns the entire rate limit
12. **`start_ws_feeds()`** — launches background daemon threads:
    - Stocks: `WebSocketClient(Feed.Delayed, Market.Stocks)` subscribing to `A.<ticker>` (second aggs)
    - Indices: `WebSocketClient(Feed.Delayed, Market.Indices)` subscribing to `V.<ticker>` (index values)
    - No crypto WS (free plan not entitled)
    - `_update_ticker()` helper finds matching dict in state list and updates `last`, recalculates `change`/`change_pct` from `prev_closes`, updates `high`/`low`/`volume`
13. **Table builders** — each returns a `rich.panel.Panel`:
    - `build_equities_table` — 8 columns (Symbol, Last, Chg, Chg%, Open, High, Low, Vol)
    - `build_crypto_table` — 4 columns, title shows "polled Xs ago"
    - `build_indices_table` — 4 columns
    - `build_treasury_panel` — 2-column pairs layout (short maturities left, long right)
    - `build_economy_panel` — single column key-value
    - Section titles show data freshness (streaming/polled/date)
14. **`make_header()`** — market open/closed status from `get_market_status()` API
15. **`build_layout()`** — Rich Layout: header (3 rows) + equities + crypto + indices + bottom split (treasury | economy)
16. **`key_listener()`** — background thread, `tty.setcbreak()` for 'q' detection
17. **`main()`**:
    - Loads `.env` manually (no python-dotenv dependency)
    - Saves original termios settings, restores on exit (fixes terminal echo after Ctrl+C)
    - Suppresses urllib3 SSL warning for LibreSSL
    - Shows dashboard immediately with blank values
    - Kicks off `_init_market` thread (market status → snapshots → crypto → WS feeds)
    - Kicks off `fetch_economy_data` thread (3 calls spaced 15s apart)
    - Main loop: REST polls on `refresh_interval`, crypto polls via rate-limited `fetch_crypto_data`, economy polls on `economy_interval`, renders at 2fps

## API Compatibility

| Feature | Plan Needed | Client Call | Key Gotchas |
|---------|------------|-------------|-------------|
| Stock/index snapshots | Stocks/Indices Starter | `list_universal_snapshots(ticker_any_of=<list>)` | Must pass Python list, NOT comma-separated string |
| Stock WS second aggs | Stocks Starter | `WebSocketClient(Feed.Delayed, Market.Stocks)` → `A.*` | `Feed.StarterFeed` returns "not authorized"; must use `Feed.Delayed` |
| Index WS values | Indices Starter | `WebSocketClient(Feed.Delayed, Market.Indices)` → `V.*` | Sub-second updates |
| Crypto daily aggs | Currencies Free | `get_aggs(ticker, 1, "day", from, to)` | 5 calls/min limit; snapshots return NOT_ENTITLED |
| Treasury yields | Free | `list_treasury_yields(sort="date.desc", limit=1)` | Use `next(iter())` not `list()` — pagination burns rate limit |
| Labor market | Free | `list_labor_market_indicators(sort="date.desc", limit=1)` | Field is `labor_force_participation_rate` not `participation_rate` |
| Inflation | Free | `list_inflation(sort="date.desc", limit=1)` | `cpi_year_over_year` and `pce` are None; use raw `cpi` and `cpi_core` |
| Market status | Free | `get_market_status()` | Returns `market="open"/"closed"` |

## Key Design Decisions

- **Never blank data on failure** — state lists only overwritten when new data is fetched successfully
- **Background-first startup** — dashboard renders immediately, all API calls happen in background threads
- **Rate limit awareness** — crypto enforces `num_tickers * 12s` minimum interval; economy spaces calls 15s apart; REST polls back off 4x on 429
- **WS as enhancement, REST as baseline** — WS provides per-second updates; REST polls on configured interval as safety net
- **No python-dotenv dependency** — `.env` loaded with simple manual parser in `main()`
- **Terminal safety** — original termios saved at startup, restored in `finally` block to prevent broken terminal on Ctrl+C
