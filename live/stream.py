"""Unauthenticated Binance Spot market data with reconnect and closed-bar backfill."""
from __future__ import annotations

import json
import logging
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Iterator

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from spot_data import INTERVAL_MS, Candle, get_json, validate_candle

SYMBOL = "PAXGUSDT"
URL = "wss://stream.binance.com:9443/stream?streams=paxgusdt@kline_1h/paxgusdt@bookTicker"
D = Decimal
ROTATE_AFTER = 23*3600 + 55*60


@dataclass(frozen=True)
class Book:
    update: int
    bid: D
    ask: D
    bid_qty: D
    ask_qty: D


@dataclass(frozen=True)
class History:
    candles: tuple[Candle, ...]
    warmup: bool


def stamp(candle: Candle) -> int:
    return int(candle.time.timestamp()*1000)


def candle_at(ms: int, values: list) -> Candle:
    if ms % INTERVAL_MS:
        raise ValueError("Unaligned hourly candle")
    bar = Candle(datetime.fromtimestamp(ms/1000, timezone.utc), *map(D, values))
    validate_candle(bar)
    return bar


def decode(message: str) -> Book | Candle | None:
    packet = json.loads(message)
    data = packet.get("data", {})
    if data.get("s") != SYMBOL:
        return None
    if packet.get("stream") == "paxgusdt@bookTicker":
        b,a,bq,aq = (D(data[k]) for k in ("b","a","B","A"))
        if not all(v.is_finite() and v > 0 for v in (b,a,bq,aq)) or b > a:
            raise ValueError("Invalid public book")
        return Book(int(data["u"]),b,a,bq,aq)
    if packet.get("stream") == "paxgusdt@kline_1h":
        k = data["k"]
        if k["x"] is True and k["i"] == "1h" and k["T"] == k["t"]+INTERVAL_MS-1:
            return candle_at(k["t"], [k[field] for field in ("o","h","l","c","v")])
    return None


def backfill(after: int | None = None, limit: int = 250) -> list[Candle]:
    now = int(get_json("time")["serverTime"])
    boundary = now - now % INTERVAL_MS
    cursor = boundary-limit*INTERVAL_MS if after is None else after+INTERVAL_MS
    result = []
    while cursor < boundary:
        rows = get_json("klines", symbol=SYMBOL, interval="1h", startTime=cursor,
                        endTime=boundary-1, limit=1000)
        if not rows:
            raise ValueError("Incomplete REST backfill")
        for row in rows:
            if row[0] != cursor or row[6] != cursor+INTERVAL_MS-1 or row[6] >= boundary:
                raise ValueError("REST candle gap or unclosed candle")
            result.append(candle_at(cursor, row[1:6]))
            cursor += INTERVAL_MS
    return result


def events(url: str = URL, on_error: Callable[[dict], None] | None = None,
           warmup_hours: int = 250, *, deadline: float | None = None,
           stats: dict[str, int] | None = None) -> Iterator[Book | History]:
    candles: deque[Candle] = deque(maxlen=warmup_hours)
    delay = 1.

    def remaining() -> float:
        return float("inf") if deadline is None else deadline-time.monotonic()

    def count(key: str) -> None:
        if stats is not None:
            stats[key] = stats.get(key, 0)+1

    while remaining() > 0:
        connected = False
        try:
            with connect(url, open_timeout=min(10, remaining()), close_timeout=3) as ws:
                connected = True
                count("websocket_connections")
                rotate_at = time.monotonic()+ROTATE_AFTER
                if candles:
                    candles.extend(backfill(stamp(candles[-1])))
                else:
                    candles.extend(backfill(limit=warmup_hours))
                yield History(tuple(candles), warmup=True)
                while remaining() > 0 and time.monotonic() < rotate_at:
                    event = decode(ws.recv(timeout=min(45, remaining())))
                    if remaining() <= 0:
                        return
                    if event is None:
                        continue
                    delay = 1.
                    if isinstance(event, Book):
                        yield event
                        continue
                    current = stamp(candles[-1])
                    if stamp(event) <= current:
                        continue
                    if stamp(event) != current+INTERVAL_MS:
                        candles.extend(backfill(current))
                        recovered = stamp(candles[-1])
                        if recovered == stamp(event)-INTERVAL_MS:
                            candles.append(event)
                        elif recovered < stamp(event):
                            raise ValueError("WebSocket gap could not be recovered")
                        yield History(tuple(candles), warmup=True)
                    else:
                        candles.append(event)
                        yield History(tuple(candles), warmup=False)
                if remaining() <= 0:
                    return
                count("websocket_rotations")
                logging.info("Rotating Binance Spot connection before its 24h limit")
        except (OSError, TimeoutError, WebSocketException, ValueError, KeyError, ArithmeticError) as exc:
            if remaining() <= 0:
                return
            count("websocket_disconnects" if connected else "websocket_connect_failures")
            logging.warning("Market stream reconnect in %.1fs (%s)", delay, type(exc).__name__)
            if on_error:
                on_error({"kind": "paper_market_disconnect", "error": type(exc).__name__, "retry_seconds": delay})
            time.sleep(max(0, min(remaining(), delay+random.uniform(0, delay*.2))))
            delay = min(delay*2, 60)
