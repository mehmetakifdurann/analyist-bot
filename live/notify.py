"""Optional asynchronous JSON webhook for paper events."""
import json
import logging
from datetime import datetime, timezone
from queue import Full, Queue
from threading import Thread
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .state import State


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Notifier:
    def __init__(self, url: str | None):
        self.queue = None
        if url:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Webhook must be an HTTPS URL without userinfo")
            self.queue = Queue(maxsize=100)
            Thread(target=self._worker, args=(url,), daemon=True).start()

    def publish(self, data: dict) -> None:
        if self.queue is not None:
            try:
                self.queue.put_nowait(data)
            except Full:
                logging.warning("Webhook queue full")

    def _worker(self, url: str) -> None:
        assert self.queue is not None
        opener = build_opener(NoRedirect)
        while True:
            data = self.queue.get()
            try:
                request = Request(url, json.dumps(data).encode(), {"Content-Type":"application/json"})
                with opener.open(request, timeout=4):
                    pass
            except OSError:
                logging.warning("Paper webhook delivery failed")
            finally:
                self.queue.task_done()


def heartbeat(state: State, notifier: Notifier, now: int, last_signal: dict | None) -> None:
    """Record one daily snapshot on the first available quote at or after 00:05 UTC."""
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
    logging.info("paper heartbeat %s", json.dumps(snapshot))
    notifier.publish(snapshot)
