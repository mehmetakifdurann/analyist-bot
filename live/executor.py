"""Single long-only paper wallet with simulated resting limit and protective exits."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_UP, Decimal as D

from .risk import update
from .state import State
from .strategy import Intent
from .stream import Book

MAKER, TAKER, SLIP = D(".001"), D(".001"), D(".0002")
PENETRATION = D(".0002")


@dataclass(frozen=True)
class Filters:
    step: D
    minimum: D
    notional: D
    tick: D


class PaperExecutor:
    def __init__(self, state: State, filters: Filters, daily_loss: D = D(".01")):
        self.state, self.filters, self.daily_loss = state, filters, daily_loss

    def on_close(self, candle: int, intent: Intent | None, book: Book, now: int) -> None:
        with self.state.transaction() as w:
            if candle <= w["candle"]:
                return
            w["candle"] = candle
            if not intent or w["pending"] or w["position"] or w["locked"]:
                return
            if (not all(p.is_finite() and p > 0 for p in (intent.stop,intent.limit,intent.target))
                    or not 0 < intent.ttl_seconds <= 86400):
                return
            limit = intent.limit//self.filters.tick*self.filters.tick
            stop = intent.stop//self.filters.tick*self.filters.tick
            target = (intent.target/self.filters.tick).to_integral_value(rounding=ROUND_UP)*self.filters.tick
            if not 0 < stop < limit < target or limit >= book.ask:
                return
            budget = D(w["cash"])*D(".25")
            units = budget/(limit*(1+MAKER))//self.filters.step*self.filters.step
            if units < self.filters.minimum or units*stop < self.filters.notional:
                return
            p = dict(id=f"PAXGUSDT:{candle}", units=str(units), limit=str(limit),
                     stop=str(stop), target=str(target), expires=now+intent.ttl_seconds)
            w["pending"] = p
            self.state.event(p["id"],"submitted",p)

    def on_book(self, book: Book, now: int) -> tuple[D, D, list[dict]]:
        recorded = []
        with self.state.transaction() as w:
            day = datetime.fromtimestamp(now,timezone.utc).date().isoformat()
            pos = w["position"]
            cash = D(w["cash"])
            taker = book.bid*(1-TAKER)*(1-SLIP)
            equity = cash+(D(pos["units"])*taker if pos else 0)
            update(w,day,equity,self.daily_loss)
            pending = w["pending"]
            if pending:
                units = D(pending["units"])
                limit = D(pending["limit"])
                kind = None
                if now >= pending["expires"] or w["locked"]:
                    kind = "canceled"
                elif book.ask < limit*(1-PENETRATION) and book.ask_qty >= units:
                    kind = "filled"
                    cost = units*limit*(1+MAKER)
                    w["cash"] = str(cash-cost)
                    w["position"] = {**pending,"cost":str(cost)}
                if kind:
                    detail = {"id":pending["id"],"kind":kind,"time":now}
                    self.state.event(pending["id"]+":"+kind,kind,detail)
                    recorded.append(detail)
                    w["pending"] = None
            pos = w["position"]
            if pos:
                units = D(pos["units"])
                target = D(pos["target"])
                reason = ("daily_limit" if w["locked"] else "stop" if book.bid <= D(pos["stop"])
                          else "target" if book.bid > target*(1+PENETRATION) else None)
                if reason and book.bid_qty >= units:
                    price = target*(1-MAKER) if reason == "target" else taker
                    proceeds = units*price
                    pnl = proceeds-D(pos["cost"])
                    w["cash"] = str(D(w["cash"])+proceeds)
                    w["realized"] = str(D(w["realized"])+pnl)
                    w["position"] = None
                    detail = {"id":pos["id"],"kind":reason,"pnl":str(pnl),"time":now}
                    self.state.event(pos["id"]+":exit",reason,detail)
                    recorded.append(detail)
            pos = w["position"]
            equity = D(w["cash"])+(D(pos["units"])*taker if pos else 0)
            update(w,day,equity,self.daily_loss)
            return equity, D(w["realized"]), recorded
