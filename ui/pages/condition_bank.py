"""
Condition Bank page.

Every card is built once, the first time the page is created, and then only
shown or hidden as the filter changes.  Nothing is destroyed and rebuilt, and
no CTkTextbox is used, so switching to this page is instant.
"""

import customtkinter as ctk
from core import theme as T, conditions as C
from core.store import STORE
from ui.widgets import Card, heading

GROUPS = ("All", "Entry", "Exit", "Late entry")
_G = {"Entry": "entry", "Exit": "exit", "Late entry": "late"}


class ConditionBankPage(ctk.CTkFrame):
    def __init__(self, master, shell):
        super().__init__(master, fg_color="transparent")
        self.shell = shell
        self.group = "All"
        self.query = ""
        self.cards = {}
        self._dirty = True

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(22, 0))
        heading(head, "The Condition Bank",
                "Every condition lives here once and can be used by any number "
                "of strategies. Settings are chosen per strategy in the "
                "Strategy Builder.").pack(anchor="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=26, pady=(16, 10))

        self.search = ctk.CTkEntry(bar, width=280, height=36,
                                   placeholder_text="Search conditions...",
                                   font=T.f(12), fg_color=T.PANEL,
                                   border_color=T.BORDER)
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", self._on_search)

        self.seg = ctk.CTkSegmentedButton(
            bar, values=list(GROUPS), font=T.f(12), height=36,
            fg_color=T.PANEL, selected_color=T.ACCENT,
            selected_hover_color=T.ACCENT_DEEP, unselected_color=T.PANEL,
            unselected_hover_color=T.PANEL_HI, text_color=T.TEXT,
            command=self._on_group)
        self.seg.set("All")
        self.seg.pack(side="left", padx=14)

        self.count = ctk.CTkLabel(bar, text="", font=T.f(12),
                                  text_color=T.TEXT_MUTED)
        self.count.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.scroll.grid_columnconfigure((0, 1), weight=1, uniform="col")

        self.empty = ctk.CTkLabel(self.scroll,
                                  text="Nothing matches that search.",
                                  font=T.f(13), text_color=T.TEXT_MUTED)

        self._build_cards()
        self._apply_filter()

    # ------------------------------------------------------------ building
    def _build_cards(self):
        """Runs once. After this the page only ever re-grids existing cards."""
        for cond in C.REGISTER:
            colour = T.GROUP_COLOR[cond.group]
            card = Card(self.scroll, stripe=colour)
            b = card.body

            top = ctk.CTkFrame(b, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(top, text=cond.cid, font=T.fm(15, "bold"),
                         text_color=colour).pack(side="left")
            ctk.CTkLabel(top, text=T.GROUP_LABEL[cond.group],
                         font=T.f(9, "bold"), text_color=T.TEXT_DIM
                         ).pack(side="left", padx=(9, 0))
            usage = ctk.CTkLabel(top, text="", font=T.f(10, "bold"),
                                 text_color=T.GREEN, fg_color=T.PANEL_DEEP,
                                 corner_radius=8)
            usage.pack(side="right")

            ctk.CTkLabel(b, text=cond.name, font=T.f(14, "bold"),
                         text_color=T.TEXT, anchor="w", justify="left",
                         wraplength=380).pack(fill="x", pady=(6, 2))
            ctk.CTkLabel(b, text=cond.plain, font=T.f(11),
                         text_color=T.TEXT_MUTED, anchor="w", justify="left",
                         wraplength=380).pack(fill="x", pady=(0, 8))

            # a plain label instead of a CTkTextbox -- far cheaper to create
            fbox = ctk.CTkFrame(b, fg_color=T.PANEL_DEEP, corner_radius=6)
            fbox.pack(fill="x")
            ctk.CTkLabel(fbox, text=cond.formula, font=T.fm(11),
                         text_color=colour, anchor="w", justify="left"
                         ).pack(fill="x", padx=10, pady=8)

            names = ", ".join(p.label for p in cond.params) or "no settings"
            ctk.CTkLabel(b, text=f"Settings:  {names}", font=T.f(10),
                         text_color=T.TEXT_DIM, anchor="w", justify="left",
                         wraplength=380).pack(fill="x", pady=(8, 0))

            self.cards[cond.cid] = (card, usage)

    # ------------------------------------------------------------- events
    def _on_search(self, _=None):
        self.query = self.search.get().strip().lower()
        self._apply_filter()

    def _on_group(self, value):
        self.group = value
        self._apply_filter()

    def _matches(self, c: C.Condition) -> bool:
        if self.group != "All" and c.group != _G[self.group]:
            return False
        if not self.query:
            return True
        return self.query in f"{c.cid} {c.name} {c.plain} {c.phrase}".lower()

    def _apply_filter(self):
        shown = 0
        self.empty.grid_forget()
        for cond in C.REGISTER:
            card, _ = self.cards[cond.cid]
            if self._matches(cond):
                card.grid(row=shown // 2, column=shown % 2, sticky="nsew",
                          padx=6, pady=6)
                shown += 1
            else:
                card.grid_remove()
        self.count.configure(text=f"{shown} of {len(C.REGISTER)} conditions")
        if not shown:
            self.empty.grid(row=0, column=0, columnspan=2, pady=40)

    # ------------------------------------------------------------- refresh
    def mark_dirty(self):
        self._dirty = True

    def refresh(self):
        """Only the usage badges can change, so only they are redrawn."""
        if not self._dirty:
            return
        for cid, (_, usage) in self.cards.items():
            n = STORE.usage_count(cid) if STORE.bank else 0
            usage.configure(text=f"  used in {n}  " if n else "")
        self._dirty = False
