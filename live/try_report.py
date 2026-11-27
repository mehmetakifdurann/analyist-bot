"""Value an existing paper ledger in TRY using public Binance Spot data."""
import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

from spot_data import get_json


def value_in_try(report: dict, funding: dict, quote: dict) -> dict:
    if D(str(report["initial_usdt"])) != D(funding["initial_usdt"]):
        raise ValueError("Funding record does not match the ledger's opening balance")
    equity = D(str(report["equity_usdt"]))
    bid, quantity, fee = D(quote["bidPrice"]), D(quote["bidQty"]), D(funding["assumed_conversion_fee"])
    if quote.get("symbol") != "USDTTRY" or not (0 < bid and 0 <= equity <= quantity and 0 <= fee < 1):
        raise ValueError("Invalid USDT/TRY quote or insufficient bid quantity")
    initial = D(funding["initial_try"])
    value = equity*bid*(1-fee)
    return dict(initial_try=str(initial), equity_try=str(value.quantize(D(".01"))),
                pnl_try=str((value-initial).quantize(D(".01"))),
                usdttry_bid=str(bid), assumed_conversion_fee=str(fee),
                submitted=report["submitted"], filled=report["filled"],
                closed_trades=report["closed_trades"], open_position=report["open_position"],
                valued_at_utc=datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    import sys

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("funding", type=Path)
    args = cli.parse_args()
    try:
        report = json.load(sys.stdin)
        funding = json.loads(args.funding.read_text())
        print(json.dumps(value_in_try(report,funding,get_json("ticker/bookTicker",symbol="USDTTRY")),indent=2))
    except (ValueError, ArithmeticError, OSError, KeyError) as exc:
        cli.error(str(exc))
