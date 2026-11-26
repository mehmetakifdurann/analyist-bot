"""Optional asynchronous JSON webhook for paper events."""
import json
import logging
from queue import Full, Queue
from threading import Thread
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
