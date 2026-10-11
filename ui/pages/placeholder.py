"""Pages that arrive in the next build. They list exactly what will be here."""

import customtkinter as ctk
from core import theme as T
from ui.widgets import Card, heading

PLANNED = {
    "Execution": [
        "A screen for the strike filters the engine already reads -- option "
        "type, moneyness, allow / ignore percentage of the underlying, step "
        "factor and premium range, per strategy",
        "Strike selection Method 2 -- exclude first X strikes, include first "
        "Y strikes, use current expiry if at least N days away",
        "Overlap warning when one premium range fully contains the other",
        "Entry signal time window and hard square-off time",
        "Max same-side open signals and max open positions, with the ranking "
        "rule for when more strikes pass than the limit allows",
        "Limit order buffer, wait seconds, reprice attempts, maximum slippage",
    ],
    "Targets": [
        "Four targets and four stop-losses, each with rate % and quantity %",
        "Trailing lock profit, ten levels, per position",
        "Profit locking per strategy, and across all strategies combined",
        "Day profit and day loss limits, per strategy and combined",
        "The eleven-step exit precedence from Section 8 of the specification",
    ],
    "Brokers": [],
    "Copy trade": [
        "Master and child account list with net quantity, MTM, cash, margin",
        "Per child multiplier -- fixed lots, multiple of master, or by capital",
        "Auto push, retry imbalanced orders N times, manual balance",
        "Square off one account, all children, or everything",
    ],
    "Security": [
        "Password protection -- deferred until the software is finished",
        "Export and import a backup of the bank",
        "Licensing controls -- allowed strategies, allowed broker logins, "
        "prefilled client codes, broker login scope, editing rights, "
        "copy trade enable",
    ],
}


class PlaceholderPage(ctk.CTkFrame):
    def __init__(self, master, shell, title):
        super().__init__(master, fg_color="transparent")
        heading(self, title,
                "Laid out in the specification. Arriving in the next build."
                ).pack(anchor="w", padx=26, pady=(22, 14))
        card = Card(self)
        card.pack(fill="x", padx=26)
        ctk.CTkLabel(card, text="WHAT GOES HERE", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=18,
                                                 pady=(14, 8))
        for item in PLANNED.get(title, []):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=3)
            ctk.CTkLabel(row, text="\u25aa", font=T.f(12),
                         text_color=T.ACCENT).pack(side="left", anchor="n")
            ctk.CTkLabel(row, text=item, font=T.f(12), text_color=T.TEXT_MUTED,
                         anchor="w", justify="left", wraplength=760
                         ).pack(side="left", padx=8)
        ctk.CTkLabel(card, text="", font=T.f(6)).pack(pady=6)

    def refresh(self):
        pass
