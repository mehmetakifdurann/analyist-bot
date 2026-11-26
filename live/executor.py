"""Single long-only paper wallet with simulated resting limit and protective exits."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_UP, Decimal as D

from .risk import RISK_PER_TRADE_PCT, evaluate_order, update
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


class PaperExecutionAdapter:
    def __init__(self, state: State, filters: Filters, daily_loss: D = D(".01"),
                 *, position_cap: D = D(".25")):
        if not position_cap.is_finite() or not 0 < position_cap <= 1:
            raise ValueError("Paper position cap must be in (0, 1]")
        self.position_cap = position_cap
        self.state, self.filters, self.daily_loss = state, filters, daily_loss

    def submit(self, candle: int, intent: Intent | None, book: Book, now: int, *, context: dict | None = None) -> dict | None:
        with self.state.transaction() as w:
            if candle <= w["candle"]:
                return None
            w["candle"] = candle
            if not intent or (context is None and (w["pending"] or w["position"] or w["locked"])):
                return None
            if (not all(p.is_finite() and p > 0 for p in (intent.stop,intent.limit))
                    or (intent.target is not None and (not intent.target.is_finite() or intent.target <= 0))
                    or not 0 < intent.ttl_seconds <= 86400):
                return None
            limit = intent.limit//self.filters.tick*self.filters.tick
            stop = intent.stop//self.filters.tick*self.filters.tick
            target = ((intent.target/self.filters.tick).to_integral_value(rounding=ROUND_UP)*self.filters.tick
                      if intent.target is not None else None)
            if not 0 < stop < limit or (target is not None and target <= limit) or limit >= book.ask:
                return None
            budget = D(w["cash"])*self.position_cap
            units = budget/(limit*(1+MAKER))//self.filters.step*self.filters.step
            ticket = None
            if context is not None:
                paid = limit*(1+MAKER)
                stop_net = stop*(1-TAKER)*(1-SLIP)
                # A diagnostic 2R level for trailing-only strategies; never a sell instruction.
                reference = target if target is not None else limit+2*(limit-stop)
                equity = D(w.get("last_equity",w["cash"]))
                units = min(units,equity*RISK_PER_TRADE_PCT/(paid-stop_net))
                units = units//self.filters.step*self.filters.step
                verdict, details = evaluate_order(
                    cash=D(w["cash"]),equity=equity,units=units,paid=paid,
                    stop_net=stop_net,target_net=reference*(1-MAKER),locked=w["locked"],
                    spread_bps=(book.ask-book.bid)*20000/(book.ask+book.bid),
                    shock_ratio=context["shock"],position_cap=self.position_cap,
                    minimum=self.filters.minimum,min_notional=self.filters.notional,limit=limit)
                if w["pending"] or w["position"]:
                    verdict = "BLOCK: existing_order_or_position"
                if units*stop < self.filters.notional and verdict == "PASS":
                    verdict = "BLOCK: exit_minimum_notional"
                ticket = dict(id=f"PAXGUSDT:{candle}",kind="trade_ticket",time=now,
                              limit=str(limit),stop=str(stop),target=str(reference),
                              target_is_diagnostic=target is None,units=str(units),
                              risk_check=verdict,timemachine=context["timemachine"],**details)
                self.state.event(ticket["id"]+":ticket","trade_ticket",ticket)
                if verdict != "PASS":
                    return ticket
            elif units < self.filters.minimum or units*stop < self.filters.notional:
                return None
            p = dict(id=f"PAXGUSDT:{candle}", units=str(units), limit=str(limit),
                     stop=str(stop), target=str(target) if target is not None else None, expires=now+intent.ttl_seconds)
            p.update(time=now, signal_bid=str(book.bid))
            if ticket is not None:
                p["ticket"] = ticket
            w["pending"] = p
            self.state.event(p["id"],"submitted",p)
            return ticket if ticket is not None else {**p, "kind": "signal"}

    on_close = submit  # Compatibility for existing paper callers.

    def balance(self) -> dict:
        with self.state.transaction() as wallet:
            return wallet

    def order_status(self, order_id: str) -> str | None:
        if self.state.db.execute("SELECT 1 FROM events WHERE id=?", (order_id,)).fetchone() is None:
            return None
        rows = dict(self.state.db.execute("SELECT id,kind FROM events WHERE id IN (?,?,?)",
                    (f"{order_id}:exit", f"{order_id}:filled", f"{order_id}:canceled")))
        return next((rows[f"{order_id}:{suffix}"] for suffix in ("exit","filled","canceled")
                     if f"{order_id}:{suffix}" in rows), "submitted")

    def _cancel(self, wallet: dict, order: dict, now: int, reason: str) -> dict:
        detail = dict(id=order["id"], kind="canceled", time=now, reason=reason)
        self.state.event(order["id"]+":canceled", "canceled", detail)
        wallet["pending"] = None
        return detail

    def cancel(self, order_id: str, now: int) -> bool:
        with self.state.transaction() as wallet:
            pending = wallet["pending"]
            if pending is None or pending["id"] != order_id:
                return False
            self._cancel(wallet, pending, now, "manual")
            return True

    def daily_heartbeat(self, now: int, last_signal: dict | None) -> dict | None:
        from .notify import record_heartbeat
        return record_heartbeat(self.state, now, last_signal)

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

    def _exit(self, wallet: dict, position: dict, price: D, reason: str, now: int) -> dict:
        units = D(position["units"])
        proceeds = units*price
        pnl = proceeds-D(position["cost"])
        wallet["cash"] = str(D(wallet["cash"])+proceeds)
        wallet["realized"] = str(D(wallet["realized"])+pnl)
        wallet["position"] = None
        detail = {"id":position["id"],"kind":reason,"pnl":str(pnl),"time":now,
                  "units":str(units),"exit_price_net":str(price)}
        self.state.event(position["id"]+":exit",reason,detail)
        return detail

    def close_replay(self, book: Book, now: int) -> dict | None:
        """Liquidate in a bounded historical test using the last synthetic bid."""
        with self.state.transaction() as wallet:
            position = wallet["position"]
            if position is None or book.bid_qty < D(position["units"]):
                return None
            event = self._exit(wallet, position, book.bid*(1-TAKER)*(1-SLIP), "replay_end", now)
            wallet["last_equity"] = wallet["cash"]
            return event

    def on_book(self, book: Book, now: int) -> tuple[D, D, list[dict]]:
        recorded = []
        with self.state.transaction() as w:
            day = datetime.fromtimestamp(now,timezone.utc).date().isoformat()
            pos = w["position"]
            cash = D(w["cash"])
            taker = book.bid*(1-TAKER)*(1-SLIP)
            equity = cash+(D(pos["units"])*taker if pos else 0)
            previously_locked = w["locked"] and w["day"] == day
            update(w,day,equity,self.daily_loss)
            pending = w["pending"]
            if pending:
                units = D(pending["units"])
                limit = D(pending["limit"])
                if now >= pending["expires"] or w["locked"]:
                    recorded.append(self._cancel(w, pending, now,
                                    "expired" if now >= pending["expires"] else "daily_limit"))
                elif book.ask < limit*(1-PENETRATION) and book.ask_qty >= units:
                    cost = units*limit*(1+MAKER)
                    w["cash"] = str(cash-cost)
                    w["position"] = {**pending,"cost":str(cost),"filled_at":now}
                    detail = {"id": pending["id"], "kind": "filled", "time": now,
                              "units": str(units), "fill_price": str(limit),
                              "trigger_ask": str(book.ask), "trigger_bid": str(book.bid),
                              "signal_bid": pending.get("signal_bid")}
                    if "ticket" in pending:
                        detail["ticket"] = pending["ticket"]
                    self.state.event(pending["id"]+":filled","filled",detail)
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
                    recorded.append(self._exit(w, pos, price, reason, now))
            pos = w["position"]
            equity = D(w["cash"])+(D(pos["units"])*taker if pos else 0)
            update(w,day,equity,self.daily_loss)
            if w["locked"] and not previously_locked:
                detail = dict(kind="daily_limit",time=now,equity_usdt=str(equity),
                              daily_start_usdt=w["start_equity"])
                self.state.event(f"daily_limit:{day}","daily_limit",detail)
                recorded.append(detail)
            w["last_equity"] = str(equity)
            if now//60 != w.get("last_book_utc", -60)//60:
                w["last_book_utc"] = now
            # Resume the recorded high-water mark across process restarts.
            if "equity_tracking_since" not in w:
                w["equity_tracking_since"] = now
                w["equity_peak"] = str(equity)
                w["max_drawdown"] = "0"
            peak = max(D(w["equity_peak"]), equity)
            w["equity_peak"] = str(peak)
            w["max_drawdown"] = str(max(D(w["max_drawdown"]),1-equity/peak))
            return equity, D(w["realized"]), recorded


PaperExecutor = PaperExecutionAdapter
