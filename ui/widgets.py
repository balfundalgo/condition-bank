"""Small reusable pieces used across the pages."""

import customtkinter as ctk
from core import theme as T


class Card(ctk.CTkFrame):
    """A panel with an optional coloured stripe down the left edge."""

    def __init__(self, master, stripe=None, **kw):
        kw.setdefault("fg_color", T.PANEL)
        kw.setdefault("corner_radius", 10)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.BORDER)
        super().__init__(master, **kw)
        self.body = self
        if stripe:
            self.grid_columnconfigure(1, weight=1)
            bar = ctk.CTkFrame(self, width=4, fg_color=stripe, corner_radius=6)
            bar.grid(row=0, column=0, sticky="ns", padx=(6, 0), pady=8)
            self.body = ctk.CTkFrame(self, fg_color="transparent")
            self.body.grid(row=0, column=1, sticky="nsew", padx=(10, 12), pady=10)
            self.body.grid_columnconfigure(0, weight=1)


class Pill(ctk.CTkLabel):
    def __init__(self, master, text, color=T.ACCENT, **kw):
        super().__init__(master, text=f"  {text}  ", font=T.f(10, "bold"),
                         text_color=color, fg_color=T.PANEL_DEEP,
                         corner_radius=8, **kw)


def heading(master, text, sub=None):
    box = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(box, text=text, font=T.f(22, "bold"),
                 text_color=T.TEXT).pack(anchor="w")
    if sub:
        ctk.CTkLabel(box, text=sub, font=T.f(12), text_color=T.TEXT_MUTED,
                     justify="left", wraplength=900).pack(anchor="w", pady=(2, 0))
    return box


def mono_box(master, text, height=None, color=T.ACCENT_HI):
    tb = ctk.CTkTextbox(master, font=T.fm(11), fg_color=T.PANEL_DEEP,
                        text_color=color, border_width=0, corner_radius=6,
                        wrap="word", activate_scrollbars=False)
    if height:
        tb.configure(height=height)
    tb.insert("1.0", text)
    tb.configure(state="disabled")
    return tb


class FlowFrame(ctk.CTkFrame):
    """Lays child chips out left to right and wraps to the next line."""

    def __init__(self, master, pad=5, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self._pad = pad
        self._items = []
        self.bind("<Configure>", lambda e: self._relayout())

    def add(self, widget):
        self._items.append(widget)
        self._relayout()

    def clear(self):
        for w in self._items:
            w.destroy()
        self._items = []

    def _relayout(self):
        width = max(self.winfo_width(), 200)
        x = y = 0
        row_h = 0
        for w in self._items:
            w.update_idletasks()
            ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            if x + ww > width and x > 0:
                x = 0
                y += row_h + self._pad
                row_h = 0
            w.place(x=x, y=y)
            x += ww + self._pad
            row_h = max(row_h, wh)
        self.configure(height=max(y + row_h, 34))
