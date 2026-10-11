"""
Targets page.

Four targets, four stop-losses, the ten-level trailing lock, the strategy
profit lock and the strategy day limits — plus the combined limits that
apply across everything.

Every number here is a user input. Nothing is fixed in the code, and the
values a new strategy starts with are only the suggestions from the
specification.
"""

import customtkinter as ctk

from core import theme as T
from core import charges as CH
from core.positions import BOOK
from core.store import STORE, PROFIT_LOCK_DEFAULT
from ui.widgets import Card, heading


class TargetsPage(ctk.CTkFrame):
    def __init__(self, master, shell):
        super().__init__(master, fg_color="transparent")
        self.shell = shell
        self.strategy = None
        self.rows = {"targets": [], "stops": [], "trailing": [],
                     "locks": [], "combined_locks": []}
        self.fields = {}

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(22, 0))
        heading(head, "Targets and risk",
                "How a position is taken off, and the limits that stop a bad "
                "day getting worse. Everything is a user input."
                ).pack(anchor="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=26, pady=(14, 8))
        self.picker = ctk.CTkOptionMenu(bar, values=["-"], width=250,
                                        height=36, font=T.f(12),
                                        fg_color=T.PANEL,
                                        button_color=T.PANEL_HI,
                                        dropdown_fg_color=T.PANEL,
                                        command=self._pick)
        self.picker.pack(side="left")
        ctk.CTkButton(bar, text="Save", width=110, height=36,
                      font=T.f(13, "bold"), fg_color=T.ACCENT,
                      hover_color=T.ACCENT_DEEP,
                      command=self._save).pack(side="left", padx=10)
        self.msg = ctk.CTkLabel(bar, text="", font=T.f(11),
                                text_color=T.TEXT_MUTED, anchor="w",
                                justify="left", wraplength=620)
        self.msg.pack(side="left")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._build()
        self.reload()

    # ─────────────────────────────────────────────────────────── layout
    def _ladder(self, card, kind, label_a, label_b, count=4):
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(2, 2))
        for text, width in (("On", 44), ("#", 40), (label_a, 150),
                            (label_b, 150)):
            ctk.CTkLabel(header, text=text, font=T.f(10, "bold"), width=width,
                         anchor="w", text_color=T.TEXT_DIM
                         ).pack(side="left", padx=2)
        out = []
        for i in range(count):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=1)
            on = ctk.CTkCheckBox(row, text="", width=44, checkbox_width=16,
                                 checkbox_height=16, fg_color=T.ACCENT_DEEP)
            on.pack(side="left", padx=2)
            ctk.CTkLabel(row, text=str(i + 1), font=T.f(11), width=40,
                         anchor="w", text_color=T.TEXT_MUTED
                         ).pack(side="left", padx=2)
            a = ctk.CTkEntry(row, width=150, height=26, font=T.f(11),
                             fg_color=T.PANEL_DEEP, border_color=T.BORDER)
            a.pack(side="left", padx=2)
            b = ctk.CTkEntry(row, width=150, height=26, font=T.f(11),
                             fg_color=T.PANEL_DEEP, border_color=T.BORDER)
            b.pack(side="left", padx=2)
            out.append((on, a, b))
        self.rows[kind] = out

    def _switch(self, card, key, text):
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 2))
        sw = ctk.CTkSwitch(row, text=text, font=T.f(12),
                           text_color=T.TEXT, progress_color=T.ACCENT)
        sw.pack(side="left")
        self.fields[key] = sw
        return row

    def _money(self, card, key, label):
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=3)
        sw = ctk.CTkSwitch(row, text=label, font=T.f(12), width=300,
                           text_color=T.TEXT_MUTED, progress_color=T.ACCENT)
        sw.pack(side="left")
        entry = ctk.CTkEntry(row, width=140, height=28, font=T.f(12),
                             fg_color=T.PANEL_DEEP, border_color=T.BORDER)
        entry.pack(side="left", padx=8)
        ctk.CTkLabel(row, text="INR", font=T.f(11),
                     text_color=T.TEXT_DIM).pack(side="left")
        self.fields[key + "_on"] = sw
        self.fields[key] = entry

    def _title(self, card, text, sub=None):
        ctk.CTkLabel(card, text=text, font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=16,
                                                 pady=(13, 2))
        if sub:
            ctk.CTkLabel(card, text=sub, font=T.f(10),
                         text_color=T.TEXT_DIM, anchor="w", justify="left",
                         wraplength=880).pack(anchor="w", padx=16,
                                              pady=(0, 6))

    def _build(self):
        tgt = Card(self.scroll)
        tgt.pack(fill="x", pady=(2, 10))
        self._title(tgt, "TARGETS",
                    "Quantity % is a share of the original position, rounded "
                    "down to whole lots. Leave it at 0 or 100 to close "
                    "everything left. Each level fires once.")
        self._ladder(tgt, "targets", "Rate % above entry", "Quantity %")
        self.breakeven = ctk.CTkLabel(tgt, text="", font=T.f(11),
                                      text_color=T.AMBER, anchor="w",
                                      justify="left", wraplength=880)
        self.breakeven.pack(anchor="w", padx=16, pady=(8, 12))

        stp = Card(self.scroll)
        stp.pack(fill="x", pady=(0, 10))
        self._title(stp, "STOP-LOSSES",
                    "Write the rate as a positive number. A rate of 5 means "
                    "the price has fallen 5% below entry.")
        self._ladder(stp, "stops", "Rate % below entry", "Quantity %")
        ctk.CTkLabel(stp, text="", font=T.f(4)).pack(pady=2)

        trail = Card(self.scroll)
        trail.pack(fill="x", pady=(0, 10))
        self._title(trail, "TRAILING LOCK PROFIT, PER POSITION",
                    "Once profit reaches the level on the left, the figure "
                    "on the right becomes a floor. The floor only moves up. "
                    "A negative floor turns a wide stop into a tight one.")
        self._switch(trail, "trailing_on", "Enable trailing lock")
        self._ladder(trail, "trailing", "If profit reaches (%)",
                     "Lock profit at (%)", count=10)
        ctk.CTkLabel(trail, text="", font=T.f(4)).pack(pady=2)

        lock = Card(self.scroll)
        lock.pack(fill="x", pady=(0, 10))
        self._title(lock, "PROFIT LOCK — THIS STRATEGY",
                    "The same idea in rupees, on this strategy's net profit "
                    "after charges. When profit falls back to the floor, "
                    "every position in this strategy is closed.")
        self._switch(lock, "profit_lock_on", "Enable profit lock")
        self._ladder(lock, "locks", "Total profit reaches (INR)",
                     "Lock profit at (INR)", count=10)
        ctk.CTkLabel(lock, text="", font=T.f(4)).pack(pady=2)

        day = Card(self.scroll)
        day.pack(fill="x", pady=(0, 10))
        self._title(day, "DAY LIMITS — THIS STRATEGY",
                    "Measured on net profit after charges. When one is hit, "
                    "this strategy closes out and takes no new entries for "
                    "the rest of the day.")
        self._money(day, "day_profit", "Exit this strategy if day profit >=")
        self._money(day, "day_loss", "Exit this strategy if day loss >=")
        ctk.CTkLabel(day, text="", font=T.f(4)).pack(pady=4)

        combined = Card(self.scroll)
        combined.pack(fill="x", pady=(0, 10))
        self._title(combined, "ALL STRATEGIES COMBINED",
                    "These apply to the whole account and outrank everything "
                    "above. When one fires, every open position across every "
                    "strategy is closed and the day is over.")
        self._money(combined, "c_day_profit", "Exit everything if day profit >=")
        self._money(combined, "c_day_loss", "Exit everything if day loss >=")
        self._switch(combined, "c_lock_on", "Enable combined profit lock")
        self._ladder(combined, "combined_locks",
                     "Total profit reaches (INR)", "Lock profit at (INR)",
                     count=10)
        ctk.CTkLabel(combined, text="", font=T.f(4)).pack(pady=2)

        order = Card(self.scroll)
        order.pack(fill="x", pady=(0, 10))
        self._title(order, "WHICH EXIT WINS",
                    "All of these are checked continuously. Whichever "
                    "triggers first acts. If two fire on the same update, "
                    "this order decides.")
        steps = ["Combined day loss", "Combined day profit",
                 "Combined profit lock", "Strategy day loss",
                 "Strategy day profit", "Strategy profit lock",
                 "Square-off time", "Trailing lock", "Stop-loss levels",
                 "Target levels", "Exit conditions"]
        for i, text in enumerate(steps, start=1):
            ctk.CTkLabel(order, text=f"{i:>2}.  {text}", font=T.fm(11),
                         text_color=(T.RED if i <= 3 else T.AMBER if i <= 7
                                     else T.TEXT_MUTED),
                         anchor="w").pack(anchor="w", padx=16, pady=1)
        ctk.CTkLabel(order, text="", font=T.f(6)).pack(pady=6)

    # ────────────────────────────────────────────────────────── loading
    def reload(self):
        names = [f"{s.number}. {s.name}" for s in STORE.bank.strategies]
        self.picker.configure(values=names or ["-"])
        if not STORE.bank.strategies:
            self.strategy = None
            self.picker.set("-")
            self.msg.configure(text="No strategies yet.",
                               text_color=T.TEXT_MUTED)
            return
        if self.strategy not in STORE.bank.strategies:
            self.strategy = STORE.bank.strategies[0]
        self.picker.set(names[STORE.bank.strategies.index(self.strategy)])
        self._fill()

    def _pick(self, label):
        for s in STORE.bank.strategies:
            if f"{s.number}. {s.name}" == label:
                self.strategy = s
                break
        self._fill()

    @staticmethod
    def _put(entry, value):
        entry.delete(0, "end")
        entry.insert(0, "" if value is None else f"{value:g}"
                     if isinstance(value, float) else str(value))

    def _load_ladder(self, kind, rows, key_a, key_b):
        for (on, a, b), data in zip(self.rows[kind], rows or []):
            on.select() if data.get("on") else on.deselect()
            self._put(a, float(data.get(key_a) or 0))
            self._put(b, float(data.get(key_b) or 0))

    def _fill(self):
        s = self.strategy
        if not s:
            return
        self._load_ladder("targets", s.targets, "rate", "qty")
        self._load_ladder("stops", s.stops, "rate", "qty")
        self._load_ladder("trailing", s.trailing, "at", "lock")
        self._load_ladder("locks", s.profit_locks, "at", "lock")

        (self.fields["trailing_on"].select() if s.trailing_on
         else self.fields["trailing_on"].deselect())
        (self.fields["profit_lock_on"].select() if s.profit_lock_on
         else self.fields["profit_lock_on"].deselect())

        for key, on, value in (("day_profit", s.day_profit_on, s.day_profit),
                               ("day_loss", s.day_loss_on, s.day_loss)):
            (self.fields[key + "_on"].select() if on
             else self.fields[key + "_on"].deselect())
            self._put(self.fields[key], value)

        combined = (STORE.bank.settings.get("combined", {})
                    if STORE.bank else {})
        for key, src in (("c_day_profit", "day_profit"),
                         ("c_day_loss", "day_loss")):
            (self.fields[key + "_on"].select()
             if combined.get(src + "_on") else
             self.fields[key + "_on"].deselect())
            self._put(self.fields[key], float(combined.get(src) or 0))
        (self.fields["c_lock_on"].select() if combined.get("lock_on")
         else self.fields["c_lock_on"].deselect())
        locks = combined.get("locks") or [
            {"on": False, "at": float(a), "lock": float(b)}
            for a, b in PROFIT_LOCK_DEFAULT]
        self._load_ladder("combined_locks", locks, "at", "lock")

        self._show_breakeven()
        self.msg.configure(text="", text_color=T.TEXT_MUTED)

    def _show_breakeven(self):
        """
        Charges mean a small target can be entirely eaten. Say so, in
        rupees, before the user commits to one.
        """
        s = self.strategy
        first = next((r for r in (s.targets or []) if r.get("on")
                      and float(r.get("rate") or 0) > 0), None)
        premium = 150.0
        qty = 75 * max(1, int(s.lots or 1))
        trip = CH.round_trip(premium, premium, qty, "NSE", BOOK.rates)
        breakeven_pct = (trip["total"] / (premium * qty)) * 100.0
        text = (f"On a {premium:g} premium and {qty} units, charges come to "
                f"about {trip['total']:,.0f}, so the price must move roughly "
                f"{breakeven_pct:.2f}% just to break even.")
        if first:
            rate = float(first["rate"])
            if rate <= breakeven_pct:
                text += (f"  Your first target of {rate:g}% is below that — "
                         f"it would close at a loss after charges.")
            elif rate < breakeven_pct * 2:
                text += (f"  Your first target of {rate:g}% leaves very "
                         f"little after charges.")
        self.breakeven.configure(text=text)

    # ───────────────────────────────────────────────────────── saving
    def _read_ladder(self, kind, key_a, key_b):
        out = []
        for index, (on, a, b) in enumerate(self.rows[kind], start=1):
            try:
                va = float(a.get().strip() or 0)
                vb = float(b.get().strip() or 0)
            except ValueError:
                raise ValueError(f"row {index} of {kind}")
            out.append({"on": bool(on.get()), key_a: va, key_b: vb})
        return out

    def _read_money(self, key):
        try:
            return (bool(self.fields[key + "_on"].get()),
                    float(self.fields[key].get().strip() or 0))
        except ValueError:
            raise ValueError(key)

    def _save(self):
        s = self.strategy
        if not s:
            return
        try:
            targets = self._read_ladder("targets", "rate", "qty")
            stops = self._read_ladder("stops", "rate", "qty")
            trailing = self._read_ladder("trailing", "at", "lock")
            locks = self._read_ladder("locks", "at", "lock")
            c_locks = self._read_ladder("combined_locks", "at", "lock")
            dp_on, dp = self._read_money("day_profit")
            dl_on, dl = self._read_money("day_loss")
            cp_on, cp = self._read_money("c_day_profit")
            cl_on, cl = self._read_money("c_day_loss")
        except ValueError as e:
            self.msg.configure(text=f"{e.args[0]} must be a number.",
                               text_color=T.RED)
            return

        active = [r["rate"] for r in targets if r["on"]]
        if active != sorted(active):
            self.msg.configure(
                text="Target rates must increase down the list — target 2 "
                     "cannot be nearer than target 1.", text_color=T.RED)
            return
        active_stops = [r["rate"] for r in stops if r["on"]]
        if active_stops != sorted(active_stops):
            self.msg.configure(
                text="Stop-loss rates must increase down the list.",
                text_color=T.RED)
            return
        if sum(r["qty"] for r in targets if r["on"]) > 100:
            self.msg.configure(
                text="Target quantities add up to more than 100% of the "
                     "position.", text_color=T.RED)
            return

        s.targets, s.stops = targets, stops
        s.trailing, s.profit_locks = trailing, locks
        s.trailing_on = bool(self.fields["trailing_on"].get())
        s.profit_lock_on = bool(self.fields["profit_lock_on"].get())
        s.day_profit_on, s.day_profit = dp_on, dp
        s.day_loss_on, s.day_loss = dl_on, dl

        STORE.bank.settings["combined"] = {
            "day_profit_on": cp_on, "day_profit": cp,
            "day_loss_on": cl_on, "day_loss": cl,
            "lock_on": bool(self.fields["c_lock_on"].get()),
            "locks": c_locks}
        STORE.save()
        self._show_breakeven()
        self.msg.configure(text="Saved. Applies to new and open positions "
                                "immediately.", text_color=T.GREEN)
        self.shell.refresh_all()

    def refresh(self):
        self.reload()
