"""
Brokers page.

Dhan first. The connection follows the proven order: check the saved
token, renew it if it has lapsed, and only generate a fresh one with TOTP
if neither works.

The client ID and the access token are saved. The PIN and the TOTP secret
are not written to disk — they are held for this session only, or read
from a .env file beside the application. Password protection for the bank
is deferred, so nothing sensitive is stored where it need not be.
"""

import os
import threading

import customtkinter as ctk

from core import theme as T
from core import dhan
from core.store import STORE, app_dir
from ui.widgets import Card, heading

ENV_PATH = os.path.join(app_dir(), ".env")


def _from_env(key):
    value = os.getenv(key, "")
    if value:
        return value.strip()
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip().startswith(f"{key}="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return ""


class BrokersPage(ctk.CTkFrame):
    def __init__(self, master, shell):
        super().__init__(master, fg_color="transparent")
        self.shell = shell

        heading(self, "Brokers",
                "Dhan is connected first. Kotak Neo and Flattrade are added "
                "later and will appear here alongside it."
                ).pack(anchor="w", padx=26, pady=(22, 14))

        card = Card(self)
        card.pack(fill="x", padx=26)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(head, text="DHAN", font=T.f(13, "bold"),
                     text_color=T.ACCENT).pack(side="left")
        self.dot = ctk.CTkLabel(head, text="\u25cf  not connected",
                                font=T.f(11, "bold"), text_color=T.TEXT_DIM)
        self.dot.pack(side="right")

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=18, pady=(8, 4))
        form.grid_columnconfigure(1, weight=1)

        settings = STORE.bank.settings if STORE.bank else {}
        self.fields = {}
        rows = [("client_id", "Client ID", False,
                 settings.get("dhan_client_id", "") or _from_env("DHAN_CLIENT_ID")),
                ("pin", "PIN", True, _from_env("DHAN_PIN")),
                ("totp", "TOTP secret", True, _from_env("DHAN_TOTP_SECRET")),
                ("token", "Access token (optional)", True,
                 settings.get("dhan_token", "") or _from_env("DHAN_ACCESS_TOKEN"))]
        for i, (key, label, secret, value) in enumerate(rows):
            ctk.CTkLabel(form, text=label, font=T.f(12),
                         text_color=T.TEXT_MUTED, width=170, anchor="w"
                         ).grid(row=i, column=0, sticky="w", pady=5)
            entry = ctk.CTkEntry(form, height=34, font=T.f(12),
                                 fg_color=T.PANEL_DEEP, border_color=T.BORDER,
                                 show="\u2022" if secret else "")
            if value:
                entry.insert(0, value)
            entry.grid(row=i, column=1, sticky="ew", pady=5)
            self.fields[key] = entry

        ctk.CTkLabel(card,
                     text="The PIN and TOTP secret are never written to disk. "
                          "Put them in a .env file next to the application if "
                          "you want them filled in automatically.",
                     font=T.f(10), text_color=T.TEXT_DIM, justify="left",
                     wraplength=700).pack(anchor="w", padx=18, pady=(6, 0))

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(12, 16))
        self.connect_btn = ctk.CTkButton(
            buttons, text="Connect", width=140, height=38,
            font=T.f(13, "bold"), fg_color=T.ACCENT,
            hover_color=T.ACCENT_DEEP, command=self._connect)
        self.connect_btn.pack(side="left")
        ctk.CTkButton(buttons, text="Check funds", width=130, height=38,
                      font=T.f(12), fg_color=T.PANEL_DEEP,
                      hover_color=T.PANEL_HI, text_color=T.TEXT_MUTED,
                      command=self._funds).pack(side="left", padx=8)
        self.msg = ctk.CTkLabel(buttons, text="", font=T.f(11),
                                text_color=T.TEXT_MUTED, anchor="w",
                                justify="left", wraplength=420)
        self.msg.pack(side="left", padx=10)

        self.funds_card = Card(self)
        self.funds_card.pack(fill="x", padx=26, pady=(12, 0))
        ctk.CTkLabel(self.funds_card, text="AVAILABLE CAPITAL",
                     font=T.f(10, "bold"), text_color=T.TEXT_DIM
                     ).pack(anchor="w", padx=18, pady=(14, 2))
        self.funds_label = ctk.CTkLabel(
            self.funds_card, text="Connect to read the account balance.",
            font=T.f(16, "bold"), text_color=T.TEXT)
        self.funds_label.pack(anchor="w", padx=18, pady=(0, 16))

        later = Card(self)
        later.pack(fill="x", padx=26, pady=(12, 20))
        ctk.CTkLabel(later, text="COMING LATER", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=18,
                                                 pady=(14, 4))
        for name in ("Kotak Neo", "Flattrade"):
            ctk.CTkLabel(later, text=f"\u25aa  {name}", font=T.f(12),
                         text_color=T.TEXT_MUTED).pack(anchor="w", padx=18,
                                                       pady=2)
        ctk.CTkLabel(later, text="", font=T.f(6)).pack(pady=4)

        self._paint()

    # ------------------------------------------------------------ actions
    def _say(self, text, colour=T.TEXT_MUTED):
        self.msg.configure(text=text, text_color=colour)

    def _connect(self):
        client_id = self.fields["client_id"].get().strip()
        if not client_id:
            self._say("Client ID is required.", T.AMBER)
            return
        dhan.CLIENT.set_credentials(
            client_id,
            self.fields["pin"].get().strip(),
            self.fields["totp"].get().strip(),
            self.fields["token"].get().strip())
        self.connect_btn.configure(state="disabled", text="Connecting...")
        self._say("Working...")

        def run():
            ok = dhan.CLIENT.connect(status=lambda m: self.after(0, self._say, m))
            self.after(0, self._done, ok)

        threading.Thread(target=run, daemon=True).start()

    def _done(self, ok):
        self.connect_btn.configure(state="normal", text="Connect")
        if ok:
            STORE.bank.settings["dhan_client_id"] = dhan.CLIENT.client_id
            STORE.bank.settings["dhan_token"] = dhan.CLIENT.access_token
            STORE.save()
            self.fields["token"].delete(0, "end")
            self.fields["token"].insert(0, dhan.CLIENT.access_token)
            self._say("Connected.", T.GREEN)
            self._funds()
        else:
            self._say(dhan.CLIENT.last_error or "Could not connect.", T.RED)
        self._paint()
        self.shell.refresh_all()

    def _funds(self):
        if not dhan.CLIENT.connected:
            self.funds_label.configure(text="Not connected.")
            return

        def run():
            data = dhan.CLIENT.funds()
            self.after(0, self._show_funds, data)

        threading.Thread(target=run, daemon=True).start()

    def _show_funds(self, data):
        if not data:
            self.funds_label.configure(text="Could not read the balance.",
                                       text_color=T.AMBER)
            return
        self.funds_label.configure(
            text=f"\u20b9 {data['available']:,.2f}", text_color=T.GREEN)

    def _paint(self):
        if dhan.CLIENT.connected:
            self.dot.configure(text="\u25cf  connected", text_color=T.GREEN)
        else:
            self.dot.configure(text="\u25cf  not connected",
                               text_color=T.TEXT_DIM)

    def refresh(self):
        self._paint()
