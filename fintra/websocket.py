import threading
import time
from typing import Any, Dict, List

from massive import WebSocketClient
from massive.websocket import Feed, Market
from massive.websocket.models import CurrencyAgg, EquityAgg, IndexValue

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


def start_ws_feeds(api_key: str, watchlist: Dict[str, List[str]],
                   state: DashboardState, plans: PlanInfo) -> List[Any]:
    """Start WebSocket feeds for real-time price updates in background threads.

    Returns list of WebSocketClient instances so they can be closed later.
    Only starts WS feeds for plans that support WebSockets.
    """
    clients: List[Any] = []

    def _run_ws(ws_client, label):
        try:
            state.ws_connected = True
            ws_client.run(lambda msgs: _on_ws_msgs(msgs, state, label))
        except Exception:
            pass
        finally:
            state.ws_connected = False

    def _on_ws_msgs(msgs, state, label):
        for msg in msgs:
            if isinstance(msg, EquityAgg) and msg.symbol and msg.close is not None:
                _update_ticker(state.equities, msg.symbol, msg.close, state.prev_closes,
                               high=msg.high, low=msg.low, volume=msg.accumulated_volume)
                state.market_updated = time.time()

            elif isinstance(msg, IndexValue) and msg.ticker and msg.value is not None:
                _update_ticker(state.indices, msg.ticker, msg.value, state.prev_closes)
                state.market_updated = time.time()

            elif isinstance(msg, CurrencyAgg) and msg.pair and msg.close is not None:
                _update_ticker(state.crypto, msg.pair, msg.close, state.prev_closes,
                               high=msg.high, low=msg.low, volume=msg.volume)
                state.market_updated = time.time()

    # Stocks feed — only if plan supports WebSockets (Starter+)
    if watchlist["equities"] and plans.stocks_has_ws:
        stock_feed = Feed.RealTime if plans.stocks_realtime else Feed.Delayed
        stock_subs = [f"A.{t}" for t in watchlist["equities"]]
        stock_ws = WebSocketClient(
            api_key=api_key, feed=stock_feed,
            market=Market.Stocks, subscriptions=stock_subs,
        )
        clients.append(stock_ws)
        threading.Thread(target=_run_ws, args=(stock_ws, "stocks"), daemon=True).start()

    # Indices feed — only if plan supports WebSockets (Starter+)
    if watchlist["indices"] and plans.indices_has_ws:
        index_feed = Feed.RealTime if plans.indices_realtime else Feed.Delayed
        index_subs = [f"V.{t}" for t in watchlist["indices"]]
        index_ws = WebSocketClient(
            api_key=api_key, feed=index_feed,
            market=Market.Indices, subscriptions=index_subs,
        )
        clients.append(index_ws)
        threading.Thread(target=_run_ws, args=(index_ws, "indices"), daemon=True).start()

    # Crypto feed — only if Currencies Starter
    if watchlist["crypto"] and plans.currencies_has_ws:
        crypto_subs = [f"XA.{t}" for t in watchlist["crypto"]]
        crypto_ws = WebSocketClient(
            api_key=api_key, feed=Feed.RealTime,
            market=Market.Crypto, subscriptions=crypto_subs,
        )
        clients.append(crypto_ws)
        threading.Thread(target=_run_ws, args=(crypto_ws, "crypto"), daemon=True).start()

    return clients


def stop_ws_feeds(clients: List[Any]):
    """Close all WebSocket client connections."""
    for c in clients:
        try:
            c.close()
        except Exception:
            pass
