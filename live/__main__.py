"""Continuous, read-only Binance market feed and paper execution."""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from typing import Iterable

from spot_data import get_json
from .executor import Filters, PaperExecutor
from .notify import Notifier
from .state import State
from .strategy import DailySwing, DemoPullback, Observe, Strategy
from .stream import Book, History, SYMBOL, URL, events, stamp

PUBLIC_FALLBACK = URL.replace("stream.binance.com:9443", "data-stream.binance.vision")


def filters() -> Filters:
    symbol, = get_json("exchangeInfo", symbol=SYMBOL)["symbols"]
    if (symbol["symbol"] != SYMBOL or symbol["status"] != "TRADING"
            or not symbol["isSpotTradingAllowed"] or symbol["quoteAsset"] != "USDT"):
        raise ValueError("Expected active Binance Spot PAXGUSDT")
    f = {v["filterType"]:v for v in symbol["filters"]}
    values = [D(f["LOT_SIZE"]["stepSize"]), D(f["LOT_SIZE"]["minQty"]),
              D((f.get("NOTIONAL") or f["MIN_NOTIONAL"])["minNotional"]),
              D(f["PRICE_FILTER"]["tickSize"])]
    if not all(x.is_finite() and x > 0 for x in values):
        raise ValueError("Invalid Spot filters")
    return Filters(*values)


def run(feed: Iterable[Book | History], executor: PaperExecutor, strategy: Strategy,
        notifier: Notifier, max_books: int = 0) -> int:
    closed = None
    trail = None
    update_id = -1
    seen = 0
    last_status = 0
    last_day = None
    latest_equity = latest_realized = None
    for event in feed:
        if isinstance(event, History):
            if isinstance(strategy, DailySwing):
                view = strategy.view(event.candles)
                if view:
                    trail = event.candles, D(str(view.atr))
                    if event.warmup or event.candles[-1].time.hour == 23:
                        context = strategy.view(event.candles,4)
                        logging.info("%s closed daily signal=%s ATR=%.4f 4h_up=%s",
                                     strategy.kind, view.flags[strategy.flag], view.atr,
                                     context.up if context else None)
            if event.warmup:
                closed = None
                logging.info("warmup/backfill: %d closed candles through %s",
                             len(event.candles),event.candles[-1].time.isoformat())
            else:
                closed = event.candles
            continue
        if event.update <= update_id:
            continue
        update_id = event.update
        now = int(time.time())
        day = datetime.fromtimestamp(now,timezone.utc).date()
        equity, realized, changes = executor.on_book(event,now)
        if trail is not None:
            executor.trail(*trail)
            trail = None
        if closed:
            opened = stamp(closed[-1])
            age = now - (opened//1000+3600)
            if -5 <= age <= 90:
                executor.on_close(opened,strategy.on_close(closed,event),event,now)
            closed = None
        if last_day is not None and last_day != day:
            notifier.publish({"kind":"paper_daily_summary","date":str(last_day),
                              "equity":str(latest_equity),"realized":str(latest_realized)})
        last_day, latest_equity, latest_realized = day, equity, realized
        for change in changes:
            logging.info("paper event %s",json.dumps(change))
            notifier.publish(change)
        seen += 1
        if now-last_status >= 60 or max_books and seen == max_books:
            logging.info("paper book=%s/%s equity=%s USDT realized=%s update=%d",
                         event.bid,event.ask,equity,realized,event.update)
            last_status = now
        if max_books and seen >= max_books:
            break
    return seen


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--mode", choices=("paper","testnet","live"), default="paper")
    cli.add_argument("--strategy", choices=("observe","demo-pullback","donchian-1d","keltner-1d"), default="observe")
    cli.add_argument("--db", type=Path, default=Path(os.getenv("PAPER_DB","paper.sqlite3")))
    cli.add_argument("--cash", type=D, default=D(os.getenv("PAPER_CASH","10000")))
    cli.add_argument("--daily-loss", type=D, default=D(os.getenv("PAPER_DAILY_LOSS","0.01")))
    cli.add_argument("--public-stream", action="store_true", help="Use Binance market-data-only WebSocket hostname")
    cli.add_argument("--max-books", type=int, default=0, help="Stop after this many book events (0 keeps running)")
    args = cli.parse_args()
    if args.mode != "paper":
        cli.error("Authenticated Binance modes are unavailable. Use --mode paper for public live prices.")
    if (not args.cash.is_finite() or args.cash <= 0 or not args.daily_loss.is_finite()
            or not 0 < args.daily_loss < 1 or args.max_books < 0):
        cli.error("Invalid paper settings")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    market_filters = filters()
    state = State(args.db,str(args.cash))
    executor = PaperExecutor(state,market_filters,args.daily_loss)
    notifier = Notifier(os.getenv("PAPER_WEBHOOK_URL"))
    demos = {"observe": Observe, "demo-pullback": DemoPullback}
    strategy = demos[args.strategy]() if args.strategy in demos else DailySwing(args.strategy)
    feed = events(PUBLIC_FALLBACK if args.public_stream else URL, notifier.publish,
                  getattr(strategy,"warmup_hours",250))
    try:
        run(feed,executor,strategy,notifier,args.max_books)
    except KeyboardInterrupt:
        logging.info("Paper engine stopped")
    finally:
        feed.close()
        state.db.close()


if __name__ == "__main__":
    main()
