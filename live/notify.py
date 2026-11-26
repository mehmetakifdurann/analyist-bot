"""Optional asynchronous JSON webhook for paper events."""
import json
import logging
import re
from datetime import datetime, timezone
from queue import Full, Queue
from threading import Thread
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .state import State


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def message(data: dict) -> str | None:
    kind = data["kind"]
    prefix = "PAXG paper"
    if kind == "trade_ticket" or (kind == "filled" and "ticket" in data):
        ticket = data.get("ticket",data)
        mc = ticket["timemachine"]
        model = (f'hedef olasılığı %{mc["p_target_pct"]:.1f}, beklenen R {mc["expected_r"]:+.2f}'
                 if "p_target_pct" in mc else "Monte Carlo verisi yok")
        fill = f' · dolum {data["fill_price"]}' if kind == "filled" else ""
        label = "referans hedef" if ticket["target_is_diagnostic"] else "hedef"
        return (f'{prefix} · {ticket["risk_check"]}{fill} · Limit {ticket["limit"]}, stop {ticket["stop"]}, '
                f'{label} {ticket["target"]} USDT · risk {float(ticket["risk_usdt"]):.2f} USDT, '
                f'R/R {float(ticket["rr"]):.2f} · {model}.')
    if kind == "signal":
        return f'{prefix} · Alış sinyali: limit {data["limit"]} USDT, stop {data["stop"]}.'
    if kind == "filled":
        return f'{prefix} · Sanal dolum: {data["units"]} PAXG, fiyat {data["fill_price"]} USDT.'
    if kind in ("stop","target"):
        return f'{prefix} · Çıkış ({kind}): {float(data["pnl"]):+.2f} USDT.'
    if kind == "daily_limit":
        return f'{prefix} · Günlük giriş kilidi. Özsermaye {float(data["equity_usdt"]):.2f} USDT.'
    if kind == "paper_heartbeat":
        pos = data["position"]
        holding = f'{pos["units"]} PAXG' if pos else "yok"
        signal = data["last_closed_signal"]
        entry = ("alış" if signal["entry"] else "bekle") if signal else "bilinmiyor"
        return (f'{prefix} · Motor çalışıyor. Nakit {float(data["cash_usdt"]):.2f}, özsermaye '
                f'{float(data["equity_usdt"]):.2f} USDT. Açık pozisyon: {holding}. Son sinyal: {entry}.')
    return None


class Notifier:
    def __init__(self, url: str | None, token: str | None = None, chat_id: str | None = None):
        self.queue = None
        if url:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Webhook must be an HTTPS URL without userinfo")
        self.telegram = None
        if token and chat_id:
            if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
                raise ValueError("Invalid Telegram bot token format")
            self.telegram = (f"https://api.telegram.org/bot{token}/sendMessage", chat_id)
        if url or self.telegram:
            self.queue = Queue(maxsize=100)
            Thread(target=self._worker, args=(url,), daemon=True).start()

    def publish(self, data: dict) -> None:
        if (data.get("kind") == "trade_ticket"
                and data.get("risk_check") == "BLOCK: existing_order_or_position"):
            return
        if self.queue is not None:
            try:
                self.queue.put_nowait(data)
            except Full:
                logging.warning("Paper notification queue full")

    def _worker(self, url: str | None) -> None:
        assert self.queue is not None
        opener = build_opener(NoRedirect)
        while True:
            data = self.queue.get()
            try:
                targets = [(url, data)] if url else []
                if self.telegram and (text := message(data)):
                    dest, chat_id = self.telegram
                    targets.append((dest, {"chat_id": chat_id, "text": text}))
                for destination,payload in targets:
                    try:
                        request = Request(destination, json.dumps(payload).encode(),
                                          {"Content-Type":"application/json"})
                        with opener.open(request, timeout=4):
                            pass
                    except (OSError, ValueError):
                        logging.warning("Paper notification delivery failed")
            finally:
                self.queue.task_done()


def record_heartbeat(state: State, now: int, last_signal: dict | None) -> dict | None:
    """Persist a snapshot once per UTC day, from 00:05 onward."""
    stamp = datetime.fromtimestamp(now, timezone.utc)
    if stamp.hour == 0 and stamp.minute < 5:
        return
    day = stamp.date().isoformat()
    with state.transaction() as wallet:
        if wallet.get("heartbeat_day", "") >= day:
            return
        wallet["heartbeat_day"] = day
        pos = wallet["position"]
        snapshot = {"kind": "paper_heartbeat", "utc": stamp.isoformat(),
                    "feed": "connected", "cash_usdt": wallet["cash"],
                    "equity_usdt": wallet["last_equity"], "realized_usdt": wallet["realized"],
                    "position": {k: pos[k] for k in ("units","stop","id")} if pos else None,
                    "entry_locked": wallet["locked"], "last_closed_signal": last_signal}
        state.event(f"heartbeat:{day}", "heartbeat", snapshot)
    return snapshot


def publish_heartbeat(notifier: Notifier, snapshot: dict | None) -> None:
    if snapshot:
        logging.info("paper heartbeat %s", json.dumps(snapshot))
        notifier.publish(snapshot)


def heartbeat(state: State, notifier: Notifier, now: int, last_signal: dict | None) -> None:
    publish_heartbeat(notifier, record_heartbeat(state, now, last_signal))
