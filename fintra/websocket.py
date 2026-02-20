import threading
import time
from typing import Any, Dict, List

from fintra.plans import PlanInfo
from fintra.state import DashboardState

# Track which feeds are currently connected
_connected_feeds: set = set()
_connected_lock = threading.Lock()


def _set_connected(label: str, connected: bool, state: DashboardState):
    """Update the connected feeds set and state flag."""
    with _connected_lock:
        if connected:
            _connected_feeds.add(label)
        else:
            _connected_feeds.discard(label)
        state.ws_connected = bool(_connected_feeds)


class WsFeedHandle:
    """Handle for a WebSocket feed with automatic reconnection."""

    def __init__(self):
        self._stopped = False
        self._current_feed = None
        self._lock = threading.Lock()

    def set_feed(self, feed):
        with self._lock:
            self._current_feed = feed

    @property
    def stopped(self):
        return self._stopped

    def close(self):
        self._stopped = True
        with self._lock:
            if self._current_feed:
                try:
                    self._current_feed.close()
                except Exception:
                    pass


def _update_ticker(items: List[Dict[str, Any]], ticker: str, last: float,
                   prev_closes: Dict[str, float], **extra):
    """Update a ticker dict in a list with new price data."""
    for item in items:
        if item["ticker"] == ticker:
            old_change = item.get("change")
            item["last"] = last
            prev = prev_closes.get(ticker)
            if prev:
                item["change"] = last - prev
                item["change_pct"] = (item["change"] / prev) * 100
            if old_change is not None and item.get("change") != old_change:
                item["_flash_until"] = time.time() + 1.0
                item["_flash_up"] = (item["change"] - old_change) > 0
            for k, v in extra.items():
                if v is not None:
                    if k in ("high",) and item.get(k) is not None:
                        item[k] = max(item[k], v)
                    elif k in ("low",) and item.get(k) is not None:
                        item[k] = min(item[k], v)
                    else:
                        item[k] = v
            return True
    return False


def _run_feed_with_reconnect(handle, provider, market, feed_type, tickers,
                              on_update, state, label):
    """Run a WS feed, reconnecting automatically on disconnect with backoff."""
    backoff = 1
    max_backoff = 60
    while not handle.stopped and not state.quit_flag:
        try:
            feed = provider.create_ws_feed(market, feed_type, tickers, on_update)
            handle.set_feed(feed)
            if handle.stopped:
                try:
                    feed.close()
                except Exception:
                    pass
                return
            _set_connected(label, True, state)
            backoff = 1  # reset on successful connection
            feed.run()
        except Exception:
            pass
        finally:
            _set_connected(label, False, state)
            handle.set_feed(None)
        # Backoff before reconnecting (check stop flag frequently)
        for _ in range(int(backoff * 2)):
            if handle.stopped or state.quit_flag:
                return
            time.sleep(0.5)
        backoff = min(backoff * 2, max_backoff)


def start_ws_feeds(provider, watchlist: Dict[str, List[str]],
                   state: DashboardState, plans: PlanInfo) -> List[WsFeedHandle]:
    """Start WebSocket feeds with automatic reconnection in background threads.

    Returns list of WsFeedHandle instances so they can be closed later.
    Only starts WS feeds for plans that support WebSockets.
    """
    handles: List[WsFeedHandle] = []

    # Stocks feed — only if plan supports WebSockets (Starter+)
    if watchlist["equities"] and plans.stocks_has_ws:
        feed_type = "realtime" if plans.stocks_realtime else "delayed"

        def _on_stock(ticker, price, extras):
            _update_ticker(state.equities, ticker, price, state.prev_closes, **extras)
            state.market_updated = time.time()

        handle = WsFeedHandle()
        handles.append(handle)
        threading.Thread(target=_run_feed_with_reconnect,
                        args=(handle, provider, "stocks", feed_type,
                              watchlist["equities"], _on_stock, state, "stocks"),
                        daemon=True).start()

    # Indices feed — only if plan supports WebSockets (Starter+)
    if watchlist["indices"] and plans.indices_has_ws:
        feed_type = "realtime" if plans.indices_realtime else "delayed"

        def _on_index(ticker, price, extras):
            _update_ticker(state.indices, ticker, price, state.prev_closes, **extras)
            state.market_updated = time.time()

        handle = WsFeedHandle()
        handles.append(handle)
        threading.Thread(target=_run_feed_with_reconnect,
                        args=(handle, provider, "indices", feed_type,
                              watchlist["indices"], _on_index, state, "indices"),
                        daemon=True).start()

    # Crypto feed — only if Currencies Starter
    if watchlist["crypto"] and plans.currencies_has_ws:
        def _on_crypto(ticker, price, extras):
            _update_ticker(state.crypto, ticker, price, state.prev_closes, **extras)
            state.market_updated = time.time()

        handle = WsFeedHandle()
        handles.append(handle)
        threading.Thread(target=_run_feed_with_reconnect,
                        args=(handle, provider, "crypto", "realtime",
                              watchlist["crypto"], _on_crypto, state, "crypto"),
                        daemon=True).start()

    return handles


def stop_ws_feeds(feeds: List[WsFeedHandle]):
    """Close all WebSocket feed connections and stop reconnection."""
    for f in feeds:
        try:
            f.close()
        except Exception:
            pass
