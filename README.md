# Fintra — Terminal Market Dashboard

A real-time terminal dashboard for equities, crypto, indices, and economic data. Powered by the Massive.com API and rendered with Rich.

## Prerequisites

- Python 3.9+
- [Massive.com](https://massive.com) API key

## Setup

```bash
git clone <repo-url> && cd Fintra
bash setup.sh
source venv/bin/activate
export MASSIVE_API_KEY='your_key_here'
python fintra.py
```

## Configuration

### config.ini

```ini
[dashboard]
refresh_interval = 10s    # 10s, 1m, 5m, 15m
economy_interval = 5m     # Economy data changes infrequently
```

### watchlist.txt

One ticker per line, organized by section:

```
[equities]
AAPL
MSFT

[crypto]
X:BTCUSD
X:ETHUSD

[indices]
I:SPX
I:VIX
```

**Ticker format:**
- Equities: bare symbol (`AAPL`, `MSFT`)
- Crypto: `X:` prefix (`X:BTCUSD`)
- Indices: `I:` prefix (`I:SPX`, `I:VIX`)
- Comments: lines starting with `#`

## Usage

| Key | Action |
|-----|--------|
| `q` | Quit |
| `Ctrl+C` | Quit (fallback) |

The dashboard displays:
- **Equities** — price, change, change%, open, high, low, volume
- **Crypto** — price, change, change%
- **Indices** — price, change, change%
- **Treasury Yields** — 1M through 30Y
- **Economy** — unemployment, participation rate, CPI, PCE

Data refreshes automatically per `config.ini` intervals. Stale data is marked when API calls fail.
