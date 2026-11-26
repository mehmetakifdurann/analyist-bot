"""UTC daily loss circuit for the simulated wallet."""
from decimal import Decimal as D


def update(wallet: dict, utc_day: str, equity: D, limit: D) -> None:
    if wallet["day"] is None or utc_day > wallet["day"]:
        wallet.update(day=utc_day, start_equity=str(equity), locked=False)
    if equity <= D(wallet["start_equity"])*(1-limit):
        wallet["locked"] = True
