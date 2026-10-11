"""Main window: sidebar navigation plus the page area."""

import customtkinter as ctk
from core import theme as T
from core import dhan
from core.engine import Engine
from core.store import STORE
from ui.pages.condition_bank import ConditionBankPage
from ui.pages.strategy_builder import StrategyBuilderPage
from ui.pages.dashboard import DashboardPage
from ui.pages.placeholder import PlaceholderPage
from ui.pages.brokers import BrokersPage
from ui.pages.engine_page import EnginePage
from ui.pages.execution import ExecutionPage
from ui.pages.targets import TargetsPage

NAV = [("Dashboard", "\u25f0"), ("Condition Bank", "\u25c8"),
       ("Strategy Builder", "\u2699"), ("Brokers", "\u26a1"),
       ("Engine", "\u25b6"), ("Execution", "\u2708"),
       ("Targets", "\u25ce"), ("Copy trade", "\u29c9"),
       ("Security", "\u26bf")]


class Shell(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{T.APP_NAME}  v{T.APP_VERSION}")
        self.configure(fg_color=T.BG)
        self.geometry("1440x880")
        self.minsize(1180, 720)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=0, width=232)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)

        ctk.CTkLabel(side, text="BALFUND", font=T.f(11, "bold"),
                     text_color=T.ACCENT).pack(anchor="w", padx=22, pady=(24, 0))
        ctk.CTkLabel(side, text="Condition Bank", font=T.f(19, "bold"),
                     text_color=T.TEXT).pack(anchor="w", padx=22)
        ctk.CTkFrame(side, height=1, fg_color=T.BORDER).pack(fill="x", padx=18,
                                                             pady=16)

        self.buttons = {}
        for name, icon in NAV:
            b = ctk.CTkButton(side, text=f"  {icon}   {name}", anchor="w",
                              height=40, corner_radius=8, font=T.f(13),
                              fg_color="transparent", hover_color=T.PANEL_HI,
                              text_color=T.TEXT_MUTED,
                              command=lambda n=name: self.show(n))
            b.pack(fill="x", padx=12, pady=2)
            self.buttons[name] = b

        self.status = ctk.CTkLabel(side, text="", font=T.f(10),
                                   text_color=T.TEXT_DIM, wraplength=190,
                                   justify="left")
        self.status.pack(side="bottom", anchor="w", padx=22, pady=18)

        self.area = ctk.CTkFrame(self, fg_color="transparent")
        self.area.grid(row=0, column=1, sticky="nsew")

        # One engine, shared by the Engine page and the Dashboard.
        self.engine = Engine(dhan.CLIENT)

        self.pages = {}
        self.current = None
        self.show("Dashboard")
        # build the heavy pages once, in the background, so the first click
        # on them is instant instead of waiting for 23 cards to be created
        self.after(120, lambda: self._warm("Condition Bank"))
        self.after(360, lambda: self._warm("Strategy Builder"))

    def _warm(self, name):
        if name not in self.pages:
            self.pages[name] = self._build(name)

    # ------------------------------------------------------------ paging
    def _build(self, name):
        if name == "Dashboard":
            return DashboardPage(self.area, self)
        if name == "Condition Bank":
            return ConditionBankPage(self.area, self)
        if name == "Strategy Builder":
            return StrategyBuilderPage(self.area, self)
        if name == "Brokers":
            return BrokersPage(self.area, self)
        if name == "Engine":
            return EnginePage(self.area, self)
        if name == "Execution":
            return ExecutionPage(self.area, self)
        if name == "Targets":
            return TargetsPage(self.area, self)
        return PlaceholderPage(self.area, self, name)

    def show(self, name):
        current_page = self.current
        if (current_page is not None
                and hasattr(current_page, "confirm_leave")
                and not current_page.confirm_leave()):
            return
        if name not in self.pages:
            self.pages[name] = self._build(name)
        if self.current:
            self.current.pack_forget()
        page = self.pages[name]
        page.pack(fill="both", expand=True)
        self.current = page
        for key, button in self.buttons.items():
            live = key == name
            button.configure(
                fg_color=T.ACCENT if live else "transparent",
                text_color=T.TEXT if live else T.TEXT_MUTED)
        if hasattr(page, "refresh"):
            page.refresh()
        self._status()

    def mark_data_changed(self):
        """Strategies were added, edited or removed."""
        for page in self.pages.values():
            if hasattr(page, "mark_dirty"):
                page.mark_dirty()
        self.refresh_all()

    def refresh_all(self):
        for name, page in self.pages.items():
            if hasattr(page, "refresh") and page is not self.current:
                try:
                    page.refresh()
                except Exception:
                    pass
        self._status()

    def _status(self):
        n = len(STORE.bank.strategies) if STORE.bank else 0
        ready = sum(1 for s in STORE.bank.strategies if s.summary()) if n else 0
        self.status.configure(
            text=f"{n} strateg{'y' if n == 1 else 'ies'}  \u00b7  "
                 f"{ready} ready")

    def toast(self, message):
        self.status.configure(text=message)
        self.after(4000, self._status)
