"""Offline PAXG/USDT Spot breakout research on completed hourly candles."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Sequence
from zoneinfo import ZoneInfo

from technical_paper import load_bars, replay as legacy_replay

HOUR = timedelta(hours=1)
START = datetime.fromisoformat("2026-04-01T00:00:00+00:00")
END = datetime.fromisoformat("2026-11-25T00:00:00+00:00")
LONDON, NEW_YORK = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
CAPITAL = 10_000.0


@dataclass(frozen=True)
class Config:
    ema: int = 20
    channel: int = 20
    relative_volume: float = 1.25
    stop_atr: float = 1
    target_atr: float = 2
    maker_fee_bps: float = 10
    taker_fee_bps: float = 10
    slippage_bps: float = 16
    volatility_slip: float = 0
    adx_min: float = 0
    overlap: bool = False
    mtf: bool = False
    breakeven_r: float = 0
    partial: bool = False
    trailing: bool = False
    circuit: bool = False

    def __post_init__(self) -> None:
        if (not 2 <= self.ema < 50 or not 2 <= self.channel < 120
                or not all(math.isfinite(v) and v > 0 for v in
                           (self.relative_volume, self.stop_atr, self.target_atr))
                or not all(math.isfinite(v) and 0 <= v < 1000 for v in
                           (self.maker_fee_bps, self.taker_fee_bps, self.slippage_bps,
                            self.volatility_slip, self.adx_min, self.breakeven_r))):
            raise ValueError("Invalid research configuration")


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    close: float
    ema: float
    sma: float
    trend: bool
    support: float
    resistance: float
    atr: float
    relative_volume: float
    adx: float
    mtf_up: bool


@dataclass
class Position:
    entry_time: datetime
    units: float
    paid: float
    stop: float
    target: float
    one_r: float
    peak: float
    hold: int
    initial_risk: float
    partial_done: bool = False
    realized: float = 0


def wilder_adx(bars: Sequence[Bar]) -> list[float]:
    n = 14
    tr = plus = minus = adx = 0.0
    dx_seed: list[float] = []
    result = [0.0]
    for i, (a, b) in enumerate(zip(bars, bars[1:]), 1):
        up, down = b.high - a.high, a.low - b.low
        r = max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        p, m = (up if up > max(0, down) else 0), (down if down > max(0, up) else 0)
        if i <= n:
            tr, plus, minus = tr + r, plus + p, minus + m
        else:
            tr, plus, minus = tr * (1 - 1/n) + r, plus * (1 - 1/n) + p, minus * (1 - 1/n) + m
        if i >= n:
            dx = 100 * abs(plus - minus) / (plus + minus) if tr and plus + minus else 0
            if len(dx_seed) < n:
                dx_seed.append(dx)
                if len(dx_seed) == n:
                    adx = mean(dx_seed)
            else:
                adx += (dx - adx) / n
        result.append(adx)
    return result


def indicators(bars: Sequence[Bar], cfg: Config) -> list[Signal | None]:
    if len(bars) < max(51, cfg.channel + 1):
        raise ValueError("Not enough completed candles for SMA and channel")
    ema = mean(bar.close for bar in bars[:cfg.ema])
    adx = wilder_adx(bars)
    four_hour_closes: list[float] = []
    result = []
    for i, bar in enumerate(bars):
        previous_ema = ema
        if i >= cfg.ema:
            ema += (bar.close - ema) * 2 / (1 + cfg.ema)
        if bar.time.hour % 4 == 3 and i >= 3:
            four_hour_closes.append(bar.close)
        if i < max(50, cfg.channel):
            result.append(None)
            continue
        prior = bars[i-cfg.channel:i]
        sma = mean(b.close for b in bars[i-49:i+1])
        atr = mean(max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close))
                   for a, b in zip(bars[i-14:i], bars[i-13:i+1]))
        mtf_up = (len(four_hour_closes) >= 21 and
                  four_hour_closes[-1] > mean(four_hour_closes[-20:]) and
                  four_hour_closes[-1] > four_hour_closes[-21])
        result.append(Signal(bar.close, ema, sma,
                             bar.close > ema > sma and ema > previous_ema and bar.close > bars[i-50].close,
                             min(b.low for b in prior), max(b.high for b in prior), atr,
                             bar.volume / max(1e-9, median(b.volume for b in prior)), adx[i], mtf_up))
    return result


def sell_factor(cfg: Config, slip: float, maker: bool = False) -> float:
    if maker:
        return 1 - cfg.maker_fee_bps / 10_000
    return (1 - slip) * (1 - cfg.taker_fee_bps / 10_000)


def levels_hit(bar: Bar, stop: float, target: float) -> tuple[str, float] | None:
    if bar.open <= stop:
        return "stop_gap", bar.open
    if bar.open >= target:
        return "target", target
    if bar.low <= stop:
        return "stop", stop
    if bar.high >= target:
        return "target", target
    return None


def overlap_hour(stamp: datetime) -> bool:
    london, ny = stamp.astimezone(LONDON), stamp.astimezone(NEW_YORK)
    return london.weekday() < 5 and 8 <= london.hour < 17 and (ny.hour, ny.minute) >= (9, 30) and ny.hour < 16


def metrics(returns: Sequence[float], pnls: Sequence[float], drawdown: float) -> dict:
    growth = math.prod(1 + r for r in returns)
    avg = mean(returns) if returns else 0
    vol = pstdev(returns) if returns else 0
    downside = math.sqrt(mean(min(0, r)**2 for r in returns)) if returns else 0
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    streak = longest = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        longest = max(longest, streak)
    annualized = math.expm1(math.log(growth) * 8760 / len(returns)) if returns else 0
    return {"hours": len(returns), "trades": len(pnls), "net_return_pct": 100*(growth-1),
            "win_rate_pct": 100*len(wins)/len(pnls) if pnls else None,
            "avg_win_usdt": mean(wins) if wins else None,
            "avg_loss_usdt": mean(losses) if losses else None,
            "profit_factor": sum(wins)/-sum(losses) if losses else None,
            "expectancy_usdt": mean(pnls) if pnls else None,
            "sharpe": avg/vol*math.sqrt(8760) if vol else None,
            "sortino": avg/downside*math.sqrt(8760) if downside else None,
            "calmar": annualized/drawdown if drawdown else None,
            "max_drawdown_pct": 100*drawdown, "max_loss_streak": longest}


def simulate(bars: Sequence[Bar], signals: Sequence[Signal | None], cfg: Config,
             left: int, right: int, capital: float = CAPITAL) -> dict:
    cash = prior_equity = peak = day_equity = week_equity = capital
    worst = 0.0
    returns, pnls, marks = [], [], []
    reasons: Counter[str] = Counter()
    pos: Position | None = None
    loss_streak = 0
    cooldown = left
    day = week = None
    day_locked = week_locked = False

    def mark(value: float) -> None:
        nonlocal peak, worst
        marks.append(value / capital)
        peak = max(peak, value)
        worst = max(worst, 1 - value/peak)

    def exit_units(price: float, factor: float, share: float, i: int) -> None:
        nonlocal cash, pos, loss_streak, cooldown
        assert pos is not None
        units = pos.units * share
        pos.units -= units
        cash += units * price * factor
        pos.realized += units * (price * factor - pos.paid)
        if share == 1:
            pnl = pos.realized
            pnls.append(pnl)
            loss_streak = loss_streak + 1 if pnl < 0 else 0
            if cfg.circuit and loss_streak >= 3:
                cooldown = i + 25
                loss_streak = 0
            pos = None

    for i in range(left, right):
        bar, sig = bars[i], signals[i-1]
        assert sig is not None
        if bar.time.date() != day:
            day, day_equity, day_locked = bar.time.date(), prior_equity, False
        key = bar.time.isocalendar()[:2]
        if key != week:
            week, week_equity, week_locked = key, prior_equity, False
        slip = (cfg.slippage_bps + min(35, cfg.volatility_slip * 10_000 * sig.atr/sig.close))/10_000
        taker = sell_factor(cfg, slip)
        open_equity = cash + (pos.units * bar.open * taker if pos else 0)
        if cfg.circuit:
            day_locked |= open_equity <= day_equity * 0.99
            week_locked |= open_equity <= week_equity * 0.975
        had_position = pos is not None
        if pos:
            opening_hit = levels_hit(replace(bar, low=bar.open, high=bar.open), pos.stop, pos.target)
            if opening_hit:
                reason, price = opening_hit
                reasons[reason] += 1
                exit_units(price, sell_factor(cfg, slip, maker=reason == "target"), 1, i)
            elif ((bar.time - pos.entry_time)/HOUR >= pos.hold
                  or (not cfg.trailing and sig.close < sig.ema) or day_locked or week_locked):
                reasons["open_exit"] += 1
                exit_units(bar.open, taker, 1, i)
        if not had_position and i < right - 1:
            resistance, atr = sig.resistance, sig.atr
            if day_locked or week_locked or i < cooldown:
                reasons["circuit"] += 1
            elif not sig.trend or sig.adx < cfg.adx_min or (cfg.mtf and not sig.mtf_up):
                reasons["trend_or_regime"] += 1
            elif cfg.overlap and not overlap_hour(bar.time):
                reasons["session"] += 1
            elif (atr <= 0 or sig.close <= resistance + .1*atr or
                  sig.relative_volume < cfg.relative_volume or not resistance <= bar.open <= resistance + atr):
                reasons["breakout_volume_or_gap"] += 1
            else:
                paid = bar.open * (1 + slip) * (1 + cfg.taker_fee_bps/10_000)
                stop = max(sig.support, resistance - cfg.stop_atr*atr)
                target = bar.open + cfg.target_atr*atr
                risk = paid - stop*taker
                reward = target*sell_factor(cfg, slip, maker=True) - paid
                if risk <= 0 or stop >= bar.open or reward < 1.5*risk:
                    reasons["net_reward_risk"] += 1
                else:
                    scale = min(1., .004*sig.close/atr) if cfg.circuit else 1.
                    units = min(cash/paid, open_equity*.25/paid, open_equity*.005*scale/risk)
                    if units > 0:
                        cash -= units*paid
                        one_r = (paid+risk)/sell_factor(cfg, slip, maker=True)
                        hold = max(12, min(36, round(12*sig.adx/20))) if cfg.trailing else 12
                        pos = Position(bar.time, units, paid, stop, target, one_r, bar.open, hold, risk)
                        reasons["entry"] += 1
        if pos:
            hit = levels_hit(bar, pos.stop, pos.target)
            if hit and hit[0].startswith("stop"):
                mark(cash + pos.units*hit[1]*taker)
                reasons[hit[0]] += 1
                exit_units(hit[1], taker, 1, i)
            else:
                mark(cash + pos.units*bar.low*taker)
                if cfg.partial and not pos.partial_done and bar.high >= pos.one_r:
                    exit_units(pos.one_r, sell_factor(cfg, slip, maker=True), .5, i)
                    assert pos is not None
                    pos.partial_done = True
                    reasons["partial"] += 1
                if hit:
                    reasons["target"] += 1
                    exit_units(hit[1], sell_factor(cfg, slip, maker=True), 1, i)
                else:
                    pos.peak = max(pos.peak, bar.high)
                    if cfg.breakeven_r and bar.high * taker >= pos.paid + cfg.breakeven_r*pos.initial_risk:
                        pos.stop = max(pos.stop, pos.paid/taker)
                    if cfg.trailing:
                        pos.stop = max(pos.stop, pos.peak-3*sig.atr)
        if i == right - 1 and pos:
            exit_units(bar.close, taker, 1, i)
            reasons["boundary"] += 1
        equity = cash + (pos.units*bar.close*taker if pos else 0)
        mark(equity)
        if cfg.circuit:
            day_locked |= equity <= day_equity*.99
            week_locked |= equity <= week_equity*.975
        returns.append(equity/prior_equity-1)
        prior_equity = equity
    return {"returns": returns, "pnls": pnls, "drawdown": worst,
            "decisions": reasons, "ending_equity": prior_equity, "marks": marks}


def run_research(path: Path) -> dict:
    raw = load_bars(path)
    bars = [Bar(**row) for row in raw if START - 120*HOUR <= row["time"] < END]
    if (not bars or bars[0].time != START - 120*HOUR or bars[-1].time != END-HOUR
            or any(b.time - a.time != HOUR for a, b in zip(bars, bars[1:]))):
        raise ValueError("Expected a continuous UTC hourly archive including warmup")
    for b in bars:
        if (not all(math.isfinite(x) for x in (b.open, b.high, b.low, b.close, b.volume))
                or not 0 < b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
                or b.volume < 0):
            raise ValueError(f"Invalid OHLCV at {b.time}")
    base = Config()
    dynamic = replace(base, slippage_bps=4, volatility_slip=.5)
    regime = replace(dynamic, adx_min=22)
    session = replace(regime, overlap=True)
    mtf = replace(regime, mtf=True)
    be = replace(mtf, breakeven_r=1)
    partial = replace(be, partial=True)
    trail = replace(partial, trailing=True)
    full = replace(trail, circuit=True)
    stages = {"corrected": base, "dynamic_cost": dynamic, "adx": regime, "session": session,
              "mtf": mtf, "session_and_mtf": replace(mtf, overlap=True),
              "breakeven": be, "partial": partial, "trailing_and_hold": trail, "circuit": full}
    stress = replace(full, maker_fee_bps=20, taker_fee_bps=20,
                     slippage_bps=8, volatility_slip=1)
    stages["higher_cost_stress"] = stress
    participation = {
        name + "_6atr": replace(cfg, target_atr=6)
        for name, cfg in stages.items() if name != "higher_cost_stress"
    }
    participation["breakeven_1_5r_6atr"] = replace(be, target_atr=6, breakeven_r=1.5)
    participation["higher_cost_stress_6atr"] = replace(stress, target_atr=6)
    stages.update(participation)
    full = replace(full, target_atr=4)
    grid = {"ema": (16, 20, 24), "channel": (16, 20, 24), "relative_volume": (1., 1.25, 1.5),
            "stop_atr": (.75, 1., 1.25), "target_atr": (2., 4., 6.)}
    variants = {full, *(replace(full, **{k: v}) for k, values in grid.items() for v in values)}
    # For the target sweep, include neighbors in both directions around each tested center.
    cache: dict[tuple[int, int], list[Signal | None]] = {}

    def run(c: Config, left: int, right: int, capital: float) -> dict:
        key = c.ema, c.channel
        if key not in cache:
            cache[key] = indicators(bars, c)
        return simulate(bars, cache[key], c, left, right, capital)

    def row(a: dict) -> dict:
        return {**metrics(a["returns"], a["pnls"], a["drawdown"]), "decisions": a["decisions"]}

    def legacy(left: int, right: int) -> dict:
        begin = bars[left].time.date().isoformat()
        end = (bars[right-1].time + HOUR).date().isoformat()
        a = legacy_replay(raw, begin, end, .0052)
        equity = [CAPITAL, *a["equity_curve"]]
        return {"returns": [y/x-1 for x,y in zip(equity,equity[1:])],
                "pnls": [t["pnl"] for t in a["trades"]],
                "drawdown": a["max_hourly_drawdown_pct"]/100,
                "decisions": a["decisions"], "ending_equity": equity[-1],
                "marks": [v/CAPITAL for v in equity[1:]]}

    logs: dict[str, list] = defaultdict(list)
    picks = []
    for left in range(120+84*24, len(bars), 28*24):
        right = min(left+28*24, len(bars))
        train_right = left-24
        train_left = train_right-83*24
        settings = sorted(variants, key=lambda c: tuple(asdict(c).values()))
        sensitivity = {c: row(run(c, train_left, train_right, CAPITAL)) for c in settings}

        def one_change(a: Config, b: Config) -> bool:
            return sum(getattr(a, k) != getattr(b, k) for k in grid) == 1

        eligible = []
        for c in settings:
            neighbors = [sensitivity[n] for n in settings if one_change(n, c)]
            own = sensitivity[c]
            good = [n for n in neighbors if n["trades"] >= 5 and n["net_return_pct"] > 0]
            if own["trades"] >= 5 and own["net_return_pct"] > 0 and len(good) >= max(2, len(neighbors)//2+1):
                eligible.append((median(n["net_return_pct"] for n in neighbors), c))
        selected = max(eligible, key=lambda x: x[0])[1] if eligible else None
        picks.append({"train_from": bars[train_left].time.isoformat(),
                      "train_to_exclusive": bars[train_right].time.isoformat(),
                      "test_from": bars[left].time.isoformat(),
                      "test_to_exclusive": (bars[right-1].time + HOUR).isoformat(),
                      "selected": asdict(selected) if selected else None,
                      "sensitivity": [{"config": asdict(c), "train": sensitivity[c]} for c in settings]})
        logs["legacy"].append(legacy(left, right))
        for name, cfg in {**stages, "walk_forward": selected}.items():
            cap = logs[name][-1]["ending_equity"] if logs[name] else CAPITAL
            result = run(cfg, left, right, cap) if cfg else {
                "returns": [0.]*(right-left), "pnls": [], "drawdown": 0.,
                "decisions": {"no_training_plateau": right-left}, "ending_equity": cap, "marks": []}
            logs[name].append(result)
    totals = {}
    for name, folds in logs.items():
        returns = [r for fold in folds for r in fold["returns"]]
        realized = []
        equity = peak = 1.
        drawdown = 0.
        for fold in folds:
            factor = equity if name == "legacy" else 1.
            realized.extend(p*factor for p in fold["pnls"])
            for relative in fold["marks"]:
                level = equity*relative
                peak = max(peak, level)
                drawdown = max(drawdown, 1-level/peak)
            equity *= math.prod(1+r for r in fold["returns"])
        totals[name] = {"folds": [row(f) for f in folds],
                        "total": metrics(returns, realized, drawdown)}
    return {"market": "Binance Spot PAXGUSDT", "currency": "USDT",
            "stages": {k: asdict(v) for k,v in stages.items()},
            "walk_forward_selection": picks, "results": totals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Continuous Binance Spot PAXGUSDT 1h archive CSV")
    args = parser.parse_args()
    print(json.dumps(run_research(args.csv), indent=2, allow_nan=False))
