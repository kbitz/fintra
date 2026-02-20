import os
import sys
import threading
import time
import warnings
from datetime import datetime, time as dt_time
from typing import Any, List
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.live import Live

from fintra.config import parse_config, parse_watchlist, list_watchlists
from fintra.constants import PROJECT_ROOT
from fintra.data import fetch_market_data, fetch_crypto_data, fetch_economy_data, fetch_ytd_closes, fetch_ticker_details
from fintra.plans import load_plans
from fintra.provider import MassiveProvider
from fintra.state import DashboardState
from fintra.ui import build_layout, key_listener
from fintra.websocket import start_ws_feeds, stop_ws_feeds


def main():
    # Load .env file if present
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

    # Validate API key
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        print("[error] MASSIVE_API_KEY environment variable not set.")
        print("  export MASSIVE_API_KEY='your_key'")
        sys.exit(1)

    # Parse config and watchlist
    config = parse_config()

    # Discover available watchlist files and load the first one
    watchlist_files = list_watchlists()
    if not watchlist_files:
        print("[error] No valid watchlist files found in watchlists/")
        sys.exit(1)
    watchlist_idx = 0
    watchlist = parse_watchlist(watchlist_files[watchlist_idx])

    total_tickers = len(watchlist["equities"]) + len(watchlist["crypto"]) + len(watchlist["indices"])
    if total_tickers == 0:
        print("[error] Watchlist has no tickers.")
        sys.exit(1)

    print(f"[fintra] Refresh: {config.refresh_interval}s market, {config.economy_interval}s economy")
    print(f"[fintra] Watching {total_tickers} tickers")

    # Suppress urllib3 SSL warning for LibreSSL
    warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")

    provider = MassiveProvider(api_key=api_key)
    plans = load_plans(provider)
    state = DashboardState()
    state.active_watchlist_name = os.path.basename(watchlist_files[watchlist_idx])

    # Save original terminal settings before key listener changes them
    _original_termios = None
    try:
        import termios as _termios
        _original_termios = _termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    # Start key listener thread
    listener = threading.Thread(target=key_listener, args=(state,), daemon=True)
    listener.start()

    # Show dashboard immediately, populate data in background
    console = Console()

    # Track WS feed references for lifecycle management
    ws_feeds: List[Any] = []
    was_open = False  # track market state transitions
    market_closed_at = None  # timestamp when market transitioned to closed
    DELAYED_GRACE = 15 * 60  # delayed feeds keep updating 15min after close

    def _check_market_status():
        try:
            status = provider.fetch_market_status()
            state.market_is_open = status["market_is_open"]
            groups = status.get("indices_groups", {})
            if groups:
                state.indices_group_status = groups
        except Exception:
            pass

    _ET = ZoneInfo("America/New_York")
    _PRE_MARKET_OPEN = dt_time(4, 0)
    _MARKET_OPEN = dt_time(9, 30)
    _MARKET_CLOSE = dt_time(16, 0)
    _AFTER_HOURS_CLOSE = dt_time(20, 0)

    def _in_extended_hours() -> bool:
        """True if current ET time is in pre-market or after-hours on a weekday."""
        now_et = datetime.now(_ET)
        if now_et.weekday() >= 5:  # weekend
            return False
        t = now_et.time()
        return (_PRE_MARKET_OPEN <= t < _MARKET_OPEN) or (_MARKET_CLOSE <= t < _AFTER_HOURS_CLOSE)

    def _all_realtime():
        """True if all entitled feeds are real-time (no delayed grace needed)."""
        has_stocks = bool(watchlist["equities"])
        has_indices = bool(watchlist["indices"])
        stocks_rt = (not has_stocks) or plans.stocks_realtime
        indices_rt = (not has_indices) or plans.indices_realtime
        return stocks_rt and indices_rt

    # Kick off all data fetches in background threads
    def _init_market():
        nonlocal ws_feeds, was_open
        _check_market_status()
        # Always do initial fetch to populate data regardless of market status
        fetch_market_data(provider, watchlist, state, plans)
        fetch_crypto_data(provider, watchlist, state, plans)
        if state.market_is_open:
            ws_feeds = start_ws_feeds(provider, watchlist, state, plans)
            was_open = True

    threading.Thread(target=_init_market, daemon=True).start()
    threading.Thread(target=fetch_economy_data, args=(provider, state), daemon=True).start()

    # Fetch YTD reference prices if any column config uses ytd%
    needs_ytd = "ytd%" in config.equity_cols or "ytd%" in config.index_cols
    needs_mktcap = "mktcap" in config.equity_cols
    if needs_ytd or needs_mktcap:
        def _deferred_fetches():
            # Wait for economy data to finish first to avoid rate limit contention
            while not state.economy_updated and not state.quit_flag:
                time.sleep(1)
            if needs_ytd:
                fetch_ytd_closes(provider, watchlist, state)
            if needs_mktcap:
                fetch_ticker_details(provider, watchlist, state)
        threading.Thread(target=_deferred_fetches, daemon=True).start()

    last_market_fetch = time.time()
    last_economy_fetch = time.time()
    last_status_check = time.time()
    last_crypto_fetch = time.time()

    effective_refresh = config.refresh_interval

    try:
        with Live(build_layout(state, watchlist, config, plans), console=console, screen=True, refresh_per_second=2) as live:
            while not state.quit_flag:
                now = time.time()

                # Handle watchlist switch
                if state.switch_watchlist:
                    state.switch_watchlist = False
                    watchlist_files = list_watchlists()
                    if len(watchlist_files) > 1:
                        watchlist_idx = (watchlist_idx + 1) % len(watchlist_files)
                    elif len(watchlist_files) == 1:
                        watchlist_idx = 0
                    else:
                        state.watchlist_error = "No valid watchlist files"
                    if watchlist_files:
                        new_path = watchlist_files[watchlist_idx]
                        try:
                            new_wl = parse_watchlist(new_path)
                            new_total = len(new_wl["equities"]) + len(new_wl["crypto"]) + len(new_wl["indices"])
                            if new_total == 0:
                                state.watchlist_error = f"{os.path.basename(new_path)}: no tickers"
                            else:
                                # Stop existing WS feeds
                                stop_ws_feeds(ws_feeds)
                                ws_feeds = []
                                was_open = False
                                market_closed_at = None
                                # Reset state data
                                state.equities = []
                                state.crypto = []
                                state.indices = []
                                state.treasury = {}
                                state.labor = {}
                                state.inflation = {}
                                state.prev_closes = {}
                                state.ytd_closes = {}
                                state.ticker_details = {}
                                state.market_updated = None
                                state.crypto_updated = None
                                state.crypto_data_date = None
                                state.economy_updated = None
                                state.market_stale = False
                                state.economy_stale = False
                                state.market_error = ""
                                state.economy_error = ""
                                state.ws_connected = False
                                state.watchlist_error = ""
                                # Swap watchlist
                                watchlist = new_wl
                                state.active_watchlist_name = os.path.basename(new_path)
                                # Re-kick data fetches
                                threading.Thread(target=_init_market, daemon=True).start()
                                threading.Thread(target=fetch_economy_data, args=(provider, state), daemon=True).start()
                                if needs_ytd or needs_mktcap:
                                    threading.Thread(target=_deferred_fetches, daemon=True).start()
                                last_market_fetch = now
                                last_economy_fetch = now
                                last_status_check = now
                                last_crypto_fetch = now
                        except Exception as e:
                            state.watchlist_error = f"{os.path.basename(new_path)}: {e}"

                # Check market status every 60s
                if now - last_status_check >= 60:
                    _check_market_status()
                    last_status_check = now

                    # Handle market open/close transitions
                    if state.market_is_open and not was_open:
                        # Market just opened — reconnect WS and do an initial fetch
                        market_closed_at = None
                        ws_feeds = start_ws_feeds(provider, watchlist, state, plans)
                        threading.Thread(target=fetch_market_data, args=(provider, watchlist, state, plans), daemon=True).start()
                        threading.Thread(target=fetch_crypto_data, args=(provider, watchlist, state, plans), daemon=True).start()
                        last_market_fetch = now
                        last_crypto_fetch = now
                        was_open = True
                    elif not state.market_is_open and was_open and market_closed_at is None:
                        # Market just closed
                        threading.Thread(target=fetch_market_data, args=(provider, watchlist, state, plans), daemon=True).start()
                        if _all_realtime():
                            # Real-time feeds: stop immediately
                            stop_ws_feeds(ws_feeds)
                            ws_feeds = []
                            was_open = False
                        else:
                            # Delayed feeds: keep running for 15 more minutes
                            market_closed_at = now

                # Expire delayed grace period
                if market_closed_at is not None and now - market_closed_at >= DELAYED_GRACE:
                    stop_ws_feeds(ws_feeds)
                    ws_feeds = []
                    threading.Thread(target=fetch_market_data, args=(provider, watchlist, state, plans), daemon=True).start()
                    was_open = False
                    market_closed_at = None

                # Adjust refresh rate when rate-limited
                if state.rate_limited:
                    effective_refresh = min(config.refresh_interval * 4, 120)
                else:
                    effective_refresh = config.refresh_interval

                # Equities/indices: active when market open, in delayed grace, or extended hours
                ext_hours = _in_extended_hours()
                state.extended_hours = ext_hours
                eq_active = state.market_is_open or market_closed_at is not None or ext_hours
                if eq_active:
                    if now - last_market_fetch >= effective_refresh:
                        threading.Thread(target=fetch_market_data, args=(provider, watchlist, state, plans), daemon=True).start()
                        last_market_fetch = now

                # Crypto: starter plan polls at refresh interval, basic hourly (data is daily)
                crypto_interval = effective_refresh if plans.currencies_has_snapshots else 3600
                if plans.currencies_has_snapshots or eq_active:
                    if now - last_crypto_fetch >= crypto_interval:
                        threading.Thread(target=fetch_crypto_data, args=(provider, watchlist, state, plans), daemon=True).start()
                        last_crypto_fetch = now

                # Economy data refresh (independent of market hours)
                if now - last_economy_fetch >= config.economy_interval:
                    threading.Thread(target=fetch_economy_data, args=(provider, state), daemon=True).start()
                    last_economy_fetch = now

                live.update(build_layout(state, watchlist, config, plans))
                time.sleep(0.5)

    except KeyboardInterrupt:
        pass
    finally:
        state.quit_flag = True
        stop_ws_feeds(ws_feeds)
        # Restore original terminal settings
        if _original_termios:
            try:
                import termios as _termios
                _termios.tcsetattr(sys.stdin.fileno(), _termios.TCSADRAIN, _original_termios)
            except Exception:
                pass
        console.clear()
        print("[fintra] Goodbye.")
