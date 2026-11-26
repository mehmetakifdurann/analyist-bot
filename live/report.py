"""Read-only performance and liveness checks for the paper ledger."""
from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing
from decimal import Decimal as D
from pathlib import Path
from time import time


def read(path: Path, *, events: bool = True) -> tuple[dict, list[dict]]:
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT body FROM wallet WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Paper wallet is missing")
        entries = [{"event_id": id_, **json.loads(body), "kind": kind}
                   for id_,kind,body in db.execute("SELECT id,kind,body FROM events ORDER BY rowid")] if events else []
        return json.loads(row[0]), entries


def healthy(path: Path, now: float | None = None) -> bool:
    wallet, _ = read(path, events=False)
    stamp = wallet.get("last_book_utc")
    return stamp is not None and 0 <= (time() if now is None else now)-stamp <= 180


def performance(wallet: dict, events: list[dict]) -> dict:
    submitted = {e["event_id"]:e for e in events if e["kind"] == "submitted"}
    filled = [e for e in events if e["kind"] == "filled"]
    canceled = [e for e in events if e["kind"] == "canceled"]
    pnls = [D(e["pnl"]) for e in events if e["kind"] in ("stop","target","daily_limit") and "pnl" in e]
    expired = [e for e in canceled if e.get("reason") == "expired" or (
        "reason" not in e and e["id"] in submitted and e["time"] >= submitted[e["id"]]["expires"])]
    def entry_delta(field: str) -> tuple[float | None, int]:
        sample = [(D(e[field])/D(e["signal_bid"])-1)*10000
                  for e in filled if e.get("signal_bid") and e.get(field)]
        return (float(sum(sample)/len(sample)),len(sample)) if sample else (None,0)
    slip, slip_n = entry_delta("fill_price")
    trigger, _ = entry_delta("trigger_ask")
    cash, realized = D(wallet["cash"]), D(wallet["realized"])
    pos = wallet["position"]
    equity = D(wallet.get("last_equity", str(cash))) if pos else cash
    initial = D(wallet.get("initial_cash", cash+(D(pos["cost"]) if pos else 0)-realized))
    losses = -sum(p for p in pnls if p < 0)
    return {
        "submitted":len(submitted), "filled":len(filled), "expired":len(expired),
        "canceled_other":len(canceled)-len(expired),
        "fill_rate_pct":100*len(filled)/len(submitted) if submitted else None,
        "mean_paper_entry_slippage_bps":slip, "entry_slippage_samples":slip_n,
        "mean_trigger_ask_vs_signal_bid_bps":trigger,
        "closed_trades":len(pnls),
        "win_rate_pct":100*sum(p > 0 for p in pnls)/len(pnls) if pnls else None,
        "profit_factor":float(sum(p for p in pnls if p > 0)/losses) if losses else None,
        "realized_pnl_usdt":float(realized), "net_return_usdt":float(equity-initial),
        "cash_usdt":float(cash), "equity_usdt":float(equity),
        "max_drawdown_pct":float(D(wallet["max_drawdown"])*100) if "max_drawdown" in wallet else None,
        "drawdown_tracking_since_utc_epoch":wallet.get("equity_tracking_since"),
        "last_book_utc_epoch":wallet.get("last_book_utc"),
        "open_position":pos, "pending_order":wallet["pending"], "entry_locked":wallet["locked"],
    }


def export_csv(path: Path, events: list[dict]) -> None:
    fields = sorted(set().union(*(e.keys() for e in events))-{"event_id","kind"})
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["event_id","kind",*fields])
        writer.writeheader()
        for row in events:
            writer.writerow({k:json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else v
                             for k,v in row.items()})
