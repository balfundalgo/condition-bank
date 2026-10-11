"""
Dashboard page -- the layout from the specification.

The figures are live when the engine is running: booked, MTM, capital,
traded value, open positions and errors all come from the position book.

The day limits and the two profit-lock tables are Phase 4. They are shown
here so the layout is settled, and they are clearly marked as not yet
acting on anything.
"""

import customtkinter as ctk
from core import theme as T, expression as E
from core import charges as CH
from core.positions import BOOK
from core.store import STORE
from ui.widgets import Card, heading

KPI_KEYS = [("capital", "Total capital used"), ("booked", "Booked profit / loss"),
            ("mtm", "MTM profit / loss"), ("total", "Gross profit"),
            ("charges", "Charges"), ("net", "Net after charges"),
            ("traded", "Total traded value"), ("open", "Open positions"),
            ("errors", "Errors")]

COLS = [("#", 34), ("Strategy", 190), ("Booked", 90), ("MTM", 90),
        ("Total", 90), ("Capital", 95), ("Traded value", 105),
        ("Open", 55), ("Err", 45), ("Status", 105), ("Mode", 95)]

LOCK_ROWS = [(10000, 5000), (20000, 10000), (30000, 20000), (40000, 30000),
             (50000, 40000), (60000, 50000), (70000, 60000), (80000, 70000),
             (90000, 80000), (100000, 100000)]


class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, shell):
        super().__init__(master, fg_color="transparent")
        self.shell = shell
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=16)
        self._dirty = False
        self.build()

    def build(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        heading(self.scroll, "Dashboard",
                "Everything running, on one screen. The engine is connected "
                "in the next build -- the layout and controls are live."
                ).pack(anchor="w", padx=6, pady=(4, 14))

        # ---- KPI strip
        strip = ctk.CTkFrame(self.scroll, fg_color="transparent")
        strip.pack(fill="x", padx=6)
        self.kpis = {}
        per_row = 5
        for i, (key, label) in enumerate(KPI_KEYS):
            strip.grid_columnconfigure(i % per_row, weight=1)
            box = Card(strip)
            box.grid(row=i // per_row, column=i % per_row, sticky="nsew",
                     padx=3, pady=3)
            ctk.CTkLabel(box, text=label.upper(), font=T.f(9, "bold"),
                         text_color=T.TEXT_DIM).pack(anchor="w", padx=12,
                                                     pady=(11, 0))
            value = ctk.CTkLabel(box, text="-", font=T.f(17, "bold"),
                                 text_color=T.TEXT)
            value.pack(anchor="w", padx=12, pady=(1, 12))
            self.kpis[key] = value

        # ---- strategy table
        table = Card(self.scroll)
        table.pack(fill="x", padx=6, pady=(12, 0))
        th = ctk.CTkFrame(table, fg_color="transparent")
        th.pack(fill="x", padx=14, pady=(13, 4))
        ctk.CTkLabel(th, text="STRATEGY PERFORMANCE", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(side="left")
        ctk.CTkButton(th, text="Deploy all", width=100, height=28,
                      font=T.f(11, "bold"), fg_color=T.GREEN_DEEP,
                      hover_color=T.GREEN, command=self._deploy_all
                      ).pack(side="right")
        ctk.CTkButton(th, text="Manual exit and stop", width=160, height=28,
                      font=T.f(11, "bold"), fg_color=T.PANEL_DEEP,
                      hover_color=T.RED_DEEP, text_color=T.RED,
                      command=self._stop_all).pack(side="right", padx=8)

        header = ctk.CTkFrame(table, fg_color=T.PANEL_DEEP, corner_radius=6)
        header.pack(fill="x", padx=14, pady=(4, 2))
        for name, width in COLS:
            ctk.CTkLabel(header, text=name, font=T.f(10, "bold"), width=width,
                         anchor="w", text_color=T.TEXT_DIM
                         ).pack(side="left", padx=4, pady=6)

        self.rows = ctk.CTkFrame(table, fg_color="transparent")
        self.rows.pack(fill="x", padx=14, pady=(0, 14))
        self._draw_rows()

        # ---- three control panels
        panels = ctk.CTkFrame(self.scroll, fg_color="transparent")
        panels.pack(fill="x", padx=6, pady=(12, 0))
        panels.grid_columnconfigure((0, 1), weight=1, uniform="p")
        panels.grid_columnconfigure(2, weight=2)
        self._limit_panel(panels, "Exit all open positions if day profit >=",
                          20000, T.GREEN).grid(row=0, column=0, sticky="new",
                                               padx=(0, 5))
        self._limit_panel(panels, "Exit all open positions if day loss >=",
                          20000, T.RED).grid(row=0, column=1, sticky="new",
                                             padx=5)
        self._lock_panel(panels).grid(row=0, column=2, sticky="nsew",
                                      padx=(5, 0))

        # ---- charges
        self._charges_card().pack(fill="x", padx=6, pady=(12, 0))

        # ---- quick exits
        quick = Card(self.scroll)
        quick.pack(fill="x", padx=6, pady=(12, 6))
        ctk.CTkLabel(quick, text="QUICK EXIT ACTIONS", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=14,
                                                 pady=(12, 6))
        strip = ctk.CTkFrame(quick, fg_color="transparent")
        strip.pack(fill="x", padx=14, pady=(0, 8))
        for label in ("Exit TG1", "Exit TG1 + TG2", "Exit TG1 + TG2 + TG3",
                      "Exit selected"):
            ctk.CTkButton(strip, text=label, height=36, font=T.f(12, "bold"),
                          fg_color=T.PANEL_DEEP, hover_color=T.PANEL_HI,
                          text_color=T.ACCENT_HI).pack(side="left",
                                                       expand=True, fill="x",
                                                       padx=4)
        ctk.CTkButton(quick, text="EXIT ALL", height=40, font=T.f(13, "bold"),
                      fg_color=T.RED_DEEP, hover_color=T.RED
                      ).pack(fill="x", padx=14, pady=(0, 14))

        self._paint_kpis()
        ctk.CTkLabel(self.scroll,
                     text="Day limits and profit locking are shown here but "
                          "do not act yet -- they arrive in the next build. "
                          "Manual exit closes all open positions immediately. "
                          "All values are in INR.",
                     font=T.f(10), text_color=T.TEXT_DIM
                     ).pack(anchor="w", padx=8, pady=(0, 8))

    # ------------------------------------------------------------- pieces
    def _charges_card(self):
        card = Card(self.scroll)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(13, 2))
        ctk.CTkLabel(head, text="CHARGES PER TRADE", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(side="left")
        ctk.CTkButton(head, text="Save rates", width=90, height=26,
                      font=T.f(11, "bold"), fg_color=T.PANEL_DEEP,
                      hover_color=T.PANEL_HI, text_color=T.ACCENT_HI,
                      command=self._save_rates).pack(side="right")
        ctk.CTkButton(head, text="Reset", width=70, height=26, font=T.f(11),
                      fg_color=T.PANEL_DEEP, hover_color=T.PANEL_HI,
                      text_color=T.TEXT_MUTED,
                      command=self._reset_rates).pack(side="right", padx=6)

        ctk.CTkLabel(
            card,
            text=("Applied to every trade and already included in Net. "
                  f"Rates last checked {CH.RATES_CHECKED} — check them "
                  "against a real contract note and correct them here if "
                  "they differ. GST applies to brokerage, exchange and SEBI "
                  "fees only, never to STT or stamp duty."),
            font=T.f(10), text_color=T.TEXT_DIM, justify="left",
            wraplength=960).pack(anchor="w", padx=14, pady=(2, 8))

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 6))
        self.rate_fields = {}
        rows = CH.describe(BOOK.rates)
        for i, (key, label, value) in enumerate(rows):
            col = (i % 2) * 2
            row = i // 2
            grid.grid_columnconfigure(col + 1, weight=1)
            text = label
            if key in CH.UNVERIFIED:
                text += "  (verify)"
            ctk.CTkLabel(grid, text=text, font=T.f(11),
                         text_color=(T.AMBER if key in CH.UNVERIFIED
                                     else T.TEXT_MUTED),
                         anchor="w", width=230
                         ).grid(row=row, column=col, sticky="w", pady=3)
            entry = ctk.CTkEntry(grid, height=28, font=T.f(11), width=120,
                                 fg_color=T.PANEL_DEEP, border_color=T.BORDER)
            entry.insert(0, str(value))
            entry.grid(row=row, column=col + 1, sticky="w", padx=(0, 24),
                       pady=3)
            self.rate_fields[key] = entry

        self.rate_msg = ctk.CTkLabel(card, text="", font=T.f(11),
                                     text_color=T.TEXT_MUTED, anchor="w",
                                     justify="left", wraplength=940)
        self.rate_msg.pack(anchor="w", padx=14, pady=(2, 12))
        self._show_example()
        return card

    def _show_example(self):
        """A worked example, so the rates are not abstract."""
        t = CH.round_trip(200.0, 220.0, 75, "NSE", BOOK.rates)
        parts = ", ".join(f"{CH.LABELS[k]} {v:,.2f}"
                          for k, v in t["lines"].items() if v)
        self.rate_msg.configure(
            text=(f"Example — 75 units bought at 200 and sold at 220:  "
                  f"{parts}.  Total {t['total']:,.2f} against a gross "
                  f"{t['gross']:,.0f}, so the price has to move "
                  f"Rs {t['breakeven_move']:.2f} per unit just to break even."))

    def _save_rates(self):
        values = {}
        for key, entry in self.rate_fields.items():
            try:
                values[key] = float(entry.get().strip())
            except ValueError:
                self.rate_msg.configure(
                    text=f"{key} must be a number.", text_color=T.RED)
                return
        rates = CH.ChargeRates.from_dict(values)
        BOOK.set_rates(rates)
        STORE.bank.settings["charges"] = rates.to_dict()
        STORE.save()
        self._show_example()
        self.rate_msg.configure(text_color=T.TEXT_MUTED)
        self.shell.toast("Charge rates saved.")
        self._paint_kpis()

    def _reset_rates(self):
        BOOK.set_rates(CH.ChargeRates())
        STORE.bank.settings.pop("charges", None)
        STORE.save()
        self.mark_dirty()
        self.build()
        self.shell.toast(f"Rates reset to the {CH.RATES_CHECKED} defaults.")

    def _live(self):
        engine = getattr(self.shell, "engine", None)
        if engine is None or engine.status == "stopped":
            return None
        return engine

    def _paint_kpis(self):
        engine = self._live()
        if engine is None:
            for key, label in self.kpis.items():
                label.configure(text="-", text_color=T.TEXT_DIM)
            return
        snap = engine.snapshot()
        pos, orders = snap["positions"], snap["orders"]
        money = {"capital": pos["capital"], "booked": pos["booked"],
                 "mtm": pos["mtm"], "total": pos["total"],
                 "charges": -pos["charges"], "net": pos["net"],
                 "traded": pos["traded"]}
        for key, value in money.items():
            colour = T.TEXT
            if key == "charges":
                colour = T.AMBER if value else T.TEXT
            elif key in ("booked", "mtm", "total", "net"):
                colour = (T.GREEN if value > 0
                          else T.RED if value < 0 else T.TEXT)
            self.kpis[key].configure(text=f"\u20b9 {value:,.0f}",
                                     text_color=colour)
        self.kpis["open"].configure(text=str(pos["open"]), text_color=T.TEXT)
        self.kpis["errors"].configure(
            text=str(orders["errors"]),
            text_color=T.RED if orders["errors"] else T.TEXT)

    def _draw_rows(self):
        for w in self.rows.winfo_children():
            w.destroy()
        strategies = STORE.bank.strategies
        if not strategies:
            ctk.CTkLabel(self.rows,
                         text="No strategies yet. Open the Strategy Builder "
                              "and create one.",
                         font=T.f(12), text_color=T.TEXT_MUTED).pack(pady=22)
            return
        engine = self._live()
        live_rows = {r["number"]: r for r in engine.strategy_rows()} \
            if engine else {}
        for s in strategies:
            row = ctk.CTkFrame(self.rows, fg_color=T.PANEL_DEEP,
                               corner_radius=6)
            row.pack(fill="x", pady=2)
            ready = s.summary()
            d = live_rows.get(s.number)
            if d:
                cells = [str(s.number), s.name,
                         f"{d['booked']:,.0f}", f"{d['mtm']:,.0f}",
                         f"{d['total']:,.0f}", f"{d['capital']:,.0f}",
                         f"{d['traded']:,.0f}", str(d["open"]), "0"]
            else:
                cells = [str(s.number), s.name, "0", "0", "0", "0", "0",
                         "0", "0"]
            for (name, width), value in zip(COLS, cells):
                ctk.CTkLabel(row, text=value, font=T.f(11), width=width,
                             anchor="w", text_color=T.TEXT
                             ).pack(side="left", padx=4, pady=7)
            if d:
                status, tint = "RUNNING", T.GREEN
            elif ready:
                status, tint = "READY", T.ACCENT_HI
            else:
                status, tint = "INCOMPLETE", T.AMBER
            ctk.CTkLabel(row, text=status, font=T.f(10, "bold"), width=105,
                         anchor="w", text_color=tint).pack(side="left", padx=4)
            mode = ctk.CTkOptionMenu(
                row, values=["Paper", "Live"], width=88, height=26,
                font=T.f(11, "bold"),
                fg_color=T.RED_DEEP if s.mode == "Live" else T.PANEL,
                button_color=T.RED if s.mode == "Live" else T.PANEL_HI,
                button_hover_color=T.RED if s.mode == "Live" else T.BORDER_HI,
                dropdown_fg_color=T.PANEL,
                text_color=T.TEXT if s.mode == "Live" else T.TEXT_MUTED,
                command=lambda choice, st=s: self._set_mode(st, choice))
            mode.set(s.mode)
            mode.pack(side="left", padx=4)

    def _limit_panel(self, master, title, default, colour):
        card = Card(master)
        ctk.CTkLabel(card, text=title.upper(), font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM, wraplength=250, justify="left"
                     ).pack(anchor="w", padx=14, pady=(13, 8))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14)
        entry = ctk.CTkEntry(row, width=120, height=34, font=T.f(13),
                             fg_color=T.PANEL_DEEP, border_color=T.BORDER)
        entry.insert(0, str(default))
        entry.pack(side="left")
        ctk.CTkLabel(row, text="INR", font=T.f(11),
                     text_color=T.TEXT_MUTED).pack(side="left", padx=8)
        ctk.CTkSwitch(row, text="", width=44, progress_color=colour
                      ).pack(side="right")
        bar = ctk.CTkProgressBar(card, height=6, progress_color=colour,
                                 fg_color=T.PANEL_DEEP)
        bar.set(0)
        bar.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(card, text="0% of limit reached", font=T.f(10),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=14,
                                                 pady=(0, 13))
        return card

    def _lock_panel(self, master):
        card = Card(master)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(13, 6))
        ctk.CTkLabel(head, text="PROFIT LOCKING (ALL STRATEGIES COMBINED)",
                     font=T.f(10, "bold"), text_color=T.TEXT_DIM
                     ).pack(side="left")
        ctk.CTkSwitch(head, text="", width=44,
                      progress_color=T.GREEN).pack(side="right")
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=14)
        for name, w in (("On", 40), ("Total profit >=", 150),
                        ("Lock profit at", 150)):
            ctk.CTkLabel(hdr, text=name, font=T.f(10, "bold"), width=w,
                         anchor="w", text_color=T.TEXT_DIM).pack(side="left")
        for total, lock in LOCK_ROWS:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=1)
            ctk.CTkCheckBox(row, text="", width=40, checkbox_width=16,
                            checkbox_height=16, fg_color=T.GREEN_DEEP
                            ).pack(side="left")
            for value in (total, lock):
                e = ctk.CTkEntry(row, width=146, height=24, font=T.f(11),
                                 fg_color=T.PANEL_DEEP, border_color=T.BORDER)
                e.insert(0, f"{value:,}")
                e.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(card,
                     text="Profit is locked when total profit reaches the "
                          "selected level. The floor only moves up.",
                     font=T.f(10), text_color=T.TEXT_DIM, wraplength=360,
                     justify="left").pack(anchor="w", padx=14, pady=(8, 13))
        return card

    def _set_mode(self, strategy, choice):
        """
        Switching between paper and live is the one setting that decides
        whether real money moves, so it is guarded twice.
        """
        if choice == strategy.mode:
            return

        engine = self._live()
        if engine is not None:
            open_now = [p for p in engine.book.open.values()
                        if p.strategy_number == strategy.number]
            if open_now:
                # A paper position closed by a live order would send a real
                # sell for stock that was never bought, and the reverse
                # would strand a real position in the paper book.
                self.shell.toast(
                    f"{strategy.name} has {len(open_now)} open position"
                    f"{'s' if len(open_now) != 1 else ''}. Close them before "
                    f"switching between paper and live.")
                self._draw_rows()
                return

        if choice == "Live":
            dialog = ctk.CTkInputDialog(
                title="Switch to live trading",
                text=(f"\"{strategy.name}\" will place REAL orders with real "
                      f"money on the connected broker.\n\n"
                      f"Type  LIVE  to confirm."))
            if (dialog.get_input() or "").strip().upper() != "LIVE":
                self.shell.toast("Left in paper mode.")
                self._draw_rows()
                return

        strategy.mode = choice
        STORE.save()
        self.shell.toast(
            f"{strategy.name} is now in {choice.lower()} mode."
            + ("  Real orders will be placed." if choice == "Live" else ""))
        self._draw_rows()
        self.shell.refresh_all()

    def _deploy_all(self):
        self.shell.show("Engine")

    def _stop_all(self):
        engine = self._live()
        if engine is None:
            self.shell.toast("Nothing is running.")
            return
        count = engine.exit_all()
        engine.stop()
        self.shell.toast(f"Exit sent for {count} position"
                         f"{'s' if count != 1 else ''}, engine stopped.")

    def mark_dirty(self):
        self._dirty = True

    def refresh(self):
        if getattr(self, "_dirty", True):
            self.build()
            self._dirty = False
        else:
            self._paint_kpis()
            self._draw_rows()
