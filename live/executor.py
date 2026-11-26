"""Single long-only paper wallet with simulated resting limit and protective exits."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_UP, Decimal as D

from .risk import update
from .state import State
from .strategy import Intent
from spot_data import Candle
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
    def __init__(self, state: State, filters: Filters, daily_loss: D = D(".01"),
                 *, position_cap: D = D(".25")):
        if not position_cap.is_finite() or not 0 < position_cap <= 1:
            raise ValueError("Paper position cap must be in (0, 1]")
        self.position_cap = position_cap
        self.state, self.filters, self.daily_loss = state, filters, daily_loss

    def on_close(self, candle: int, intent: Intent | None, book: Book, now: int) -> None:
        with self.state.transaction() as w:
            if candle <= w["candle"]:
                return
            w["candle"] = candle
            if not intent or w["pending"] or w["position"] or w["locked"]:
                return
            if (not all(p.is_finite() and p > 0 for p in (intent.stop,intent.limit))
                    or (intent.target is not None and (not intent.target.is_finite() or intent.target <= 0))
                    or not 0 < intent.ttl_seconds <= 86400):
                return
            limit = intent.limit//self.filters.tick*self.filters.tick
            stop = intent.stop//self.filters.tick*self.filters.tick
            target = ((intent.target/self.filters.tick).to_integral_value(rounding=ROUND_UP)*self.filters.tick
                      if intent.target is not None else None)
            if not 0 < stop < limit or (target is not None and target <= limit) or limit >= book.ask:
                return
            budget = D(w["cash"])*self.position_cap
            units = budget/(limit*(1+MAKER))//self.filters.step*self.filters.step
            if units < self.filters.minimum or units*stop < self.filters.notional:
                return
            p = dict(id=f"PAXGUSDT:{candle}", units=str(units), limit=str(limit),
                     stop=str(stop), target=str(target) if target is not None else None, expires=now+intent.ttl_seconds)
            w["pending"] = p
            self.state.event(p["id"],"submitted",p)

    def trail(self, candles: tuple[Candle, ...], atr: D) -> None:
        if not atr.is_finite() or atr <= 0:
            return
        with self.state.transaction() as w:
            pos = w["position"]
            if not pos or pos["target"] is not None:
                return
            # Hourly highs from before a fill or from the partial entry hour are excluded.
            highs = [c.high for c in candles if c.time.timestamp() >= pos["filled_at"]]
            peak = max(D(pos.get("peak", pos["limit"])), *highs) if highs else D(pos.get("peak", pos["limit"]))
            stop = (peak-3*atr)//self.filters.tick*self.filters.tick
            pos["peak"] = str(peak)
            pos["stop"] = str(max(D(pos["stop"]),stop))

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
                    w["position"] = {**pending,"cost":str(cost),"filled_at":now}
                if kind:
                    detail = {"id":pending["id"],"kind":kind,"time":now}
                    self.state.event(pending["id"]+":"+kind,kind,detail)
                    recorded.append(detail)
                    w["pending"] = None
            pos = w["position"]
            if pos:
                units = D(pos["units"])
                target = D(pos["target"]) if pos["target"] is not None else None
                reason = ("stop" if book.bid <= D(pos["stop"])
                          else "target" if target is not None and book.bid > target*(1+PENETRATION) else None)
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
            w["last_equity"] = str(equity)
            return equity, D(w["realized"]), recorded
