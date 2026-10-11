"""
Positions.

What the platform believes it is holding, and how that belief is kept
honest against the broker.

The broker is always the truth. When the two disagree the position book is
corrected, never the other way round, and the disagreement is reported
rather than quietly smoothed over. A platform that assumes its own record
is right will happily trade on a position that does not exist.

State is written to disk after every change so a positional strategy
survives a restart, and so an intraday restart mid-session picks up where
it left off instead of losing track of open trades.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime

from . import charges as CH
from .store import app_dir

log = logging.getLogger("positions")

STATE_FILE = os.path.join(app_dir(), "positions.json")


@dataclass
class Exit:
    qty: int
    price: float
    reason: str
    at: str


@dataclass
class Position:
    strategy_number: int
    strategy_name: str
    security_id: str
    label: str
    segment: str
    product: str
    mode: str                      # Paper | Live
    qty: int                       # quantity still open
    original_qty: int
    entry_price: float
    entry_at: str
    lot_size: int = 0
    ltp: float = 0.0
    realised: float = 0.0
    exits: list = field(default_factory=list)
    status: str = "open"           # open | closed
    note: str = ""
    entry_charges: float = 0.0     # already paid on the buy leg
    exit_charges: float = 0.0      # paid so far on exits

    @property
    def key(self):
        return (self.strategy_number, self.security_id)

    @property
    def exchange(self):
        return "BSE" if "BSE" in (self.segment or "").upper() else "NSE"

    @property
    def charges(self):
        """Everything paid so far on this position."""
        return self.entry_charges + self.exit_charges

    def expected_exit_charges(self, rates=None):
        """What closing the rest of it would cost at the current price."""
        if self.status != "open" or not self.qty:
            return 0.0
        price = self.ltp or self.entry_price
        return CH.leg(price * self.qty, "SELL", self.exchange, rates)["total"]

    def net(self, rates=None):
        """P&L after everything -- what actually lands in the account."""
        return (self.realised + self.mtm - self.charges
                - self.expected_exit_charges(rates))

    @property
    def mtm(self):
        if self.status != "open" or not self.ltp:
            return 0.0
        return (self.ltp - self.entry_price) * self.qty

    @property
    def total(self):
        return self.realised + self.mtm

    @property
    def capital(self):
        return self.entry_price * self.qty

    def describe(self, rates=None):
        return {"strategy": self.strategy_name, "strike": self.label,
                "qty": self.qty, "entry": round(self.entry_price, 2),
                "ltp": round(self.ltp, 2), "mtm": round(self.mtm, 2),
                "realised": round(self.realised, 2),
                "total": round(self.total, 2),
                "charges": round(self.charges
                                 + self.expected_exit_charges(rates), 2),
                "net": round(self.net(rates), 2),
                "status": self.status, "mode": self.mode, "at": self.entry_at}


class PositionBook:
    def __init__(self):
        self.open = {}             # (strategy_number, security_id) -> Position
        self.closed = []
        self.mismatches = []
        self.rates = CH.ChargeRates()
        self._lock = threading.Lock()

    def set_rates(self, rates: CH.ChargeRates):
        self.rates = rates or CH.ChargeRates()

    # ────────────────────────────────────────────────────────── changes
    def add(self, position: Position):
        if not position.entry_charges:
            position.entry_charges = CH.leg(
                position.entry_price * position.qty, "BUY",
                position.exchange, self.rates)["total"]
        with self._lock:
            self.open[position.key] = position
        self.save()
        return position

    def mark(self, security_id, ltp):
        for pos in self.open.values():
            if pos.security_id == security_id:
                pos.ltp = ltp

    def reduce(self, key, qty, price, reason):
        """Partial or full exit. Returns the position, or None if unknown."""
        with self._lock:
            pos = self.open.get(key)
            if pos is None:
                return None
            qty = min(int(qty), pos.qty)
            if qty <= 0:
                return pos
            pos.realised += (price - pos.entry_price) * qty
            # Brokerage is charged per executed order, so each partial
            # exit carries its own leg of charges.
            pos.exit_charges += CH.leg(price * qty, "SELL", pos.exchange,
                                       self.rates)["total"]
            pos.qty -= qty
            pos.exits.append(Exit(qty, price, reason,
                                  datetime.now().strftime("%H:%M:%S")))
            if pos.qty <= 0:
                pos.status = "closed"
                pos.ltp = price
                self.closed.append(pos)
                self.open.pop(key, None)
        self.save()
        return pos

    # ───────────────────────────────────────────────────────── reporting
    def for_strategy(self, number):
        return [p for p in self.open.values() if p.strategy_number == number]

    def totals(self, number=None):
        live = [p for p in self.open.values()
                if number is None or p.strategy_number == number]
        done = [p for p in self.closed
                if number is None or p.strategy_number == number]
        booked = sum(p.realised for p in done) + sum(p.realised for p in live)
        mtm = sum(p.mtm for p in live)
        charges = (sum(p.charges for p in done)
                   + sum(p.charges + p.expected_exit_charges(self.rates)
                         for p in live))
        return {"booked": booked, "mtm": mtm, "total": booked + mtm,
                "charges": charges, "net": booked + mtm - charges,
                "capital": sum(p.capital for p in live),
                "traded": (sum(p.entry_price * p.original_qty for p in live)
                           + sum(p.entry_price * p.original_qty for p in done)),
                "open": len(live)}

    def describe_open(self):
        return [p.describe(self.rates) for p in self.open.values()]

    # ─────────────────────────────────────────────────────── persistence
    def save(self):
        try:
            payload = {"saved": datetime.now().isoformat(),
                       "open": [asdict(p) for p in self.open.values()],
                       "closed": [asdict(p) for p in self.closed[-200:]]}
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            log.warning("could not save position state: %s", e)

    def load(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            log.warning("could not read position state: %s", e)
            return
        for raw in data.get("open", []):
            raw["exits"] = [Exit(**e) for e in raw.get("exits", [])]
            pos = Position(**raw)
            self.open[pos.key] = pos
        for raw in data.get("closed", []):
            raw["exits"] = [Exit(**e) for e in raw.get("exits", [])]
            self.closed.append(Position(**raw))
        log.info("restored %d open and %d closed positions",
                 len(self.open), len(self.closed))

    # ────────────────────────────────────────────────────── reconciling
    def reconcile(self, broker_positions):
        """
        Compare against the broker and correct ourselves. Returns a list of
        plain-language mismatch descriptions for the screen.
        """
        found = []
        broker = {}
        for row in broker_positions or []:
            sid = str(row.get("securityId", "")).strip()
            if not sid:
                continue
            try:
                net = int(float(row.get("netQty", 0) or 0))
            except (TypeError, ValueError):
                net = 0
            broker[sid] = {"qty": net,
                           "price": float(row.get("buyAvg", 0) or 0)}

        with self._lock:
            for key, pos in list(self.open.items()):
                if pos.mode != "Live":
                    continue
                side = broker.get(pos.security_id)
                if side is None or side["qty"] == 0:
                    found.append(
                        f"{pos.label}: we hold {pos.qty} but the broker shows "
                        f"none. Closing our record.")
                    pos.status = "closed"
                    pos.note = "closed by reconciliation"
                    self.closed.append(pos)
                    self.open.pop(key, None)
                elif abs(side["qty"]) != pos.qty:
                    found.append(
                        f"{pos.label}: we hold {pos.qty}, the broker shows "
                        f"{abs(side['qty'])}. Taking the broker's number.")
                    pos.qty = abs(side["qty"])
                    pos.note = "quantity corrected from the broker"

            ours = {p.security_id for p in self.open.values()
                    if p.mode == "Live"}
            for sid, side in broker.items():
                if side["qty"] != 0 and sid not in ours:
                    found.append(
                        f"Security {sid}: the broker shows {abs(side['qty'])} "
                        f"that this platform did not open. Left alone.")

        self.mismatches = found
        if found:
            log.warning("reconciliation found %d mismatches", len(found))
            self.save()
        return found


BOOK = PositionBook()
