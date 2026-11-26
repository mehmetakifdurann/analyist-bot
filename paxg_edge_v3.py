"""Time-ordered PAXG swing validation using the public hourly archive."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from statistics import mean

from paxg_edge_v2 import CAPITAL, Plan, read, replay, resample, swing_view
from paxg_research import Bar, HOUR, metrics

DAY = timedelta(days=1)
NAMES = ("donchian-1d", "keltner-1d", "ema-1d", "hybrid")


@dataclass(frozen=True)
class Settings:
    entry: float
    trail: float


def swing_plans(bars: list[Bar], name: str, settings: Settings) -> dict[datetime, Plan]:
    period = 4 if name == "hybrid" else 24
    days = resample(bars,24)
    bars_for_entry = resample(bars,period) if period == 4 else days
    def calculate(items: list[Bar], hours: int, channel: int, keltner: float) -> dict:
        return {p[-1].time+hours*HOUR: swing_view(p,channel,keltner)
                for i in range(50,len(items)) if
                (p:=items[i-50:i+1])[-1].time-p[0].time == 50*hours*HOUR}
    regime = calculate(days,24,20,1.5) if period == 4 else {}
    entries = calculate(bars_for_entry,period,int(settings.entry) if name=="donchian-1d" else 20,
                        settings.entry if name in ("keltner-1d","hybrid") else 1.5)
    out = {}
    day_active = False
    day_key = None
    for t,v in entries.items():
        if period == 4:
            utc_day = t.replace(hour=0)
            if utc_day != day_key:
                d = regime.get(utc_day)
                day_active = bool(d and d.up and (day_active or d.flags[0]))
                day_key = utc_day
            take = day_active and v.flags[1]
        else:
            take = v.flags[NAMES.index(name)]
        out[t] = Plan(enter=take,atr=v.atr)
    return out


def combined(rows: list[dict]) -> dict:
    equity = peak = 1.
    dd = 0.
    returns, pnls, gross = [], [], []
    for row in rows:
        for mark in row["marks"]:
            value = equity*mark
            peak = max(peak,value)
            dd = max(dd,1-value/peak)
        equity *= math.prod(1+r for r in row["returns"])
        returns.extend(row["returns"])
        pnls.extend(row["pnls"])
        gross.extend(row["gross"])
    return {**metrics(returns,pnls,dd), "gross_expectancy_usdt": mean(gross) if gross else None}


def research(path: Path) -> dict:
    source = read(path)
    start = source[0].time.replace(hour=0)+DAY
    end = (source[-1].time+HOUR).replace(hour=0)
    oos = start+366*DAY
    folds = []
    while oos+90*DAY <= end:
        right = min(end,oos+182*DAY)
        folds.append((oos-366*DAY,oos-DAY,oos,right))
        oos = right
    if not folds:
        raise ValueError("Archive too short for an IS/OOS fold")
    report = {}
    for name in (*NAMES,"buy_hold"):
        entries = (15,20,25) if name=="donchian-1d" else (1.,1.5,2.) if name in ("hybrid","keltner-1d") else (0.,)
        choices = [Settings(a,t) for a,t in product(entries,(2.5,3.,3.5))] if name!="buy_hold" else [Settings(0,3.)]
        base = Settings(20 if name=="donchian-1d" else 1.5 if len(entries)>1 else 0,3.)
        books = {s:swing_plans(source,name,s) if name!="buy_hold" else {} for s in choices}
        tests = []
        fixed_oos: dict[int,list[dict]] = {12:[],26:[],36:[]}
        running: dict[int,list[dict]] = {12:[],26:[],36:[]}

        def simulate(lo: datetime, hi: datetime, cfg: Settings, cost: int, cap: float = CAPITAL) -> dict:
            return replay(source,books[cfg],name,cost,lo,hi,capital=cap,trail_atr=cfg.trail,
                          allow_gaps=True,detail=True)

        for a,b,c,d in folds:
            train = {s:simulate(a,b,s,26) for s in choices}
            # Penalize training drawdown and require at least three completed trades in training.
            eligible = [s for s in choices if train[s]["trades"] >= 3]
            picked = max(eligible,key=lambda s:train[s]["net_return_pct"]-train[s]["max_drawdown_pct"]) if eligible else base
            if name=="buy_hold":
                continue
            row = {"training": [a.isoformat(),b.isoformat()],"oos": [c.isoformat(),d.isoformat()],
                   "config":asdict(picked),"fallback":not eligible,
                   "train_return_pct":train[picked]["net_return_pct"],"train_trades":train[picked]["trades"],
                   "results":{}}
            for cost,runs in running.items():
                result = simulate(c,d,picked,cost,runs[-1]["ending_usdt"] if runs else CAPITAL)
                row["results"][cost] = combined([result])
                runs.append(result)
                fixed = fixed_oos[cost]
                fixed.append(simulate(c,d,base,cost,fixed[-1]["ending_usdt"] if fixed else CAPITAL))
            tests.append(row)
        if name=="buy_hold":
            for cost in running:
                running[cost].append(simulate(folds[0][2],folds[-1][3],base,cost))
        report[name] = {"folds":tests,"aggregate":{k:combined(r) for k,r in running.items()}}
        if name != "buy_hold":
            report[name]["fixed_default_oos"] = {k:combined(v) for k,v in fixed_oos.items()}
        two_year_start = datetime.fromisoformat("2024-11-25T00:00:00+00:00")
        report[name]["same_two_year_window"] = {
            cost: combined([simulate(two_year_start,datetime.fromisoformat("2026-11-25T00:00:00+00:00"),base,cost)]) for cost in running}

    return {"archive_first":source[0].time.isoformat(),"archive_last":source[-1].time.isoformat(),
            "archive_candles":len(source),"folds":len(folds),"oos_first":folds[0][2].isoformat(),
            "oos_until":folds[-1][3].isoformat(),"results":report}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv",type=Path)
    p.add_argument("--paper-parity", action="store_true", help="Replay the live paper engine on synthetic historical books")
    args = p.parse_args()
    if args.paper_parity:
        from paper_parity import END, START, parity
        candles = read(args.csv)
        report = {"start_utc": START.isoformat(), "end_utc": END.isoformat(),
                  "results": {name: {path: parity(candles,name,path=="high_first")
                                     for path in ("low_first","high_first")}
                              for name in ("keltner-1d","ema-1d")}}
    else:
        report = research(args.csv)
    print(json.dumps(report,indent=2,allow_nan=False))
