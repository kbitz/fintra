import threading
import time
from typing import Any, Dict, List

from fintra.plans import PlanInfo
from fintra.state import DashboardState


def _update_ticker(items: List[Dict[str, Any]], ticker: str, last: float,
                   prev_closes: Dict[str, float], **extra):
    """Update a ticker dict in a list with new price data."""
    for item in items:
        if item["ticker"] == ticker:
            item["last"] = last
            prev = prev_closes.get(ticker)
            if prev:
                item["change"] = last - prev
                item["change_pct"] = (item["change"] / prev) * 100
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


def start_ws_feeds(provider, watchlist: Dict[str, List[str]],
                   state: DashboardState, plans: PlanInfo) -> List[Any]:
    """Start WebSocket feeds for real-time price updates in background threads.

    Returns list of WsFeed instances so they can be closed later.
    Only starts WS feeds for plans that support WebSockets.
    """
    feeds: List[Any] = []

    def _run_feed(feed, label):
        try:
            state.ws_connected = True
            feed.run()
        except Exception:
            pass
        finally:
            state.ws_connected = False

    # Stocks feed — only if plan supports WebSockets (Starter+)
    if watchlist["equities"] and plans.stocks_has_ws:
        feed_type = "realtime" if plans.stocks_realtime else "delayed"

        def _on_stock(ticker, price, extras):
            _update_ticker(state.equities, ticker, price, state.prev_closes, **extras)
            state.market_updated = time.time()

        stock_feed = provider.create_ws_feed("stocks", feed_type,
                                             watchlist["equities"], _on_stock)
        feeds.append(stock_feed)
        threading.Thread(target=_run_feed, args=(stock_feed, "stocks"), daemon=True).start()

    # Indices feed — only if plan supports WebSockets (Starter+)
    if watchlist["indices"] and plans.indices_has_ws:
        feed_type = "realtime" if plans.indices_realtime else "delayed"

        def _on_index(ticker, price, extras):
            _update_ticker(state.indices, ticker, price, state.prev_closes, **extras)
            state.market_updated = time.time()

        index_feed = provider.create_ws_feed("indices", feed_type,
                                             watchlist["indices"], _on_index)
        feeds.append(index_feed)
        threading.Thread(target=_run_feed, args=(index_feed, "indices"), daemon=True).start()

    # Crypto feed — only if Currencies Starter
    if watchlist["crypto"] and plans.currencies_has_ws:
        def _on_crypto(ticker, price, extras):
            _update_ticker(state.crypto, ticker, price, state.prev_closes, **extras)
            state.market_updated = time.time()

        crypto_feed = provider.create_ws_feed("crypto", "realtime",
                                              watchlist["crypto"], _on_crypto)
        feeds.append(crypto_feed)
        threading.Thread(target=_run_feed, args=(crypto_feed, "crypto"), daemon=True).start()

    return feeds


def stop_ws_feeds(feeds: List[Any]):
    """Close all WebSocket feed connections."""
    for f in feeds:
        try:
            f.close()
        except Exception:
            pass
