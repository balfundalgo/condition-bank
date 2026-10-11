"""
Store for the condition bank and the strategies.

Everything the user creates lives in one JSON file next to the EXE.

NOTE: password protection and the licensing layer are deliberately switched
off for now and will be added once the software is finished. When that
happens, only this file and app.py need to change -- the pages call
STORE.save() and never touch the file themselves.
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime

from . import conditions as C
from . import expression as E

# Suggested starting values from the specification. Every one of them is a
# user input -- these are only what a new strategy begins with.
TRAILING_DEFAULT = [(7.0, -5.0), (10.0, 0.0), (15.0, 5.0), (20.0, 10.0),
                    (25.0, 15.0), (30.0, 20.0), (35.0, 25.0), (40.0, 30.0),
                    (45.0, 35.0), (50.0, 40.0)]
PROFIT_LOCK_DEFAULT = [(10000, 5000), (20000, 10000), (30000, 20000),
                       (40000, 30000), (50000, 40000), (60000, 50000),
                       (70000, 60000), (80000, 70000), (90000, 80000),
                       (100000, 100000)]


def _levels(pairs):
    return [{"on": False, "at": float(a), "lock": float(b)} for a, b in pairs]


def _ladder():
    return [{"on": False, "rate": 0.0, "qty": 0.0} for _ in range(4)]


def app_dir() -> str:
    """Folder next to the EXE when frozen, else the project folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DATA_FILE = os.path.join(app_dir(), "condition_bank.json")
LOG_DIR = os.path.join(app_dir(), "logs")


# ------------------------------------------------------------------ model
@dataclass
class Strategy:
    number: int = 1
    name: str = "New Strategy"
    entry: list = field(default_factory=list)
    exit: list = field(default_factory=list)
    late_enabled: bool = False
    late: list = field(default_factory=lambda: list(E.DEFAULT_LATE))
    late_x: int = 1
    late_y: int = 5
    params: dict = field(default_factory=C.all_defaults)
    instrument: str = "NIFTY"
    broker: str = "Dhan"
    mode: str = "Paper"            # Paper | Live
    style: str = "Intraday"        # Intraday | Positional
    strike_method: str = "Method 1"
    enabled: bool = True
    max_same_side: int = 0          # 0 means no limit
    max_open_positions: int = 0     # 0 means no limit
    lots: int = 1                   # entry size, per strategy
    entry_from: str = "09:20"
    entry_to: str = "15:00"
    square_off_time: str = "15:10"
    strike_filter: dict = field(default_factory=dict)

    # targets and stop-losses: four rows each, rate % and quantity %
    targets: list = field(default_factory=_ladder)
    stops: list = field(default_factory=_ladder)

    # trailing lock profit, per position, ten levels
    trailing_on: bool = False
    trailing: list = field(default_factory=lambda: _levels(TRAILING_DEFAULT))

    # profit lock for this strategy, ten levels, in rupees
    profit_lock_on: bool = False
    profit_locks: list = field(
        default_factory=lambda: _levels(PROFIT_LOCK_DEFAULT))

    # day limits for this strategy, in rupees
    day_profit_on: bool = False
    day_profit: float = 0.0
    day_loss_on: bool = False
    day_loss: float = 0.0

    def summary(self):
        ok_e, _ = E.validate(self.entry, "entry")
        ok_x, _ = E.validate(self.exit, "exit")
        return ok_e and ok_x


@dataclass
class Bank:
    strategies: list = field(default_factory=list)
    created: str = ""
    notes: str = ""
    settings: dict = field(default_factory=dict)

    def to_dict(self):
        return {"created": self.created, "notes": self.notes,
                "settings": self.settings,
                "strategies": [asdict(s) for s in self.strategies]}

    @staticmethod
    def from_dict(d: dict) -> "Bank":
        b = Bank(created=d.get("created", ""), notes=d.get("notes", ""),
                 settings=d.get("settings", {}))
        for s in d.get("strategies", []):
            base = C.all_defaults()
            base.update(s.get("params", {}))
            s["params"] = base
            known = {f for f in Strategy.__dataclass_fields__}
            b.strategies.append(Strategy(**{k: v for k, v in s.items()
                                            if k in known}))
        return b


# ------------------------------------------------------------------ store
class Store:
    def __init__(self):
        self.bank: Bank = None

    def load(self):
        """Read the bank from disk, or start a fresh empty one."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, encoding="utf-8") as fh:
                    self.bank = Bank.from_dict(json.load(fh))
                return
            except Exception:
                backup = DATA_FILE + ".bad"
                try:
                    os.replace(DATA_FILE, backup)
                except OSError:
                    pass
        self.bank = Bank(created=datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.save()

    def save(self):
        if self.bank is None:
            return
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.bank.to_dict(), fh, indent=2)
        os.replace(tmp, DATA_FILE)

    # -- backup ----------------------------------------------------------
    def export_backup(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.bank.to_dict(), fh, indent=2)

    def import_backup(self, path: str):
        with open(path, encoding="utf-8") as fh:
            self.bank = Bank.from_dict(json.load(fh))
        self.save()

    # -- strategies ------------------------------------------------------
    def next_number(self) -> int:
        used = {s.number for s in self.bank.strategies}
        n = 1
        while n in used:
            n += 1
        return n

    def add_strategy(self, template="Blank") -> Strategy:
        tpl = E.TEMPLATES.get(template, E.TEMPLATES["Blank"])
        n = self.next_number()
        name = template if template != "Blank" else f"Strategy {n}"
        s = Strategy(number=n, name=name.replace(" (from the spec)", ""),
                     entry=list(tpl["entry"]), exit=list(tpl["exit"]))
        self.bank.strategies.append(s)
        self.save()
        return s

    def delete_strategy(self, strategy: Strategy):
        self.bank.strategies = [s for s in self.bank.strategies
                                if s is not strategy]
        self.save()

    def usage_count(self, cid: str) -> int:
        n = 0
        for s in self.bank.strategies:
            if cid in s.entry or cid in s.exit or cid in s.late:
                n += 1
        return n


STORE = Store()
