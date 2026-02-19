# Fintra — Terminal Market Dashboard

A real-time terminal dashboard for equities, crypto, indices, and economic data. Built with the [Massive.com](https://massive.com) (Polygon.io) API and rendered with [Rich](https://github.com/Textualize/rich).

Stocks and indices stream per-second via WebSocket. Crypto polls on a rate-limited interval. Treasury yields and economic indicators load in the background on startup.

All data is **15-minute delayed** on Starter plans.

## Setup

```bash
git clone <repo-url> && cd Fintra
bash setup.sh
```

Create a `.env` file with your API key (this file is gitignored):

```
MASSIVE_API_KEY=your_key_here
```

Then run:

```bash
source venv/bin/activate
python fintra.py
```

The dashboard appears immediately. Data populates in the background as API calls complete.

## Massive.com Plans

Fintra is designed around these plan tiers:

| Data | Plan | Method |
|------|------|--------|
| Equities | Stocks Starter ($29/mo) | REST snapshots + WS second aggregates |
| Indices | Indices Starter | REST snapshots + WS index values |
| Crypto | Currencies Free | REST daily aggregates (5 calls/min) |
| Treasury / Economy | Free | REST (5 calls/min, spaced 15s apart) |

You can use lower plans — the dashboard gracefully handles missing entitlements and rate limits.

## Configuration

### config.ini

```ini
[dashboard]
# How often stock/index REST data refreshes (WS streams independently)
refresh_interval = 10s    # 10s, 1m, 5m, 15m, 1h

# How often economy data refreshes (changes at most daily)
economy_interval = 1d     # 1h, 6h, 1d
```

Time units: `s` (seconds), `m` (minutes), `h` (hours), `d` (days).

### watchlist.txt

One ticker per line, organized by section:

```
[equities]
AAPL
MSFT
NVDA

[crypto]
X:BTCUSD
X:ETHUSD

[indices]
I:SPX
I:DJI
I:NDX
I:VIX
```

**Ticker format:**
- Equities: bare symbol (`AAPL`, `MSFT`, `NVDA`)
- Crypto: `X:` prefix (`X:BTCUSD`, `X:ETHUSD`)
- Indices: `I:` prefix (`I:SPX`, `I:VIX`, `I:DJI`, `I:NDX`)
- Blank lines and `#` comments are ignored

**Crypto rate limiting:** The free currencies plan allows 5 API calls/min. Fintra automatically throttles crypto polling based on ticker count (minimum 15s between refreshes, ~12s per ticker). Adding more than 5 crypto tickers will increase the polling interval accordingly.

## Dashboard Sections

| Section | Data Shown | Update Method |
|---------|-----------|---------------|
| **Equities** | Price, change, change%, open, high, low, volume | WebSocket streaming (~1s) |
| **Indices** | Price, change, change% | WebSocket streaming (sub-second) |
| **Crypto** | Price, change, change% | REST polling (rate-limited) |
| **Treasury Yields** | 1M, 3M, 1Y, 2Y, 5Y, 10Y, 30Y | REST on startup, then per `economy_interval` |
| **Economy** | Unemployment, participation rate, avg hourly wage, CPI, core CPI | REST on startup, then per `economy_interval` |

Each section title shows its data status (e.g. "15min delayed, streaming" or "polled 24s ago"). Treasury and economy panels show the date of the most recent data point.

## Controls

| Key | Action |
|-----|--------|
| `q` | Quit cleanly |
| `Ctrl+C` | Quit (fallback) |

## Architecture

Single-file Python app (`fintra.py`, ~850 lines):

1. Dashboard renders immediately with blank values
2. Background threads fetch REST data (market snapshots, crypto aggs, economy)
3. WebSocket feeds start for stocks (second aggregates) and indices (index values) on `Feed.Delayed`
4. Main loop renders the Rich layout at 2fps from shared `DashboardState`
5. REST continues polling on `refresh_interval` as a safety net alongside WS
6. Economy data fetches are spaced 15s apart to avoid 429 rate limits

## Troubleshooting

- **Crypto flickering or blank:** Rate limit exceeded. Reduce crypto tickers or increase `refresh_interval`.
- **Economy sections showing "loading..." forever:** Economy endpoints may be rate-limited. They space calls 15s apart and will populate within ~45s of startup if the API allows.
- **"Rate limited" in header:** Fintra auto-backs off to 4x the configured interval (max 120s) and recovers when limits clear.
- **Terminal broken after exit:** Should not happen (terminal settings are saved/restored), but run `reset` if it does.
