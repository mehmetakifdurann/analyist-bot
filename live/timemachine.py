"""Close-to-close historical bootstrap for paper signal diagnostics."""
from datetime import timedelta
import math
from random import Random
from typing import Sequence

from spot_data import Candle

HISTORY_HOURS = 180 * 24
PATHS = 10_000
HORIZON = 168


def simulate(returns: Sequence[float], entry: float, stop: float, target: float,
             *, seed: int = 42, paths: int = PATHS, hours: int = HORIZON) -> dict:
    if (not returns or not all(math.isfinite(r) and r > -1 for r in returns)
            or not all(map(math.isfinite, (entry, stop, target)))
            or not 0 < stop < entry < target or min(paths, hours) < 1):
        raise ValueError("Invalid bootstrap inputs")
    rng = Random(seed)
    targets = stops = 0
    total = 0.
    risk = entry-stop
    factors = [1+r for r in returns]
    pick = rng.choice
    for _ in range(paths):
        price = entry
        for _ in range(hours):
            price *= pick(factors)
            if price >= target:
                targets += 1
                price = target
                break
            if price <= stop:
                stops += 1
                price = stop
                break
        total += (price-entry)/risk
    expected = total/paths
    return dict(p_target_pct=100*targets/paths, p_stop_pct=100*stops/paths,
                p_open_pct=100*(paths-targets-stops)/paths,expected_r=expected,
                label="edge" if expected > .1 else "unfavorable" if expected < -.1 else "coin_flip",
                paths=paths,horizon_hours=hours,seed=seed,sample_hours=len(returns))


def diagnose(candles: Sequence[Candle], entry: float, stop: float, target: float,
             *, seed: int = 42) -> dict:
    history = candles[-HISTORY_HOURS-1:]
    if len(history) != HISTORY_HOURS+1 or any(
            b.time-a.time != timedelta(hours=1) for a,b in zip(history,history[1:])):
        return {"status":"requires_180_contiguous_closed_days"}
    returns = [float(b.close/a.close-1) for a,b in zip(history,history[1:])]
    return simulate(returns,entry,stop,target,seed=seed)
