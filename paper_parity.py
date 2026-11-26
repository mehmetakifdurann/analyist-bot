"""Replay historical OHLC through the live paper engine with synthetic quotes."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path

from live.__main__ import run
from live.executor import Filters, PaperExecutor
from live.notify import Notifier
from live.state import State
from live.strategy import DailySwing
from live.stream import Book, History
from paxg_research import Bar, HOUR, metrics
from spot_data import Candle

START = datetime(2021, 8, 30, tzinfo=timezone.utc)
END = datetime(2026, 11, 26, tzinfo=timezone.utc)


def parity(bars: list[Bar], name: str, high_first: bool = False, *,
           ttl_seconds: int = 3600, position_cap: D = D(".25"),
           risk_overlay: bool = False) -> dict:
    strategy = DailySwing(name, ttl_seconds=ttl_seconds)
    state = State(Path(":memory:"), "10000")
    # Fixed PAXG filter snapshot. Historical filters and book quantities are unavailable.
    executor = PaperExecutor(state, Filters(D(".0001"), D(".0001"), D("5"), D(".01")), position_cap=position_cap)
    history: deque[Candle] = deque(maxlen=strategy.warmup_hours)
    now = 0
    marks = []
    gaps = 0

    def feed():
        nonlocal now, gaps
        previous = None
        update = 0
        for bar in bars:
            if bar.time >= END:
                break
            if previous is not None and bar.time-previous != HOUR:
                history.clear()
                if bar.time >= START:
                    gaps += 1
            ready = bar.time >= START
            if ready and history:
                yield History(tuple(history), warmup=previous != bar.time-HOUR or bar.time == START)
            if ready:
                t = int(bar.time.timestamp())
                extremes = (bar.high, bar.low) if high_first else (bar.low, bar.high)
                for offset, raw in zip((0, 900, 1800, 3599), (bar.open, *extremes, bar.close)):
                    now = t+offset
                    update += 1
                    mid = D(str(raw))
                    yield Book(update, mid*D(".9999"), mid*D("1.0001"), D(1000), D(1000))
            history.append(Candle(bar.time, *(D(str(x)) for x in
                                               (bar.open,bar.high,bar.low,bar.close,bar.volume))))
            previous = bar.time

    try:
        run(feed(), executor, strategy, Notifier(None), clock=lambda: now, on_equity=marks.append,
            risk_overlay=risk_overlay, mc_paths=False)
        ending = marks[-1]
        rows = state.db.execute("SELECT kind,body FROM events").fetchall()
        tickets = [json.loads(body) for kind,body in rows if kind=="trade_ticket"]
        pnl = [float(json.loads(body)["pnl"]) for kind,body in rows if kind in ("stop","target")]
        peak = D("10000")
        drawdown = D(0)
        for mark in marks:
            peak = max(peak,mark)
            drawdown = max(drawdown,1-mark/peak)
        closes = [D("10000"), *marks[3::4]]
        ret = [float(b/a-1) for a,b in zip(closes,closes[1:])]
        with state.transaction() as wallet:
            return {**metrics(ret,pnl,float(drawdown)),
                    "submitted":sum(kind=="submitted" for kind,_ in rows),
                    "filled":sum(kind=="filled" for kind,_ in rows),
                    "canceled":sum(kind=="canceled" for kind,_ in rows),
                    "end_equity_usdt":float(ending), "end_cash_usdt":float(wallet["cash"]),
                    "end_position_open":bool(wallet["position"]), "data_gaps":gaps,
                    **({"tickets_passed":sum(t["risk_check"]=="PASS" for t in tickets),
                        "tickets_blocked":sum(t["risk_check"]!="PASS" for t in tickets)} if risk_overlay else {})}
    finally:
        state.db.close()


def ema_sensitivity(bars: list[Bar]) -> dict:
    results = []
    for hours in (1, 4):
        for cap in (D(".25"), D(".50")):
            paths = {}
            for path in ("low_first", "high_first"):
                case = parity(bars, "ema-1d", path == "high_first",
                              ttl_seconds=3600*hours, position_cap=cap)
                case["fill_rate_pct"] = 100*case["filled"]/case["submitted"] if case["submitted"] else None
                paths[path] = case
            results.append({"ttl_hours": hours, "position_cap_pct": int(cap*100), "paths": paths})
    return {"strategy": "ema-1d", "start_utc": START.isoformat(), "end_utc": END.isoformat(),
            "daily_entry_lock_pct": 1, "results": results}
