"""Colour palette, fonts and small styling helpers for the Condition Bank UI."""

APP_NAME = "Balfund Condition Bank"
APP_VERSION = "1.1.0"

# ---------- surfaces ----------
BG = "#09090B"          # window background, near black
PANEL = "#131316"       # cards and panels
PANEL_HI = "#1C1C21"    # hover / raised
PANEL_DEEP = "#0F0F12"  # inset areas
BORDER = "#26262C"      # hairline
BORDER_HI = "#3A3A44"

# ---------- text ----------
TEXT = "#FAFAFA"
TEXT_MUTED = "#A1A1AA"
TEXT_DIM = "#6B6B76"

# ---------- accent ----------
ACCENT = "#7C5CFF"      # violet
ACCENT_HI = "#9B7DFF"
ACCENT_DEEP = "#5B3FD9"

# ---------- semantic ----------
GREEN = "#3FD68C"
GREEN_DEEP = "#1F8F5B"
RED = "#FF5A5F"
RED_DEEP = "#9F2F34"
AMBER = "#FFB020"
AMBER_DEEP = "#9A6810"
CYAN = "#4ECDC4"
PURPLE = CYAN           # kept so older imports still resolve

# ---------- group colours ----------
GROUP_COLOR = {"entry": ACCENT, "exit": RED, "late": AMBER}
GROUP_LABEL = {"entry": "ENTRY", "exit": "EXIT", "late": "LATE ENTRY"}

# ---------- fonts ----------
FONT = "Segoe UI"
FONT_MONO = "Cascadia Mono"


def f(size=13, weight="normal"):
    return (FONT, size, weight)


def fm(size=12, weight="normal"):
    return (FONT_MONO, size, weight)
