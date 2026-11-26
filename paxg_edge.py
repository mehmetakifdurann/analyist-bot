"""Compare two PAXG Spot setups with passive-entry simulation and chronological tests."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from statistics import mean, pstdev
from typing import Sequence

from paxg_research import Bar, Config, HOUR, Signal, indicators, metrics
from technical_paper import load_bars

CAPITAL = 10_000.
START = datetime.fromisoformat("2024-11-25T00:00:00+00:00")
END = datetime.fromisoformat("2026-11-25T00:00:00+00:00")
WARMUP = 200


@dataclass(frozen=True)
class Setup:
    family: str
    depth: float
    target_atr: float
    expiry: int
    stop_atr: float
    strong_reclaim: bool


@dataclass(frozen=True)
class Costs:
    maker_bps: float = 10.
    taker_bps: float = 10.
    stop_slip_bps: float = 6.
    penetration_bps: float = 2.

    @property
    def taker_out(self) -> float:
        return (1 - self.taker_bps / 10000) * (1 - self.stop_slip_bps / 10000)


@dataclass(frozen=True)
class Order:
    limit: float
    stop: float
    target: float
    expires: int


def orders(bars: Sequence[Bar], setup: Setup, signals: Sequence[Signal | None]) -> list[Order | None]:
    out = []
    for i, (bar, sig) in enumerate(zip(bars, signals)):
        order = None
        if sig is not None and sig.atr > 0:
            atr = sig.atr
            if setup.family == "pullback":
                valid = (sig.mtf_up and bar.low <= sig.ema + setup.depth*atr
                         and bar.close > sig.ema and bar.close > bar.open)
                level = sig.ema
            else:
                closes = [b.close for b in bars[i-20:i]]
                center, deviation = mean(closes), pstdev(closes)
                lower = center - setup.depth*deviation
                reclaimed = [level for level in (lower, sig.support) if bar.low < level < bar.close]
                valid = sig.adx <= 25 and bar.close > bar.open and bool(reclaimed)
                level = max(reclaimed, default=0.)
            close_location = (bar.close-bar.low) / max(bar.high-bar.low, 1e-12)
            if valid and (not setup.strong_reclaim or close_location >= .75):
                limit = min(level, bar.close - .10*atr)
                stop = min(bar.low, limit) - setup.stop_atr*atr
                if stop > 0:
                    order = Order(limit, stop, limit + setup.target_atr*atr, i+1+setup.expiry)
        out.append(order)
    return out


def passive_fill(bar: Bar, p: Order, costs: Costs) -> bool:
    # Cancel if marketable at the sampled open; a touch alone never proves queue execution.
    return bar.open > p.limit and bar.low < p.limit*(1-costs.penetration_bps/10000)


def replay(bars: Sequence[Bar], signals: Sequence[Order | None], left: int, right: int,
           costs: Costs, capital: float = CAPITAL) -> dict:
    balance = previous = capital
    seen: list[float] = []
    returns, pnls = [], []
    friction = 0.
    counts: Counter[str] = Counter()
    pending = None
    position = None
    maker = 1-costs.maker_bps/10000

    def mark(value: float) -> None:
        seen.append(value/capital)

    for i in range(left, right):
        bar = bars[i]
        if position is None:
            if pending is not None and i >= pending.expires:
                counts["expired"] += 1
                pending = None
            if pending is None and i < right-1 and i > left:
                p = signals[i-1]
                if p:
                    paid = p.limit / maker  # fee deducted from base received
                    risk = paid-p.stop*costs.taker_out
                    if risk > 0 and p.target*maker-paid >= risk:
                        pending = p
                        pending_expiry = p.expires-i
                        counts["submitted"] += 1
                    else:
                        counts["cost_or_reward_risk"] += 1
        filled_now = False
        if pending:
            resting = i > pending.expires - pending_expiry
            if bar.open <= pending.limit and not resting:
                counts["marketable_cancel"] += 1
                pending = None
            elif passive_fill(bar, pending, costs) or (resting and bar.open < pending.limit):
                paid = pending.limit/maker
                units = min(balance*.25/paid, balance*.005/(paid-pending.stop*costs.taker_out))
                balance -= units*paid
                position = pending, units, paid, i
                counts["filled"] += 1
                pending = None
                filled_now = True
        if position:
            p, units, paid, opened = position
            exit_price = None
            factor = costs.taker_out
            if not filled_now and bar.open <= p.stop:
                exit_price, reason = bar.open, "stop_gap"
            elif not filled_now and bar.open > p.target*(1+costs.penetration_bps/10000):
                exit_price, factor, reason = p.target, maker, "target_gap"
            elif filled_now and bar.open < p.stop:
                exit_price, reason = bar.open, "entry_gap_stop"
            elif bar.low <= p.stop:
                exit_price, reason = p.stop, "stop"
            elif not filled_now and bar.high > p.target*(1+costs.penetration_bps/10000):
                mark(balance + units*bar.low*costs.taker_out)
                exit_price, factor, reason = p.target, maker, "target"
            elif i-opened >= 24 or i == right-1:
                mark(balance + units*bar.low*costs.taker_out)
                exit_price, reason = bar.close, "boundary" if i == right-1 else "time_exit"
            else:
                mark(balance + units*bar.low*costs.taker_out)
            if exit_price is not None:
                balance += units*exit_price*factor
                pnls.append(units*(exit_price*factor-paid))
                friction += units*((paid-p.limit) + exit_price*(1-factor))
                counts[reason] += 1
                position = None
        equity = balance if position is None else balance+position[1]*bar.close*costs.taker_out
        mark(equity)
        returns.append(equity/previous-1)
        previous = equity
    if pending:
        counts["boundary_cancel"] += 1
    return {"marks": seen, "returns": returns, "pnls": pnls, "cash": balance, "orders": counts, "friction_usdt": friction}


def summarize(runs: Sequence[dict]) -> dict:
    peak = equity = 1.
    worst = 0.
    totals: Counter[str] = Counter()
    returns, pnls = [], []
    for run in runs:
        for relative in run["marks"]:
            mark = equity*relative
            peak = max(peak, mark)
            worst = max(worst, 1-mark/peak)
        equity *= math.prod(1+r for r in run["returns"])
        returns.extend(run["returns"])
        pnls.extend(run["pnls"])
        totals.update(run["orders"])
    return {**metrics(returns, pnls, worst), "orders": totals,
            "execution_drag_usdt": sum(run["friction_usdt"] for run in runs),
            "pnl_before_execution_drag_same_fills_usdt": sum(pnls) + sum(run["friction_usdt"] for run in runs)}


def passes(result: dict) -> bool:
    return (result["trades"] >= 50 and (result["profit_factor"] or 0) > 1.30
            and result["net_return_pct"] > 0 and (result["sharpe"] or 0) > 0)


def research(path: Path) -> dict:
    bars = [Bar(**row) for row in load_bars(path) if START-WARMUP*HOUR <= row["time"] < END]
    if (not bars or bars[0].time != START-WARMUP*HOUR or bars[-1].time != END-HOUR
            or any(b.time-a.time != HOUR for a, b in zip(bars,bars[1:]))):
        raise ValueError("Expected continuous two-year hourly PAXG archive with 200 warmup candles")
    if any(not all(math.isfinite(x) for x in (b.low,b.high,b.open,b.close,b.volume))
           or not 0 < b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high
           or b.volume < 0 for b in bars):
        raise ValueError("Invalid OHLCV")
    costs = Costs()
    stressed = Costs(12, 12, 12, 5)
    folds = range(WARMUP+180*24, len(bars), 60*24)
    views = indicators(bars, Config())
    results = {}
    families = (("pullback", (0., .25, .5)), ("mean_reversion", (1.5, 2., 2.5)))
    for (family, depths), strong in product(families, (False, True)):
        name = family + ("_strong_reclaim" if strong else "")
        configs = [Setup(family,d,t,e,s,strong) for d,t,e,s in product(depths,(2.,3.,4.),(1,3),(.5,1.))]
        prepared = {c: orders(bars,c,views) for c in configs}
        family_rows = []
        base_runs, stress_runs = [], []
        for left in folds:
            right = min(left+60*24,len(bars))
            train_end = left-24
            train_start = train_end-179*24
            scored = {c: summarize([replay(bars,prepared[c],train_start,train_end,costs)])
                      for c in configs}
            eligible = [(c,s) for c,s in scored.items() if s["trades"] >= 15]
            # Always produce a research comparison, even when no training result meets the deployment gate.
            def score(item: tuple[Setup, dict]) -> tuple[float, float, int]:
                c, s = item
                neighbors = [v["net_return_pct"] for n,v in scored.items() if
                             sum(getattr(n,k) != getattr(c,k) for k in ("depth","target_atr","expiry","stop_atr")) <= 1]
                return mean(neighbors), s["net_return_pct"], s["trades"]
            winner = max(eligible or list(scored.items()), key=score)[0]
            a = replay(bars,prepared[winner],left,right,costs,base_runs[-1]["cash"] if base_runs else CAPITAL)
            b = replay(bars,prepared[winner],left,right,stressed,stress_runs[-1]["cash"] if stress_runs else CAPITAL)
            base_runs.append(a)
            stress_runs.append(b)
            family_rows.append({"train_from": bars[train_start].time.isoformat(),
                "train_to_exclusive": bars[train_end].time.isoformat(),
                "test_from": bars[left].time.isoformat(),
                "test_to_exclusive": (bars[right-1].time+HOUR).isoformat(),
                "config": asdict(winner), "training_gate_15_met": bool(eligible),
                "training": scored[winner], "test": summarize([a]), "stress": summarize([b])})
        base, stress = summarize(base_runs), summarize(stress_runs)
        results[name] = {"tested_settings": len(configs), "folds": family_rows,
                           "oos": base, "stress_oos": stress, "passes": passes(base), "passes_stress": passes(stress)}
    candidates = [k for k, row in results.items() if row["passes"]]
    return {"symbol": "PAXGUSDT", "market": "Spot", "currency": "USDT",
            "archive_bars": len(bars)-WARMUP, "costs": asdict(costs), "stress_costs": asdict(stressed),
            "online_eligible_family": max(candidates, key=lambda k: results[k]["oos"]["profit_factor"]) if candidates else None, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    print(json.dumps(research(args.csv), indent=2, allow_nan=False))
