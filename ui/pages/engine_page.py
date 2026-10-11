"""
Engine page.

Starts the data engine and shows what it is actually doing: how many
strikes are being watched, how many have warmed up, how the feed is
behaving and which signals have fired.

The performance readout is deliberate. The broker will happily stream
25,000 instruments; the limit that bites first is the indicator maths on
this machine. Showing series count, tick rate and evaluation count means
a slowdown appears as a number rather than as unexplained lag.

Orders are placed through the order manager, so exits always outrank
entries and nothing is fired in a loop. Targets, stop-losses and the
profit locks arrive in the next build; what closes a position today is an
exit condition, the square-off time, or the Exit all button.
"""

import customtkinter as ctk

from core import theme as T
from core import dhan
from core.store import STORE
from ui.widgets import Card, heading

REFRESH_MS = 1000


class EnginePage(ctk.CTkFrame):
    def __init__(self, master, shell):
        super().__init__(master, fg_color="transparent")
        self.shell = shell
        self.engine = shell.engine
        self._ticking = False

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(22, 0))
        heading(head, "Engine",
                "Watches strikes, warms up the indicators, raises signals and "
                "places orders. Exits always go out before entries."
                ).pack(anchor="w")

        bar = Card(self)
        bar.pack(fill="x", padx=26, pady=(14, 0))
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)
        self.start_btn = ctk.CTkButton(row, text="Start engine", width=140,
                                       height=38, font=T.f(13, "bold"),
                                       fg_color=T.GREEN_DEEP,
                                       hover_color=T.GREEN,
                                       command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ctk.CTkButton(row, text="Stop", width=90, height=38,
                                      font=T.f(12), fg_color=T.PANEL_DEEP,
                                      hover_color=T.RED_DEEP,
                                      text_color=T.RED, command=self._stop,
                                      state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ctk.CTkButton(row, text="Exit all positions", width=150, height=38,
                      font=T.f(12, "bold"), fg_color=T.PANEL_DEEP,
                      hover_color=T.RED_DEEP, text_color=T.RED,
                      command=self._exit_all).pack(side="left", padx=(0, 8))
        self.state = ctk.CTkLabel(row, text="Stopped.", font=T.f(12),
                                  text_color=T.TEXT_MUTED, anchor="w",
                                  justify="left", wraplength=560)
        self.state.pack(side="left", padx=12)

        # ---- live numbers
        self.tiles = {}
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=26, pady=(12, 0))
        names = [("strikes", "Strikes watched"), ("warm", "Warm"),
                 ("series", "Live series"), ("connections", "Feed sockets"),
                 ("ticks", "Ticks / sec"), ("evals", "Evaluations"),
                 ("signals", "Signals"), ("open", "Open positions"),
                 ("queued", "Orders queued"), ("filled", "Orders filled"),
                 ("errors", "Error basket"), ("pnl", "Total P&L")]
        for i, (key, label) in enumerate(names):
            grid.grid_columnconfigure(i % 4, weight=1)
            tile = Card(grid)
            tile.grid(row=i // 4, column=i % 4, sticky="nsew", padx=3, pady=3)
            ctk.CTkLabel(tile, text=label.upper(), font=T.f(9, "bold"),
                         text_color=T.TEXT_DIM).pack(anchor="w", padx=12,
                                                     pady=(10, 0))
            value = ctk.CTkLabel(tile, text="0", font=T.f(18, "bold"),
                                 text_color=T.TEXT)
            value.pack(anchor="w", padx=12, pady=(0, 11))
            self.tiles[key] = value

        # ---- universes
        self.uni_card = Card(self)
        self.uni_card.pack(fill="x", padx=26, pady=(12, 0))
        ctk.CTkLabel(self.uni_card, text="STRIKE UNIVERSE",
                     font=T.f(10, "bold"), text_color=T.TEXT_DIM
                     ).pack(anchor="w", padx=16, pady=(13, 4))
        self.uni_body = ctk.CTkFrame(self.uni_card, fg_color="transparent")
        self.uni_body.pack(fill="x", padx=16, pady=(0, 13))

        # ---- open positions
        pos = Card(self)
        pos.pack(fill="x", padx=26, pady=(12, 0))
        ctk.CTkLabel(pos, text="OPEN POSITIONS", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=16,
                                                 pady=(13, 4))
        ph = ctk.CTkFrame(pos, fg_color=T.PANEL_DEEP, corner_radius=6)
        ph.pack(fill="x", padx=16)
        for name, width in (("Strategy", 140), ("Strike", 170), ("Qty", 60),
                            ("Entry", 70), ("LTP", 70), ("MTM", 85),
                            ("Charges", 80), ("Net", 85), ("Mode", 65)):
            ctk.CTkLabel(ph, text=name, font=T.f(10, "bold"), width=width,
                         anchor="w", text_color=T.TEXT_DIM
                         ).pack(side="left", padx=4, pady=6)
        self.pos_body = ctk.CTkFrame(pos, fg_color="transparent")
        self.pos_body.pack(fill="x", padx=16, pady=(2, 13))

        # ---- error basket
        err = Card(self)
        err.pack(fill="x", padx=26, pady=(12, 0))
        eh = ctk.CTkFrame(err, fg_color="transparent")
        eh.pack(fill="x", padx=16, pady=(13, 4))
        ctk.CTkLabel(eh, text="ERROR BASKET", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(side="left")
        ctk.CTkButton(eh, text="Clear", width=70, height=26, font=T.f(11),
                      fg_color=T.PANEL_DEEP, hover_color=T.PANEL_HI,
                      text_color=T.TEXT_MUTED,
                      command=self._clear_errors).pack(side="right")
        ctk.CTkButton(eh, text="Retry all", width=90, height=26,
                      font=T.f(11, "bold"), fg_color=T.PANEL_DEEP,
                      hover_color=T.PANEL_HI, text_color=T.AMBER,
                      command=self._retry_all).pack(side="right", padx=6)
        self.err_body = ctk.CTkFrame(err, fg_color="transparent")
        self.err_body.pack(fill="x", padx=16, pady=(2, 13))

        # ---- signals
        sig = Card(self)
        sig.pack(fill="both", expand=True, padx=26, pady=(12, 20))
        ctk.CTkLabel(sig, text="SIGNALS", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=16,
                                                 pady=(13, 4))
        header = ctk.CTkFrame(sig, fg_color=T.PANEL_DEEP, corner_radius=6)
        header.pack(fill="x", padx=16)
        for name, width in (("Time", 80), ("Strategy", 170), ("Strike", 190),
                            ("Price", 80), ("State", 90), ("Entry", 80)):
            ctk.CTkLabel(header, text=name, font=T.f(10, "bold"), width=width,
                         anchor="w", text_color=T.TEXT_DIM
                         ).pack(side="left", padx=4, pady=6)
        self.sig_body = ctk.CTkScrollableFrame(sig, fg_color="transparent",
                                               height=200)
        self.sig_body.pack(fill="both", expand=True, padx=16, pady=(2, 14))
        self._empty = ctk.CTkLabel(self.sig_body, text="Nothing yet.",
                                   font=T.f(12), text_color=T.TEXT_MUTED)
        self._empty.pack(pady=16)

    # ------------------------------------------------------------ actions
    def _start(self):
        if not dhan.CLIENT.connected:
            self.state.configure(
                text="Connect Dhan on the Brokers page first.",
                text_color=T.AMBER)
            return
        ready = [s for s in STORE.bank.strategies if s.summary()]
        if not ready:
            self.state.configure(
                text="No complete strategy to run. Build one and save it.",
                text_color=T.AMBER)
            return
        live = [s.name for s in ready if s.mode == "Live"]
        if live:
            dialog = ctk.CTkInputDialog(
                title="Live strategies",
                text=("These will place REAL orders:\n\n  "
                      + "\n  ".join(live)
                      + "\n\nType  GO  to start."))
            if (dialog.get_input() or "").strip().upper() != "GO":
                self.state.configure(text="Not started.",
                                     text_color=T.TEXT_MUTED)
                return
        if self.engine.start(ready):
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.state.configure(text="Starting...", text_color=T.TEXT_MUTED)
            self._tick()
        else:
            self.state.configure(text=self.engine.last_error, text_color=T.RED)

    def _exit_all(self):
        count = self.engine.exit_all()
        self.state.configure(
            text=(f"Exit sent for {count} position"
                  f"{'s' if count != 1 else ''}." if count
                  else "Nothing is open."),
            text_color=T.AMBER if count else T.TEXT_MUTED)

    def _retry_all(self):
        self.engine.orders.retry_all()
        self._paint()

    def _clear_errors(self):
        self.engine.orders.clear_errors()
        self._paint()

    def _stop(self):
        self.engine.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.state.configure(text="Stopped.", text_color=T.TEXT_MUTED)

    # ------------------------------------------------------------ paint
    def _tick(self):
        if not self.winfo_exists():
            return
        self._paint()
        if self.engine.status not in ("stopped",):
            self.after(REFRESH_MS, self._tick)

    def _paint(self):
        snap = self.engine.snapshot()
        feed = snap["feed"]
        orders, pos = snap["orders"], snap["positions"]
        self.tiles["strikes"].configure(text=str(snap["strikes"]))
        self.tiles["warm"].configure(
            text=f"{snap['warm']}"
                 + (f"  ({snap['partial']} partial)" if snap["partial"] else ""))
        self.tiles["series"].configure(text=str(snap["series"]))
        self.tiles["connections"].configure(text=f"{feed['connections']} / 5")
        self.tiles["ticks"].configure(text=str(feed["ticks_per_sec"]))
        self.tiles["evals"].configure(text=f"{snap['evaluations']:,}")
        self.tiles["signals"].configure(text=str(snap["signals"]))
        self.tiles["open"].configure(text=str(pos["open"]))
        self.tiles["queued"].configure(text=str(orders["queued"]))
        self.tiles["filled"].configure(text=str(orders["filled"]))
        self.tiles["errors"].configure(
            text=str(orders["errors"]),
            text_color=T.RED if orders["errors"] else T.TEXT)
        total = pos["total"]
        self.tiles["pnl"].configure(
            text=f"\u20b9 {total:,.0f}",
            text_color=T.GREEN if total > 0 else (T.RED if total < 0 else T.TEXT))

        colour = {"running": T.GREEN, "failed": T.RED,
                  "stopped": T.TEXT_MUTED}.get(snap["status"], T.AMBER)
        text = snap["status"].capitalize()
        if snap["pending_backfill"]:
            text += f"  \u00b7  {snap['pending_backfill']} strikes waiting for history"
        if snap["error"]:
            text += f"  \u00b7  {snap['error']}"
        self.state.configure(text=text, text_color=colour)

        for w in self.uni_body.winfo_children():
            w.destroy()
        if not snap["universes"]:
            ctk.CTkLabel(self.uni_body, text="Not started.", font=T.f(11),
                         text_color=T.TEXT_DIM).pack(anchor="w")
        for u in snap["universes"]:
            spot = f"{u['spot']:,.2f}" if u["spot"] else "waiting for a tick"
            ctk.CTkLabel(
                self.uni_body,
                text=(f"{u['underlying']}   expiry {u['expiry'] or '-'}   "
                      f"spot {spot}   {u['strikes']} strikes   lot {u['lot']}"),
                font=T.fm(11), text_color=T.TEXT_MUTED, anchor="w"
            ).pack(anchor="w", pady=1)

        for w in self.pos_body.winfo_children():
            w.destroy()
        positions = self.engine.open_positions()
        if not positions:
            ctk.CTkLabel(self.pos_body, text="Nothing open.", font=T.f(11),
                         text_color=T.TEXT_DIM).pack(anchor="w", pady=6)
        for p in positions:
            line = ctk.CTkFrame(self.pos_body, fg_color=T.PANEL_DEEP,
                                corner_radius=6)
            line.pack(fill="x", pady=1)
            mtm_colour = (T.GREEN if p["mtm"] > 0
                          else T.RED if p["mtm"] < 0 else T.TEXT)
            net_colour = (T.GREEN if p["net"] > 0
                          else T.RED if p["net"] < 0 else T.TEXT)
            for text, width, colour in (
                    (p["strategy"], 140, T.TEXT),
                    (p["strike"], 170, T.ACCENT_HI),
                    (p["qty"], 60, T.TEXT),
                    (f"{p['entry']:.2f}", 70, T.TEXT_MUTED),
                    (f"{p['ltp']:.2f}", 70, T.TEXT),
                    (f"{p['mtm']:,.0f}", 85, mtm_colour),
                    (f"-{p['charges']:,.0f}", 80, T.AMBER),
                    (f"{p['net']:,.0f}", 85, net_colour),
                    (p["mode"], 65, T.TEXT_DIM)):
                ctk.CTkLabel(line, text=str(text), font=T.f(11), width=width,
                             anchor="w", text_color=colour
                             ).pack(side="left", padx=4, pady=6)

        for w in self.err_body.winfo_children():
            w.destroy()
        errors = self.engine.errors(12)
        if not errors:
            ctk.CTkLabel(self.err_body, text="Empty.", font=T.f(11),
                         text_color=T.TEXT_DIM).pack(anchor="w", pady=6)
        for e in errors:
            ctk.CTkLabel(
                self.err_body,
                text=(f"{e['at']}   {e['side']} {e['strike']} x{e['qty']}"
                      f"   —   {e['error']}"),
                font=T.f(11), text_color=T.RED, anchor="w", justify="left",
                wraplength=900).pack(anchor="w", pady=2)

        rows = self.engine.recent_signals(30)
        for w in self.sig_body.winfo_children():
            w.destroy()
        if not rows:
            ctk.CTkLabel(self.sig_body, text="Nothing yet.", font=T.f(12),
                         text_color=T.TEXT_MUTED).pack(pady=16)
            return
        tint = {"taken": T.GREEN, "waiting": T.AMBER, "dropped": T.TEXT_DIM}
        for r in rows:
            line = ctk.CTkFrame(self.sig_body, fg_color=T.PANEL_DEEP,
                                corner_radius=6)
            line.pack(fill="x", pady=1)
            cells = [(r["time"], 80, T.TEXT_MUTED),
                     (r["strategy"], 170, T.TEXT),
                     (r["strike"], 190, T.ACCENT_HI),
                     (f"{r['price']:.2f}" if r["price"] else "-", 80, T.TEXT),
                     (r["state"], 90, tint.get(r["state"], T.TEXT_MUTED)),
                     (f"{r['entry']:.2f}" if r["entry"] else "-", 80, T.TEXT)]
            for text, width, colour in cells:
                ctk.CTkLabel(line, text=str(text), font=T.f(11), width=width,
                             anchor="w", text_color=colour
                             ).pack(side="left", padx=4, pady=6)

    def refresh(self):
        self._paint()
