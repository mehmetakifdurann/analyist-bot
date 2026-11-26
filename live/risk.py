"""UTC entry lock for the simulated wallet. Existing positions keep their stops."""
from decimal import Decimal as D


def update(wallet: dict, utc_day: str, equity: D, limit: D) -> None:
    if wallet["day"] is None or utc_day > wallet["day"]:
        wallet.update(day=utc_day, start_equity=wallet.get("last_equity", str(equity)), locked=False)
    if equity <= D(wallet["start_equity"])*(1-limit):
        wallet["locked"] = True


RISK_PER_TRADE_PCT = D(".005")


def evaluate_order(*, cash: D, equity: D, units: D, paid: D, stop_net: D,
                   target_net: D, locked: bool, spread_bps: D, shock_ratio: D | None,
                   position_cap: D, minimum: D, min_notional: D, limit: D) -> tuple[str, dict]:
    risk = units*(paid-stop_net)
    rr = (target_net-paid)/(paid-stop_net) if paid > stop_net else D(0)
    checks = {
        "trade_risk": 0 < risk <= equity*RISK_PER_TRADE_PCT,
        "daily_loss": not locked,
        "reward_risk": rr >= D("1.5"),
        "spread": 0 <= spread_bps <= 15,
        "volatility": shock_ratio is not None and shock_ratio <= 3,
        "position_cap": units*paid <= cash*position_cap,
        "cash_and_minimum": units >= minimum and units*limit >= min_notional and units*paid <= cash,
    }
    failures = [name for name,passed in checks.items() if not passed]
    return ("BLOCK: "+", ".join(failures) if failures else "PASS",
            dict(checks=checks,risk_usdt=str(risk),rr=str(rr),spread_bps=str(spread_bps),
                 shock_ratio=str(shock_ratio) if shock_ratio is not None else None))
