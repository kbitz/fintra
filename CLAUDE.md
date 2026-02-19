# Fintra — Implementation Plan & Status

## Current Status

**All files created, venv installed, tested with real API key.**

| File | Status | Notes |
|------|--------|-------|
| `fintra.py` | Done | ~730 lines, REST + WebSocket hybrid |
| `config.ini` | Done | 10s market, 1d economy defaults |
| `watchlist.txt` | Done | AAPL/MSFT/NVDA, BTC/ETH, SPX/DJI/NDX/VIX |
| `requirements.txt` | Done | massive, rich |
| `setup.sh` | Done | Executable, creates venv + installs deps |
| `README.md` | Done | Setup, config, usage docs |
| `.gitignore` | Done | venv/, .env, __pycache__/ |

## Architecture (fintra.py)

1. **Constants** — paths, display names, yield field mappings
2. **`parse_interval()`** / **`parse_config()`** — reads config.ini, supports `10s`/`1m`/`1h`/`1d`
3. **`parse_watchlist()`** — reads watchlist.txt into `{equities: [], crypto: [], indices: []}`
4. **`DashboardState` dataclass** — all data, timestamps, prev_closes cache, ws_connected flag
5. **Formatting helpers** — `fmt_price`, `fmt_change`, `fmt_pct`, `fmt_volume`, `fmt_yield_val`
6. **`normalize_snapshot()`** — converts REST snapshot objects to flat dicts
7. **`fetch_market_data()`** — REST: `list_universal_snapshots` for stocks/indices (as list), `get_aggs` for crypto with change calc from 3-day range
8. **`fetch_economy_data()`** — REST with 10s timeout wrapper: treasury, labor, inflation
9. **WebSocket streaming** — `start_ws_feeds()` launches background threads:
   - Stocks: `A.*` second aggregates on `Feed.Delayed`
   - Indices: `V.*` index values on `Feed.Delayed`
   - Crypto: REST-only (WS not entitled on free plan)
10. **Table builders** — equities, crypto, indices, treasury, economy panels
11. **`make_header()`** — market status (via `get_market_status()` API), WS/REST indicator, refresh time
12. **`build_layout()`** — Rich Layout: header + 3 market sections + bottom split (treasury | economy)
13. **`key_listener()`** — background thread using tty/termios for 'q' quit
14. **`main()`** — REST baseline fetch → start WS feeds → Live rendering loop with REST fallback polling

## Data Flow

```
Startup:
  REST: list_universal_snapshots → equities + indices (+ cache prev_closes)
  REST: get_aggs (3-day) → crypto with change calculation
  REST: treasury/labor/inflation (with 10s timeout for 429 protection)
  WS: start 2 background threads (stocks + indices)

Running:
  WS threads update state.equities/indices in real-time (per-second)
  REST polls on configured interval as safety net
  Economy data fetched once at startup (1d interval)
  Rich Live renders layout at 2fps from shared state
```

## API Plan Compatibility

| Feature | Plan | Method |
|---------|------|--------|
| Stock snapshots | Stocks Starter ($29) | `list_universal_snapshots` (list param, not string) |
| Index snapshots | Indices Starter | `list_universal_snapshots` |
| Stock WS second aggs | Stocks Starter | `WebSocketClient(Feed.Delayed, Market.Stocks)` → `A.*` |
| Index WS values | Indices Starter | `WebSocketClient(Feed.Delayed, Market.Indices)` → `V.*` |
| Crypto aggs | Currencies Free | `get_aggs` (daily bars) |
| Crypto WS | NOT available | Free plan, no WS entitlement |
| Treasury/Labor/Inflation | Unknown plan | REST with rate limit protection (5 calls/min) |

## Key Findings from Testing

- `list_universal_snapshots` requires a **list**, not comma-separated string (bug in original code)
- Crypto snapshots return `NOT_ENTITLED` — must use `get_aggs` fallback
- Economy endpoints hit 429 rate limits aggressively — wrapped with 10s timeout threads
- WS `Feed.StarterFeed` returns "not authorized" — must use `Feed.Delayed` instead
- WS second aggregates (`A.*`) fire every ~1s during market hours
- WS index values (`V.*`) fire sub-second
- Market status from `get_market_status()` API (replaces manual UTC offset calc)

## Verification

```bash
cd "/Users/kb/Dropbox (Personal)/Dev/Fintra"
source venv/bin/activate
export MASSIVE_API_KEY="your_key"
python fintra.py
```

Confirm: header shows "WS" green, stocks/indices update every second, crypto shows daily data, 'q' quits.
