"""
Execution page.

The settings the engine already reads: which strikes to watch, how big a
trade is, when entries are allowed and how many positions may be open.

Everything here is per strategy. Pick a strategy at the top and the whole
page follows it.
"""

import customtkinter as ctk

from core import theme as T
from core.store import STORE
from ui.widgets import Card, heading

MONEYNESS = ["All", "ITM", "OTM"]
OPTION_TYPES = ["All", "Call", "Put"]
METHODS = ["Method 1", "Method 2"]


class ExecutionPage(ctk.CTkFrame):
    def __init__(self, master, shell):
        super().__init__(master, fg_color="transparent")
        self.shell = shell
        self.strategy = None
        self.fields = {}

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(22, 0))
        heading(head, "Execution",
                "Which strikes a strategy watches, how large each trade is, "
                "and when it is allowed to trade. Saved per strategy."
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
    def _row(self, parent, key, label, kind="entry", values=None, hint=""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text=label, font=T.f(12), text_color=T.TEXT_MUTED,
                     width=250, anchor="w").pack(side="left")
        if kind == "menu":
            var = ctk.StringVar(value=values[0])
            ctk.CTkOptionMenu(row, values=values, variable=var, width=150,
                              height=30, font=T.f(12), fg_color=T.PANEL_DEEP,
                              button_color=T.PANEL_HI,
                              dropdown_fg_color=T.PANEL).pack(side="left")
            self.fields[key] = var
        else:
            entry = ctk.CTkEntry(row, width=150, height=30, font=T.f(12),
                                 fg_color=T.PANEL_DEEP, border_color=T.BORDER)
            entry.pack(side="left")
            self.fields[key] = entry
        if hint:
            ctk.CTkLabel(row, text=hint, font=T.f(10), text_color=T.TEXT_DIM,
                         anchor="w", justify="left", wraplength=430
                         ).pack(side="left", padx=12)
        return row

    def _build(self):
        instrument = Card(self.scroll)
        instrument.pack(fill="x", pady=(2, 10))
        self._title(instrument, "INSTRUMENT AND SIZE")
        self._row(instrument, "instrument", "Instrument", "menu",
                  ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"])
        self._row(instrument, "lots", "Entry size (lots)",
                  hint="Multiplied by the contract lot size from the broker.")
        self._row(instrument, "style", "Trade style", "menu",
                  ["Intraday", "Positional"],
                  hint="Intraday is squared off at the time below. "
                       "Positional carries over and keeps being managed.")
        self._row(instrument, "broker", "Broker", "menu",
                  ["Dhan", "Kotak Neo", "Flattrade"],
                  hint="Only Dhan is connected in this build.")

        strikes = Card(self.scroll)
        strikes.pack(fill="x", pady=(0, 10))
        self._title(strikes, "STRIKE SELECTION")
        self._row(strikes, "strike_method", "Method", "menu", METHODS,
                  hint="Method 1 uses a percentage band around the "
                       "underlying. Method 2 counts strikes from the money.")
        self._row(strikes, "option_type", "Option type", "menu", OPTION_TYPES)
        self._row(strikes, "moneyness", "Moneyness", "menu", MONEYNESS)
        self._row(strikes, "allow_pct", "Allow strikes within (% of spot)",
                  hint="How far from the underlying a strike may be.")
        self._row(strikes, "ignore_pct", "Ignore strikes within (% of spot)",
                  hint="Drops the strikes nearest the money.")
        self._row(strikes, "step", "Strike step factor",
                  hint="1 takes every strike, 2 every second, and so on.")
        self._row(strikes, "premium_low", "Premium range, low")
        self._row(strikes, "premium_high", "Premium range, high",
                  hint="Strikes outside this are never subscribed.")
        self.overlap = ctk.CTkLabel(strikes, text="", font=T.f(11),
                                    text_color=T.AMBER, anchor="w",
                                    justify="left", wraplength=840)
        self.overlap.pack(anchor="w", padx=16, pady=(4, 12))

        limits = Card(self.scroll)
        limits.pack(fill="x", pady=(0, 10))
        self._title(limits, "TIMING AND LIMITS")
        self._row(limits, "entry_from", "Allow entries from (HH:MM)")
        self._row(limits, "entry_to", "Allow entries until (HH:MM)")
        self._row(limits, "square_off_time", "Square off at (HH:MM)",
                  hint="Ignored for positional strategies.")
        self._row(limits, "max_same_side", "Max same-side open positions",
                  hint="0 means no limit. When more strikes signal than "
                       "this allows, the first one to become active wins.")
        self._row(limits, "max_open_positions", "Max open positions",
                  hint="0 means no limit.")
        ctk.CTkLabel(limits, text="", font=T.f(4)).pack(pady=2)

    def _title(self, card, text):
        ctk.CTkLabel(card, text=text, font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=16,
                                                 pady=(13, 4))

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

    def _set(self, key, value):
        field = self.fields[key]
        if isinstance(field, ctk.StringVar):
            field.set(str(value))
        else:
            field.delete(0, "end")
            field.insert(0, "" if value is None else str(value))

    def _fill(self):
        s = self.strategy
        if not s:
            return
        f = s.strike_filter or {}
        self._set("instrument", s.instrument)
        self._set("lots", s.lots)
        self._set("style", s.style)
        self._set("broker", s.broker)
        self._set("strike_method", s.strike_method)
        self._set("option_type", f.get("option_type", "All"))
        self._set("moneyness", f.get("moneyness", "All"))
        self._set("allow_pct", f.get("allow_pct", 0.80))
        self._set("ignore_pct", f.get("ignore_pct", 0.35))
        self._set("step", f.get("step", 1))
        premium = s.params.get("C14", {})
        self._set("premium_low", f.get("premium_low", premium.get("lower", "")))
        self._set("premium_high",
                  f.get("premium_high", premium.get("upper", "")))
        self._set("entry_from", s.entry_from)
        self._set("entry_to", s.entry_to)
        self._set("square_off_time", s.square_off_time)
        self._set("max_same_side", s.max_same_side)
        self._set("max_open_positions", s.max_open_positions)
        self.msg.configure(text="", text_color=T.TEXT_MUTED)
        self._check_overlap()

    # ───────────────────────────────────────────────────────── overlap
    def _number(self, key, default=None):
        field = self.fields[key]
        raw = (field.get() if not isinstance(field, ctk.StringVar)
               else field.get()).strip()
        if raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            raise ValueError(key)

    def _check_overlap(self):
        """
        Warn when one premium range makes the other pointless, as the
        specification asks. It is a warning, never a block.
        """
        try:
            low = self._number("premium_low")
            high = self._number("premium_high")
        except ValueError:
            self.overlap.configure(text="")
            return
        c14 = (self.strategy.params.get("C14", {}) if self.strategy else {})
        c_low, c_high = c14.get("lower"), c14.get("upper")
        if None in (low, high, c_low, c_high):
            self.overlap.configure(text="")
            return
        if low <= c_low and high >= c_high:
            self.overlap.configure(
                text=(f"The strike filter range {low:g}–{high:g} fully "
                      f"contains condition C14's range {c_low:g}–{c_high:g}, "
                      f"so only C14 ever decides. The strike filter is doing "
                      f"nothing."))
        elif c_low <= low and c_high >= high:
            self.overlap.configure(
                text=(f"Condition C14's range {c_low:g}–{c_high:g} fully "
                      f"contains the strike filter range {low:g}–{high:g}, "
                      f"so only the strike filter ever decides. C14 is doing "
                      f"nothing."))
        else:
            self.overlap.configure(text="")

    # ───────────────────────────────────────────────────────── saving
    def _save(self):
        s = self.strategy
        if not s:
            return
        try:
            lots = int(self._number("lots", 1) or 1)
            allow = self._number("allow_pct", 0.80)
            ignore = self._number("ignore_pct", 0.0) or 0.0
            step = int(self._number("step", 1) or 1)
            low = self._number("premium_low")
            high = self._number("premium_high")
            same = int(self._number("max_same_side", 0) or 0)
            max_open = int(self._number("max_open_positions", 0) or 0)
        except ValueError as e:
            self.msg.configure(text=f"{e.args[0]} must be a number.",
                               text_color=T.RED)
            return

        if lots < 1:
            self.msg.configure(text="Entry size must be at least 1 lot.",
                               text_color=T.RED)
            return
        if low is not None and high is not None and low > high:
            self.msg.configure(
                text="The premium range low cannot be above the high.",
                text_color=T.RED)
            return
        for key in ("entry_from", "entry_to", "square_off_time"):
            raw = self.fields[key].get().strip()
            parts = raw.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                self.msg.configure(text=f"{key} must look like 09:20.",
                                   text_color=T.RED)
                return

        s.instrument = self.fields["instrument"].get()
        s.lots = lots
        s.style = self.fields["style"].get()
        s.broker = self.fields["broker"].get()
        s.strike_method = self.fields["strike_method"].get()
        s.entry_from = self.fields["entry_from"].get().strip()
        s.entry_to = self.fields["entry_to"].get().strip()
        s.square_off_time = self.fields["square_off_time"].get().strip()
        s.max_same_side = same
        s.max_open_positions = max_open
        s.strike_filter = {
            "option_type": self.fields["option_type"].get(),
            "moneyness": self.fields["moneyness"].get(),
            "allow_pct": allow, "ignore_pct": ignore, "step": step,
            "premium_low": low, "premium_high": high}
        STORE.save()
        self._check_overlap()
        self.msg.configure(text="Saved. Restart the engine to pick up "
                                "strike changes.", text_color=T.GREEN)
        self.shell.refresh_all()

    def refresh(self):
        self.reload()
