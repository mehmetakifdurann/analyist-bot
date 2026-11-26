"""Plugins return a paper order proposal after a closed candle."""
from dataclasses import dataclass
from decimal import Decimal as D
from typing import Protocol, Sequence

from spot_data import Candle
from .stream import Book


@dataclass(frozen=True)
class Intent:
    limit: D
    stop: D
    target: D
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
