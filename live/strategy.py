"""Plugins return a paper order proposal after a closed candle."""
from dataclasses import dataclass
from decimal import Decimal as D
from typing import Protocol, Sequence

from spot_data import Candle
from paxg_edge_v2 import View, resample, swing_view
from paxg_research import Bar
from .stream import Book


@dataclass(frozen=True)
class Intent:
    limit: D
    stop: D
    target: D | None
    ttl_seconds: int = 3600


class Strategy(Protocol):
    def on_close(self, candles: Sequence[Candle], book: Book) -> Intent | None: ...


class Observe:
    def on_close(self, candles: Sequence[Candle], book: Book) -> None:
        return None


class DemoPullback:
    """Opt-in example to exercise the paper executor."""
    def on_close(self, candles: Sequence[Candle], book: Book) -> Intent | None:
        if len(candles) < 50:
            return None
        short = sum(c.close for c in candles[-20:])/20
        long = sum(c.close for c in candles[-50:])/50
        last = candles[-1]
        if short > long and last.low <= short < last.close:
            limit = min(short, book.bid)
            return Intent(limit, limit*D(".99"), limit*D("1.02"))
        return None


class DailySwing:
    """Paper execution adapter for the common V3 daily indicators."""
    warmup_hours = 56 * 24

    def __init__(self, kind: str):
        self.kind = kind
        self.flag = {"donchian-1d": 0, "keltner-1d": 1}[kind]

    def view(self, candles: Sequence[Candle], period: int = 24) -> View | None:
        hourly = [Bar(c.time, *(float(v) for v in (c.open,c.high,c.low,c.close,c.volume)))
                  for c in candles]
        bars = resample(hourly,period)[-51:]
        if len(bars) != 51 or (bars[-1].time-bars[0].time).total_seconds() != 50*period*3600:
            return None
        return swing_view(bars)

    def on_close(self, candles: Sequence[Candle], book: Book) -> Intent | None:
        if candles[-1].time.hour != 23:
            return None
        v = self.view(candles)
        if v is None or not v.flags[self.flag] or v.atr <= 0:
            return None
        limit = book.bid
        return Intent(limit, limit-3*D(str(v.atr)), None)
