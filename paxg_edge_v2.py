"""Research-only PAXG Spot comparison. Inputs are closed UTC hourly candles."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev

from paxg_research import Bar, HOUR, metrics
from technical_paper import load_bars

CAPITAL = 10_000.
START = datetime.fromisoformat("2026-05-01T00:00:00+00:00")
END = datetime.fromisoformat("2026-11-25T00:00:00+00:00")
TWO_YEARS = datetime.fromisoformat("2024-11-25T00:00:00+00:00")


def resample(bars: list[Bar], hours: int) -> list[Bar]:
    if hours not in (4, 24):
        raise ValueError("Supported resolutions: 4H and 1D")
    out = []
    for i, bar in enumerate(bars):
        if bar.time.hour % hours:
            continue
        window = bars[i:i+hours]
        if len(window) != hours or any(b.time != bar.time+j*HOUR for j,b in enumerate(window)):
            continue
        out.append(Bar(bar.time, bar.open, max(b.high for b in window),
                       min(b.low for b in window), window[-1].close, sum(b.volume for b in window)))
    return out


@dataclass(frozen=True)
class View:
    atr: float
    ema: float
    up: bool
    flags: tuple[bool, bool, bool]


def views(bars: list[Bar], hours: int) -> dict[datetime, View]:
    if len(bars) < 51 or any(b.time-a.time != hours*HOUR for a,b in zip(bars,bars[1:])):
        raise ValueError("At least 51 continuous aggregate candles required")
    ema = mean(b.close for b in bars[:20])
    result = {}
    for i, bar in enumerate(bars[20:],20):
        before = ema
        ema += (bar.close-ema)*2/21
        if i >= 50:
            result[bar.time+hours*HOUR] = swing_view(bars[i-50:i+1],ema_pair=(before,ema))
    return result


def swing_view(bars: list[Bar], channel: int = 20, keltner_atr: float = 1.5,
               ema_pair: tuple[float,float] | None = None) -> View:
    """Fixed 51-bar lookback shared by the offline and streaming engines."""
    if len(bars) < 51 or not 1 <= channel < 51:
        raise ValueError("Swing indicators need 51 completed bars")
    window = bars[-51:]
    if ema_pair is None:
        ema = mean(b.close for b in window[:20])
        for bar in window[20:]:
            before = ema
            ema += (bar.close-ema)*2/21
    else:
        before, ema = ema_pair
    b = window[-1]
    atr = mean(max(y.high-y.low, abs(y.high-x.close), abs(y.low-x.close))
               for x,y in zip(window[-15:-1],window[-14:]))
    up = ema > mean(x.close for x in window[-50:]) and ema >= before
    return View(atr, ema, up, (
        b.close > max(x.high for x in window[-channel-1:-1]),
        b.close > ema + keltner_atr*atr,
        b.close > ema and up))



@dataclass(frozen=True)
class Plan:
    enter: bool = False
    exit: bool = False
    atr: float = 0.
    grid_center: float = 0.
    range_exit: bool = False


def plans(bars: list[Bar], xaut: dict, btc: dict, four: dict, day: dict) -> dict[str, dict[datetime, Plan]]:
    out = {f"{name}_{frame}": {} for frame in ("4h", "1d")
           for name in ("donchian", "keltner", "ema")}
    out.update({name: {} for name in ("spread", "spread_btc_guard", "grid")})
    current = None
    logs: list[float] = []
    for i,b in enumerate(bars):
        t = b.time
        for frame, book in (("4h", four), ("1d", day)):
            if t in book:
                v = book[t]
                for j,name in enumerate(("donchian", "keltner", "ema")):
                    out[f"{name}_{frame}"][t] = Plan(v.flags[j], False, v.atr)
        if t in four:
            current = four[t]
            out["grid"][t] = Plan(atr=current.atr, grid_center=current.ema,
                                  range_exit=not current.up)
        if i and bars[i-1].time in xaut:
            logs.append(math.log(bars[i-1].close/xaut[bars[i-1].time].close))
        else:
            logs.clear()
        if len(logs) >= 121 and current:
            ref = logs[-121:-1]
            sigma = pstdev(ref)
            z = (logs[-1]-mean(ref))/sigma if sigma else 0.
            prev = t-HOUR
            back = t-25*HOUR
            shock = prev not in btc or back not in btc or abs(btc[prev].close/btc[back].close-1) >= .06
            out["spread"][t] = Plan(z <= -2, z >= -.25, current.atr)
            out["spread_btc_guard"][t] = Plan(z <= -2 and not shock, z >= -.25 or shock, current.atr)
    return out


@dataclass
class Lot:
    amount: float
    entry: float
    cost: float
    stop: float
    target: float = math.inf
    accumulated: float = 0.
    gross_accumulated: float = 0.


def replay(bars: list[Bar], plan: dict[datetime, Plan], name: str, bps: int,
           start: datetime, end: datetime, *, capital: float = CAPITAL,
           trail_atr: float = 3., allow_gaps: bool = False,
           detail: bool = False) -> dict:
    data = [b for b in bars if start <= b.time < end]
    if not data or (not allow_gaps and len(data) != int((end-start)/HOUR)):
        raise ValueError("Incomplete evaluation interval")
    cash = peak = prev = capital
    worst = 0.
    returns, pnls, gross, marks = [], [], [], []
    lots: list[Lot] = []
    fee = .001
    slip = bps/10000-fee
    buy_factor = (1+slip)/(1-fee)
    sell_factor = (1-slip)*(1-fee)
    # Prices must pass passive limits by 2 bps. OHLC cannot establish queue priority.
    penetration = .0002
    grid: list[tuple[float, float, float]] = []
    last_atr = 0.
    high_water = 0.

    def buy(price: float, budget: float, stop: float, target: float = math.inf) -> None:
        nonlocal cash
        budget = min(cash, budget)
        if budget > 5:
            lots.append(Lot(budget/(price*buy_factor), price, budget, stop, target))
            cash -= budget

    def sell(lot: Lot, price: float, share: float = 1.) -> None:
        nonlocal cash
        proceeds = lot.amount*share*price*sell_factor
        cash += proceeds
        if share < 1:
            lot.accumulated += proceeds-lot.cost*share
            lot.gross_accumulated += lot.amount*share*(price-lot.entry)
            lot.amount *= 1-share
            lot.cost *= 1-share
            lot.target = math.inf
        else:
            pnls.append(lot.accumulated+proceeds-lot.cost)
            gross.append(lot.gross_accumulated+lot.amount*(price-lot.entry))
            lots.remove(lot)

    def mark(price: float) -> float:
        nonlocal peak, worst
        equity = cash+sum(x.amount*price*sell_factor for x in lots)
        if detail:
            marks.append(equity/capital)
        peak = max(peak,equity)
        worst = max(worst, 1-equity/peak)
        return equity

    for i,b in enumerate(data):
        last = i == len(data)-1
        setup = plan.get(b.time)
        if setup:
            last_atr = setup.atr
        opened_hybrid = False
        if name == "grid":
            if setup and setup.range_exit:
                for x in lots[:]:
                    sell(x,b.open)
                grid.clear()
            elif setup and not last:
                width = max(setup.atr, setup.grid_center*.004)
                prices = [(setup.grid_center-k*width, setup.grid_center-(k-1)*width)
                          for k in (1,2,3)]
                grid = [(p,t,setup.grid_center-4.5*width) for p,t in prices
                        if 0 < p < b.open and len(lots) < 3
                        and all(abs(x.entry-p) > .25*width for x in lots)]
        elif not last:
            if name == "buy_hold" and i == 0:
                buy(b.open,cash,0.)
            if name.startswith("spread") and setup and setup.exit and lots:
                sell(lots[0],b.open)
            if setup and setup.enter and not lots and not setup.exit and setup.atr > 0:
                opened_hybrid = name == "hybrid"
                target = b.open+2*setup.atr if opened_hybrid else math.inf
                buy(b.open,cash*.7,max(0,b.open-trail_atr*setup.atr),target)
                high_water = b.open
        exits_before = len(pnls)
        for lot in lots[:]:
            if lot.stop and b.open <= lot.stop:
                sell(lot,b.open)
            elif lot.stop and b.low <= lot.stop:
                mark(lot.stop)
                sell(lot,lot.stop)
            elif b.high > lot.target*(1+penetration) and not opened_hybrid:
                mark(b.low)
                sell(lot,lot.target,.5 if name == "hybrid" else 1.)
        # Do not fund bids with exits whose intrabar ordering relative to the low is unknown.
        if name == "grid" and not last and exits_before == len(pnls):
            for p,t,s in grid[:]:
                resting_gap = b.open < p
                if len(lots) < 3 and (resting_gap or b.low < p*(1-penetration)):
                    count = len(lots)
                    buy(p, (cash+sum(x.amount*b.open*sell_factor for x in lots))*.2, s,t)
                    grid.remove((p,t,s))
                    if len(lots) > count and b.low <= s:
                        lot = lots[-1]
                        price = min(b.open,s)
                        mark(price)
                        sell(lot,price)
        mark(b.low)
        if lots and name not in ("grid","buy_hold") and not name.startswith("spread"):
            high_water = max(high_water,b.high)
            lots[0].stop = max(lots[0].stop,high_water-trail_atr*last_atr)
        if last:
            for x in lots[:]:
                sell(x,b.close)
        now = mark(b.close)
        returns.append(now/prev-1)
        prev = now
    result = {**metrics(returns,pnls,worst), "gross_expectancy_usdt": mean(gross) if gross else None,
              "execution_drag_usdt": sum(gross)-sum(pnls), "ending_usdt": cash}
    if detail:
        result.update(returns=returns, pnls=pnls, gross=gross, marks=marks)
    return result


def read(path: Path) -> list[Bar]:
    bars = [Bar(**row) for row in load_bars(path)]
    if any(a.time >= b.time for a,b in zip(bars,bars[1:])):
        raise ValueError(f"Invalid time order in {path}")
    if any(not all(math.isfinite(x) for x in (b.low,b.high,b.open,b.close,b.volume))
           or not 0 < b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high
           or b.volume < 0 for b in bars):
        raise ValueError(f"Invalid OHLCV in {path}")
    return bars


def run(directory: Path) -> dict:
    raw = read(directory/"PAXGUSDT_1h.csv")
    bars = [b for b in raw if TWO_YEARS-75*timedelta(days=1) <= b.time < END]
    if any(b.time-a.time != HOUR for a,b in zip(bars,bars[1:])):
        raise ValueError("PAXG continuity check failed")
    xaut = {b.time:b for b in read(directory/"XAUTUSDT_1h.csv")}
    btc = {b.time:b for b in read(directory/"BTCUSDT_1h.csv")}
    setups = plans(bars,xaut,btc,views(resample(bars,4),4),views(resample(bars,24),24))
    setups["buy_hold"] = {}
    periods = {"common": START, "long": TWO_YEARS}
    return {"end": END.isoformat(), "start": {k:v.isoformat() for k,v in periods.items()},
            "cost_bps_per_side": [12,26,36],
            "results": {period:{name:{bps:replay(bars,plan,name,bps,start,END)
                                      for bps in (12,26,36)}
                               for name,plan in setups.items() if period=="common" or not name.startswith("spread")}
                        for period,start in periods.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(run(parser.parse_args().directory),indent=2,allow_nan=False))
