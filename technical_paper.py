"""Offline educational PAXG Spot replay. All prices and trades are historical or simulated."""
from __future__ import annotations

import csv
import json
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
HOUR = timedelta(hours=1)
CAPITAL = 10_000.0
POSITION_CAP = 0.25
RISK_BUDGET = 0.005
MAX_HOLD = 12
COST = 0.0052
TARGET_TRY_PER_HOUR = (200, 300)
PERIODS = (("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-10-01"),
           ("2026-10-01", "2026-11-25"))


def levels(history):
    """Use completed bars only and exclude the signal bar from support and resistance."""
    closes = [bar["close"] for bar in history]
    ema = closes[0]
    for close in closes[1:]:
        previous_ema, ema = ema, ema + (close - ema) * 2 / 21
    prior = list(history)[-21:-1]
    last = history[-1]
    window = list(history)[-15:]
    atr = sum(max(b["high"] - b["low"], abs(b["high"] - a["close"]),
                  abs(b["low"] - a["close"])) for a, b in zip(window, window[1:])) / 14
    return {
        "close": last["close"], "ema20": ema, "ema_rising": ema > previous_ema,
        "sma50": sum(closes[-50:]) / 50,
        "sma_rising": sum(closes[-50:]) > sum(closes[-51:-1]),
        "support20": min(bar["low"] for bar in prior),
        "resistance20": max(bar["high"] for bar in prior),
        "atr14": atr,
        "relative_volume": last["volume"] / max(1e-9, median(b["volume"] for b in prior)),
    }


def entry(signal, next_open, cost):
    if not (signal["close"] > signal["ema20"] > signal["sma50"]
            and signal["ema_rising"] and signal["sma_rising"]):
        return "trend", None
    atr = signal["atr14"]
    resistance = signal["resistance20"]
    if atr <= 0 or signal["close"] <= resistance + 0.1 * atr:
        return "no_breakout", None
    if signal["relative_volume"] < 1.25:
        return "volume", None
    if not resistance <= next_open <= resistance + atr:
        return "gap_or_chasing", None
    stop = max(signal["support20"], resistance - atr)
    risk = next_open - stop
    reward = 2 * atr
    if risk <= 0 or reward - next_open * cost < 1.5 * (risk + next_open * cost):
        return "cost_adjusted_reward_risk", None
    return "entry", (stop, next_open + reward)


def replay(bars, lower, upper, cost):
    start, end = (datetime.fromisoformat(x + "T00:00:00+00:00") for x in (lower, upper))
    # A gap makes the timing and prices of a pending exit unknowable.
    window = [bar for bar in bars if start - 120 * HOUR <= bar["time"] < end]
    if (len(window) != int((end - start) / HOUR) + 120
            or any(b["time"] - a["time"] != HOUR for a, b in zip(window, window[1:]))):
        raise ValueError(f"Incomplete hourly archive for {lower} to {upper}")
    cash = peak = CAPITAL
    drawdown = 0.0
    record, reasons, equity_curve = [], Counter(), []
    position = None
    history = deque(maxlen=120)

    def close(price, time, reason):
        nonlocal cash, position
        proceeds = position["units"] * price * (1 - cost / 2)
        cash += proceeds
        record.append({**position, "exit_time": time.isoformat(), "exit_price": price,
                       "exit_reason": reason, "pnl": proceeds - position["spent"]})
        position = None

    for i, bar in enumerate(window):
        if bar["time"] >= start:
            sig = levels(history)
            if position:
                age = (bar["time"] - datetime.fromisoformat(position["entry_time"])) / HOUR
                reason = ("stop" if sig["close"] <= position["stop"] else
                          "target" if sig["close"] >= position["target"] else
                          "trend_exit" if sig["close"] < sig["ema20"] else
                          "time_limit" if age >= MAX_HOLD else None)
                if reason:
                    close(bar["open"], bar["time"], reason)
            elif i < len(window) - 1:
                reason, setup = entry(sig, bar["open"], cost)
                reasons[reason] += 1
                if setup:
                    stop, target = setup
                    paid = bar["open"] * (1 + cost / 2)
                    units = min(cash * POSITION_CAP / paid,
                                cash * RISK_BUDGET / (paid - stop * (1 - cost / 2)))
                    spent = units * paid
                    cash -= spent
                    position = {"signal_bar_open_utc": history[-1]["time"].isoformat(),
                                "entry_time": bar["time"].isoformat(), "entry_price": bar["open"],
                                "stop": stop, "target": target, "units": units, "spent": spent,
                                "signal": sig}
            value = cash + (position["units"] * bar["close"] * (1 - cost / 2) if position else 0)
            equity_curve.append(value)
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak)
        history.append(bar)

    if position:
        close(window[-1]["close"], end, "end_of_window")
    hours = int((end - start) / HOUR)
    return {"period": [lower, upper], "hours": hours, "end_balance_nominal": cash,
            "net_nominal": cash - CAPITAL, "nominal_per_hour": (cash - CAPITAL) / hours,
            "max_hourly_drawdown_pct": drawdown * 100, "decisions": reasons,
            "wins": sum(t["pnl"] > 0 for t in record), "trades": record,
            "equity_curve": equity_curve[:-1] + [cash]}


def load_bars(path):
    with path.open() as stream:
        return [{"time": datetime.fromisoformat(row["timestamp"]),
                 **{k: float(row[k]) for k in ("open", "high", "low", "close")},
                 "volume": float(row["quote_volume"])} for row in csv.DictReader(stream)]


if __name__ == "__main__":
    bars = load_bars(ROOT / "data/training/PAXGUSDT_1h.csv")
    print(json.dumps({"market": "PAXGUSDT", "mode": "historical_paper",
                      "target_try_per_hour": TARGET_TRY_PER_HOUR,
                      "currency_model": "nominal units, constant USDT/TRY; no historical TRY fills",
                      "research": {f"{cost * 10000:.0f}_bps": [
                          replay(bars, a, b, cost) for a, b in PERIODS]
                          for cost in (0, COST, COST * 2)}}, indent=2))
