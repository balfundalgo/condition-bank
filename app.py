"""
Balfund Condition Bank -- entry point.

Run:      python app.py
Build:    python bundler.py     (or push to GitHub, Actions builds the EXE)

Password protection and the licensing layer are switched off for now and
will be added once the software is finished.
"""

import os
import sys
import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import theme as T          # noqa: E402
from core import charges as CH       # noqa: E402
from core.positions import BOOK      # noqa: E402
from core.store import STORE, LOG_DIR  # noqa: E402
from ui.shell import Shell           # noqa: E402


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    STORE.load()
    BOOK.set_rates(CH.ChargeRates.from_dict(
        STORE.bank.settings.get("charges")))
    Shell().mainloop()


if __name__ == "__main__":
    main()
