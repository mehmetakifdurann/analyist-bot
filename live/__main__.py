"""Continuous, read-only Binance market feed and paper execution."""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from statistics import median
from typing import Callable, Iterable

from spot_data import get_json
from .adapters import ExecutionAdapter, PaperExecutionAdapter
from .executor import Filters
from .notify import Notifier, publish_heartbeat
from .report import export_csv, healthy, performance, read
from .state import State
from .timemachine import HISTORY_HOURS, diagnose
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


def run(feed: Iterable[Book | History], executor: ExecutionAdapter, strategy: Strategy,
        notifier: Notifier, max_books: int = 0, *, clock: Callable[[], float] = time.time,
        on_equity: Callable[[D], None] | None = None,
        stats: dict | None = None, deadline: float | None = None,
        risk_overlay: bool = False, mc_seed: int = 42, mc_paths: bool = True) -> int:
    closed = None
    trail = None
    update_id = -1
    seen = 0
    last_status = 0
    last_signal = None
    last_heartbeat_check = None
    last_candle = None
    for event in feed:
        if deadline is not None and time.monotonic() >= deadline:
            break
        if isinstance(event, History):
            if stats is not None:
                recent = [c for c in event.candles if last_candle is None or c.time > last_candle]
                key = ("warmup_candles" if last_candle is None else "backfilled_candles"
                       if event.warmup else "closed_1h_candles")
                stats[key] += len(recent)
                last_candle = event.candles[-1].time
                if key == "closed_1h_candles":
                    stats["utc_daily_closes"] += sum(c.time.hour == 23 for c in recent)
            if isinstance(strategy, DailySwing):
                view = strategy.view(event.candles)
                last_signal = {"time": event.candles[-1].time.replace(hour=0).isoformat()
                               if event.candles[-1].time.hour == 23 else
                               (event.candles[-1].time.replace(hour=0)-timedelta(days=1)).isoformat(),
                               "strategy": strategy.kind, "entry": view.flags[strategy.flag]} if view else None
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
        now = int(clock())
        equity, realized, changes = executor.on_book(event,now)
        if trail is not None:
            executor.trail(*trail)
            trail = None
        if closed:
            opened = stamp(closed[-1])
            age = now - (opened//1000+3600)
            daily = (stats is not None and isinstance(strategy, DailySwing)
                     and closed[-1].time.hour == 23)
            if daily:
                decision = {"closed_at_utc": (closed[-1].time+timedelta(hours=1)).isoformat(),
                            "signal": last_signal, "fresh_quote": -5 <= age <= 90,
                            "trade_ticket": None}
                stats["daily_decisions"].append(decision)
            if -5 <= age <= 90:
                intent = strategy.on_close(closed,event)
                if not isinstance(strategy, DailySwing):
                    last_signal = {"time": closed[-1].time.isoformat(), "entry": intent is not None}
                context = None
                if risk_overlay and intent and isinstance(strategy, DailySwing) and strategy.kind == "ema-1d":
                    ranges = [c.high-c.low for c in closed[-21:]]
                    typical = median(ranges[:-1]) if len(ranges) == 21 else D(0)
                    reference = intent.target or intent.limit+2*(intent.limit-intent.stop)
                    context = {
                        "shock": ranges[-1]/typical if typical > 0 else None,
                        "timemachine": diagnose(closed,float(intent.limit),float(intent.stop),
                                                 float(reference),seed=mc_seed)
                                       if mc_paths and 0 < intent.stop < intent.limit < reference
                                       else {"status":"not_evaluated"},
                    }
                signal = (executor.submit(opened,intent,event,now,context=context) if context is not None
                          else executor.submit(opened,intent,event,now))
                if stats is not None and intent is not None:
                    stats["entry_signals"] += 1
                if daily:
                    decision["trade_ticket"] = signal
                if signal:
                    logging.info("paper entry %s",json.dumps(signal))
                    notifier.publish(signal)
            closed = None
        if on_equity is not None:
            on_equity(equity)
        minute = now//60
        if minute != last_heartbeat_check:
            publish_heartbeat(notifier, executor.daily_heartbeat(now,last_signal))
            last_heartbeat_check = minute
        for change in changes:
            logging.info("paper event %s",json.dumps(change))
            notifier.publish(change)
        seen += 1
        if stats is not None:
            stats["book_tickers"] = seen
            stats["last_signal"] = last_signal
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
    cli.add_argument("--strategy", choices=("observe","demo-pullback","donchian-1d","keltner-1d","ema-1d"), default="ema-1d")
    cli.add_argument("--db", type=Path, default=Path(os.getenv("PAPER_DB","paper.sqlite3")))
    cli.add_argument("--cash", type=D, default=D(os.getenv("PAPER_CASH","10000")))
    cli.add_argument("--daily-loss", type=D, default=D(os.getenv("PAPER_DAILY_LOSS","0.01")))
    cli.add_argument("--public-stream", action="store_true", help="Use Binance market-data-only WebSocket hostname")
    cli.add_argument("--max-books", type=int, default=0, help="Stop after this many book events (0 keeps running)")
    options = cli.add_mutually_exclusive_group()
    options.add_argument("--report", action="store_true", help="Print paper ledger performance as JSON")
    options.add_argument("--healthcheck", action="store_true", help="Check the SQLite ledger and recent market activity")
    cli.add_argument("--export-csv", type=Path, help="Export ledger events to a new CSV file (--report or --duration-hours)")
    options.add_argument("--duration-hours", type=float, help="Run a bounded live paper session")
    cli.add_argument("--mc-seed", type=int, default=42)
    args = cli.parse_args()
    if args.duration_hours is not None and (
            not math.isfinite(args.duration_hours*3600) or args.duration_hours <= 0 or args.max_books):
        cli.error("--duration-hours must be finite and positive and cannot be combined with --max-books")
    if args.duration_hours is not None:
        if args.export_csv is None:
            hours = args.duration_hours
            label = str(int(hours)) if hours.is_integer() else str(hours)
            args.export_csv = Path(f"paper_runs/soak-{label}h.csv")
        args.export_csv.parent.mkdir(parents=True, exist_ok=True)
        if args.export_csv.exists() or args.export_csv.with_suffix(".json").exists():
            cli.error("Soak CSV or JSON already exists. Choose a new --export-csv path.")
    if args.export_csv and not args.report and args.duration_hours is None:
        cli.error("--export-csv requires --report or --duration-hours")
    if args.report or args.healthcheck:
        try:
            if args.healthcheck:
                if not healthy(args.db):
                    cli.exit(1, "No recent paper market activity\n")
                return
            wallet, ledger = read(args.db)
            if args.export_csv:
                export_csv(args.export_csv,ledger)
            print(json.dumps(performance(wallet,ledger),indent=2,ensure_ascii=False))
            return
        except (OSError, sqlite3.Error, ValueError, KeyError, ArithmeticError) as exc:
            cli.exit(1, f"Paper ledger error: {exc}\n")
    if args.mode != "paper":
        cli.error("Authenticated Binance modes are unavailable. Use --mode paper for public live prices.")
    if (not args.cash.is_finite() or args.cash <= 0 or not args.daily_loss.is_finite()
            or not 0 < args.daily_loss < 1 or args.max_books < 0):
        cli.error("Invalid paper settings")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    market_filters = filters()
    state = State(args.db,str(args.cash))
    executor = PaperExecutionAdapter(state,market_filters,args.daily_loss)
    notifier = Notifier(os.getenv("PAPER_WEBHOOK_URL"), os.getenv("TELEGRAM_BOT_TOKEN"),
                        os.getenv("TELEGRAM_CHAT_ID"))
    demos = {"observe": Observe, "demo-pullback": DemoPullback}
    strategy = demos[args.strategy]() if args.strategy in demos else DailySwing(args.strategy)
    started = time.monotonic()
    started_utc = datetime.now(timezone.utc)
    deadline = started+args.duration_hours*3600 if args.duration_hours is not None else None
    stats = dict(book_tickers=0, closed_1h_candles=0, backfilled_candles=0, warmup_candles=0,
                 websocket_connections=0, websocket_disconnects=0, websocket_connect_failures=0,
                 websocket_rotations=0, utc_daily_closes=0, entry_signals=0, last_signal=None, daily_decisions=[])
    url = PUBLIC_FALLBACK if args.public_stream else URL
    feed = events(url,notifier.publish,HISTORY_HOURS+1 if args.strategy == "ema-1d"
                  else getattr(strategy,"warmup_hours",250),
                  deadline=deadline,stats=stats if deadline is not None else None)
    interrupted = False
    try:
        run(feed,executor,strategy,notifier,args.max_books,
            stats=stats if deadline is not None else None,deadline=deadline,
            risk_overlay=True,mc_seed=args.mc_seed)
    except KeyboardInterrupt:
        interrupted = True
        logging.info("Paper engine stopped")
    finally:
        try:
            feed.close()
        finally:
            state.db.close()
    if deadline is not None:
        wallet, ledger = read(args.db)
        report = performance(wallet,ledger)
        report["soak"] = {
            **stats, "websocket_reconnections": max(0,stats["websocket_connections"]-1),
            "market": SYMBOL, "strategy": args.strategy, "websocket_url": url,
            "start_utc": started_utc.isoformat(), "end_utc": datetime.now(timezone.utc).isoformat(),
            "requested_seconds": args.duration_hours*3600,
            "elapsed_seconds": round(time.monotonic()-started,3),
            "completed": not interrupted and time.monotonic() >= deadline,
            "healthcheck": "healthy" if healthy(args.db) else "unhealthy",
        }
        export_csv(args.export_csv,ledger)
        payload = json.dumps(report,indent=2,ensure_ascii=False)
        with args.export_csv.with_suffix(".json").open("x",encoding="utf-8") as output:
            output.write(payload+"\n")
        print(payload)
        if interrupted or not report["soak"]["completed"]:
            cli.exit(1)


if __name__ == "__main__":
    main()
