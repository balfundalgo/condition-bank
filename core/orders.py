"""
Order manager.

Everything that reaches the broker goes through here, for three reasons.

Exits come before entries. When a sharp move makes forty strikes signal at
once and a day limit fires in the same second, the exits must not be stuck
behind a queue of new entries. The queue is ordered by priority, not by
arrival.

Nothing is fired in a loop. Calls are released through the rate gate, so a
burst of signals becomes a steady stream the broker will accept rather
than a flood it will reject.

Nothing is assumed to have worked. A market order that the API accepted is
not a filled order; the fill is confirmed against the order book, and four
failed attempts send it to the error basket rather than silently vanishing.

Paper mode fills instantly at the price the signal saw. No broker call is
made at all, so paper and live can run side by side.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from . import dhan

log = logging.getLogger("orders")

PRIORITY_EXIT = 0
PRIORITY_ENTRY = 1
QUEUE_WARN_DEPTH = 200          # refuse new entries beyond this


@dataclass
class OrderRequest:
    strategy_number: int
    strategy_name: str
    security_id: str
    label: str
    segment: str
    side: str                   # BUY | SELL
    qty: int
    product: str = "INTRADAY"
    mode: str = "Paper"
    priority: int = PRIORITY_ENTRY
    reason: str = ""
    reference_price: float = 0.0
    on_done: object = None
    attempts: int = 0
    created: datetime = field(default_factory=datetime.now)

    @property
    def is_exit(self):
        return self.priority == PRIORITY_EXIT

    def describe(self):
        return {"time": self.created.strftime("%H:%M:%S"),
                "strategy": self.strategy_name, "strike": self.label,
                "side": self.side, "qty": self.qty, "reason": self.reason,
                "attempts": self.attempts, "mode": self.mode}


class OrderManager:
    def __init__(self, client: dhan.DhanClient, on_event=None):
        self.client = client
        self.on_event = on_event or (lambda kind, data: None)
        self._queue = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._running = False
        self.error_basket = deque(maxlen=200)
        self.sent = 0
        self.filled = 0
        self.failed = 0

    # ───────────────────────────────────────────────────────── lifecycle
    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True,
                         name="orders").start()

    def stop(self):
        self._running = False
        self._wake.set()

    # ───────────────────────────────────────────────────────── the queue
    @property
    def depth(self):
        with self._lock:
            return len(self._queue)

    def submit(self, request: OrderRequest):
        """
        Returns (accepted, message). Entries are refused when the queue is
        already deep, so a backlog cannot keep growing. Exits are never
        refused.
        """
        with self._lock:
            if (not request.is_exit) and len(self._queue) >= QUEUE_WARN_DEPTH:
                return False, (f"Order queue is {len(self._queue)} deep. "
                               f"New entries are paused until it clears.")
            self._queue.append(request)
            self._queue.sort(key=lambda r: (r.priority, r.created))
        self._wake.set()
        return True, ""

    def _take(self):
        with self._lock:
            if not self._queue:
                return None
            return self._queue.pop(0)

    # ────────────────────────────────────────────────────────── worker
    def _loop(self):
        while self._running:
            request = self._take()
            if request is None:
                self._wake.wait(0.2)
                self._wake.clear()
                continue
            try:
                self._execute(request)
            except Exception as e:
                log.exception("order worker failed")
                self._to_basket(request, str(e))

    def _execute(self, request: OrderRequest):
        self.sent += 1
        if request.mode != "Live":
            result = {"filled": True, "price": request.reference_price,
                      "qty": request.qty, "order_id": "PAPER", "reason": ""}
            time.sleep(0.01)
        else:
            result = self.client.place_market(
                request.security_id, request.segment, request.side,
                request.qty, product=request.product)

        if result.get("filled"):
            self.filled += 1
            price = result.get("price") or request.reference_price
            qty = result.get("qty") or request.qty
            log.info("%s %s %s x%s @ %.2f (%s)", request.mode.upper(),
                     request.side, request.label, qty, price, request.reason)
            if request.on_done:
                request.on_done(True, price, qty, result.get("order_id", ""))
            self.on_event("fill", {**request.describe(), "price": price,
                                   "qty": qty})
        else:
            self._to_basket(request, result.get("reason", "unknown"))

    def _to_basket(self, request, reason):
        """
        A market order that failed every retry. place_market() already
        tried four times, so arriving here means it is genuinely stuck.
        """
        self.failed += 1
        entry = {**request.describe(), "error": reason,
                 "at": datetime.now().strftime("%H:%M:%S"),
                 "_request": request}
        self.error_basket.appendleft(entry)
        log.error("ORDER FAILED %s %s: %s", request.side, request.label,
                  reason)
        if request.on_done:
            request.on_done(False, 0.0, 0, "")
        self.on_event("order_failed", {k: v for k, v in entry.items()
                                       if k != "_request"})

    # ───────────────────────────────────────────────────── error basket
    def retry(self, index):
        try:
            entry = list(self.error_basket)[index]
        except IndexError:
            return False
        request = entry.get("_request")
        if request is None:
            return False
        request.attempts += 1
        self.error_basket.remove(entry)
        self.submit(request)
        return True

    def retry_all(self):
        count = 0
        for entry in list(self.error_basket):
            request = entry.get("_request")
            if request is not None:
                request.attempts += 1
                self.error_basket.remove(entry)
                self.submit(request)
                count += 1
        return count

    def clear_errors(self):
        self.error_basket.clear()

    def errors(self, n=30):
        return [{k: v for k, v in e.items() if k != "_request"}
                for e in list(self.error_basket)[:n]]

    def stats(self):
        return {"queued": self.depth, "sent": self.sent,
                "filled": self.filled, "failed": self.failed,
                "errors": len(self.error_basket)}
