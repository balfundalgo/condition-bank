"""
Strategy Builder page.

Everything is edited on a draft copy.  Nothing reaches the store, the
dashboard or the condition usage counts until Save is pressed.  Save also
takes the user straight to the Dashboard.
"""

import copy
import customtkinter as ctk
from core import theme as T, conditions as C, expression as E
from core.store import STORE, Strategy
from ui.widgets import Card, heading, FlowFrame

OPS = [("AND", T.ACCENT), ("OR", T.CYAN), ("(", T.TEXT_MUTED),
       (")", T.TEXT_MUTED)]


# --------------------------------------------------------------- dialogs
class ParamDialog(ctk.CTkToplevel):
    def __init__(self, master, strategy, cid, on_save):
        super().__init__(master)
        cond = C.get(cid)
        self.title(f"{cid} settings")
        self.configure(fg_color=T.BG)
        self.geometry("420x%d" % (190 + 62 * len(cond.params)))
        self.resizable(False, False)
        self.strategy, self.cid, self.on_save = strategy, cid, on_save
        self.vars = {}

        colour = T.GROUP_COLOR[cond.group]
        ctk.CTkLabel(self, text=cid, font=T.fm(18, "bold"),
                     text_color=colour).pack(anchor="w", padx=24, pady=(20, 0))
        ctk.CTkLabel(self, text=cond.name, font=T.f(14, "bold"),
                     text_color=T.TEXT, wraplength=360, justify="left"
                     ).pack(anchor="w", padx=24)
        ctk.CTkLabel(self, text=cond.plain, font=T.f(11),
                     text_color=T.TEXT_MUTED, wraplength=360, justify="left"
                     ).pack(anchor="w", padx=24, pady=(4, 14))

        current = strategy.params.setdefault(cid, C.default_params(cid))
        for p in cond.params:
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", padx=24, pady=5)
            ctk.CTkLabel(row, text=p.label, font=T.f(12),
                         text_color=T.TEXT_MUTED, width=170, anchor="w"
                         ).pack(side="left")
            var = ctk.StringVar(value=str(current.get(p.key, p.default)))
            if p.kind == "choice":
                ctk.CTkOptionMenu(row, values=[str(c) for c in p.choices],
                                  variable=var, width=150, height=32,
                                  font=T.f(12), fg_color=T.PANEL,
                                  button_color=T.PANEL_HI,
                                  dropdown_fg_color=T.PANEL).pack(side="right")
            else:
                ctk.CTkEntry(row, textvariable=var, width=150, height=32,
                             font=T.f(12), fg_color=T.PANEL,
                             border_color=T.BORDER).pack(side="right")
            self.vars[p.key] = (var, p)

        ctk.CTkButton(self, text="Apply", height=38, font=T.f(13, "bold"),
                      fg_color=T.ACCENT, hover_color=T.ACCENT_DEEP,
                      command=self._save).pack(fill="x", padx=24, pady=(16, 8))
        self.err = ctk.CTkLabel(self, text="", font=T.f(11), text_color=T.RED)
        self.err.pack()
        self.after(120, self.lift)
        self.grab_set()

    def _save(self):
        out = {}
        for key, (var, p) in self.vars.items():
            raw = var.get().strip()
            if p.kind == "choice":
                out[key] = raw
                continue
            try:
                val = float(raw) if p.kind == "float" else int(float(raw))
            except ValueError:
                self.err.configure(text=f"{p.label} must be a number.")
                return
            if not (p.lo <= val <= p.hi):
                self.err.configure(
                    text=f"{p.label} must be between {p.lo} and {p.hi}.")
                return
            out[key] = val
        self.strategy.params[self.cid] = out
        self.on_save()
        self.destroy()


class ConfirmDialog(ctk.CTkToplevel):
    """Save / Discard / Cancel when leaving a strategy with unsaved edits."""

    def __init__(self, master, name):
        super().__init__(master)
        self.title("Unsaved changes")
        self.configure(fg_color=T.BG)
        self.geometry("420x190")
        self.resizable(False, False)
        self.choice = "cancel"

        ctk.CTkLabel(self, text="Unsaved changes", font=T.f(17, "bold"),
                     text_color=T.TEXT).pack(anchor="w", padx=24, pady=(22, 4))
        ctk.CTkLabel(self, text=f"\"{name}\" has changes that are not saved.",
                     font=T.f(12), text_color=T.TEXT_MUTED, wraplength=360,
                     justify="left").pack(anchor="w", padx=24)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(26, 0))
        ctk.CTkButton(row, text="Save", height=38, font=T.f(13, "bold"),
                      fg_color=T.ACCENT, hover_color=T.ACCENT_DEEP,
                      command=lambda: self._pick("save")
                      ).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(row, text="Discard", height=38, font=T.f(13),
                      fg_color=T.PANEL, hover_color=T.RED_DEEP,
                      text_color=T.RED, command=lambda: self._pick("discard")
                      ).pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkButton(row, text="Cancel", height=38, font=T.f(13),
                      fg_color=T.PANEL, hover_color=T.PANEL_HI,
                      text_color=T.TEXT_MUTED,
                      command=lambda: self._pick("cancel")
                      ).pack(side="left", expand=True, fill="x", padx=(5, 0))
        self.after(120, self.lift)
        self.grab_set()

    def _pick(self, value):
        self.choice = value
        self.destroy()

    def ask(self):
        self.master.wait_window(self)
        return self.choice


# ----------------------------------------------------------- expression box
class ExpressionBox(ctk.CTkFrame):
    def __init__(self, master, page, title, field, group, hint):
        super().__init__(master, fg_color=T.PANEL, corner_radius=10,
                         border_width=2, border_color=T.BORDER)
        self.page, self.field, self.group = page, field, group
        self.colour = T.GROUP_COLOR[group]

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(13, 0))
        ctk.CTkLabel(head, text=title, font=T.f(14, "bold"),
                     text_color=self.colour).pack(side="left")
        self.status = ctk.CTkLabel(head, text="", font=T.f(11),
                                   text_color=T.TEXT_MUTED)
        self.status.pack(side="right")
        ctk.CTkLabel(self, text=hint, font=T.f(10), text_color=T.TEXT_DIM,
                     anchor="w", justify="left").pack(fill="x", padx=16)

        self.flow_holder = ctk.CTkFrame(self, fg_color=T.PANEL_DEEP,
                                        corner_radius=8)
        self.flow_holder.pack(fill="x", padx=16, pady=(9, 0))
        self.flow = FlowFrame(self.flow_holder)
        self.flow.pack(fill="x", padx=10, pady=10)

        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.pack(fill="x", padx=16, pady=(9, 0))
        for text, colour in OPS:
            ctk.CTkButton(ops, text=text, width=54, height=28,
                          font=T.fm(12, "bold"), fg_color=T.PANEL_DEEP,
                          hover_color=T.PANEL_HI, text_color=colour,
                          command=lambda t=text: self.append(t)
                          ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(ops, text="Undo", width=58, height=28, font=T.f(11),
                      fg_color=T.PANEL_DEEP, hover_color=T.PANEL_HI,
                      text_color=T.TEXT_MUTED, command=self.undo
                      ).pack(side="right")
        ctk.CTkButton(ops, text="Clear", width=58, height=28, font=T.f(11),
                      fg_color=T.PANEL_DEEP, hover_color=T.PANEL_HI,
                      text_color=T.RED, command=self.clear
                      ).pack(side="right", padx=(0, 6))

        self.expr = ctk.CTkLabel(self, text="", font=T.fm(12, "bold"),
                                 text_color=T.TEXT, anchor="w", justify="left",
                                 wraplength=760)
        self.expr.pack(fill="x", padx=16, pady=(11, 0))
        self.english = ctk.CTkLabel(self, text="", font=T.f(12),
                                    text_color=T.TEXT_MUTED, anchor="w",
                                    justify="left", wraplength=760)
        self.english.pack(fill="x", padx=16, pady=(4, 14))

        for w in (self, head, self.flow_holder, self.flow):
            w.bind("<Button-1>", lambda e: self.page.set_active(self))

    # -- token operations ------------------------------------------------
    @property
    def tokens(self):
        return getattr(self.page.draft, self.field)

    def append(self, token):
        self.page.set_active(self)
        self.tokens.append(token)
        self.page.touch()
        self.render()

    def undo(self):
        if self.tokens:
            self.tokens.pop()
            self.page.touch()
            self.render()

    def clear(self):
        if self.tokens:
            self.tokens.clear()
            self.page.touch()
            self.render()

    def remove_at(self, index):
        if 0 <= index < len(self.tokens):
            self.tokens.pop(index)
            self.page.touch()
            self.render()

    # -- drawing ---------------------------------------------------------
    def render(self):
        self.flow.clear()
        if not self.tokens:
            self.flow.add(ctk.CTkLabel(
                self.flow, text="click a condition on the left",
                font=T.f(11), text_color=T.TEXT_DIM))
        for i, tok in enumerate(self.tokens):
            self.flow.add(self._chip(tok, i))

        ok, msg = E.validate(self.tokens, self.group)
        self.status.configure(text=msg,
                              text_color=T.GREEN if ok else T.AMBER)
        self.expr.configure(text=E.to_text(self.tokens) or "-")
        lead = {"entry": "Enter when", "exit": "Exit when",
                "late": "Confirm when"}[self.group]
        self.english.configure(text=E.to_english(self.tokens, lead))

    def _chip(self, token, index):
        if token in C.BY_ID:
            cond = C.get(token)
            colour = T.GROUP_COLOR[cond.group]
            chip = ctk.CTkFrame(self.flow, fg_color=T.PANEL_HI,
                                corner_radius=8, border_width=1,
                                border_color=colour)
            lbl = ctk.CTkLabel(chip, text=token, font=T.fm(12, "bold"),
                               text_color=colour, cursor="hand2")
            lbl.pack(side="left", padx=(9, 4), pady=4)
            lbl.bind("<Button-1>", lambda e, t=token: self._edit(t))
            x = ctk.CTkLabel(chip, text="\u2715", font=T.f(10),
                             text_color=T.TEXT_DIM, cursor="hand2")
            x.pack(side="left", padx=(0, 8))
            x.bind("<Button-1>", lambda e, i=index: self.remove_at(i))
            return chip

        colour = {"AND": T.ACCENT, "OR": T.CYAN}.get(token, T.TEXT_MUTED)
        chip = ctk.CTkLabel(self.flow, text=f" {token} ", font=T.fm(12, "bold"),
                            text_color=colour, fg_color=T.PANEL_DEEP,
                            corner_radius=6, cursor="hand2")
        chip.bind("<Button-1>", lambda e, i=index: self.remove_at(i))
        return chip

    def _edit(self, cid):
        ParamDialog(self, self.page.draft, cid, self.page.on_params_changed)

    def set_active(self, active: bool):
        self.configure(border_color=self.colour if active else T.BORDER)


# ------------------------------------------------------------------- page
class StrategyBuilderPage(ctk.CTkFrame):
    def __init__(self, master, shell):
        super().__init__(master, fg_color="transparent")
        self.shell = shell
        self.draft = None        # the copy being edited
        self.origin = None       # the stored strategy, or None if brand new
        self.dirty = False
        self.active = None

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(22, 0))
        heading(head, "Strategy Builder",
                "Pick a box, then click conditions on the left to add them. "
                "Nothing goes live until you press Save."
                ).pack(anchor="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=26, pady=(14, 8))
        self.picker = ctk.CTkOptionMenu(bar, values=["-"], width=230, height=36,
                                        font=T.f(12), fg_color=T.PANEL,
                                        button_color=T.PANEL_HI,
                                        dropdown_fg_color=T.PANEL,
                                        command=self._pick)
        self.picker.pack(side="left")
        self.name = ctk.CTkEntry(bar, width=210, height=36, font=T.f(12),
                                 placeholder_text="Strategy name",
                                 fg_color=T.PANEL, border_color=T.BORDER)
        self.name.pack(side="left", padx=10)
        self.name.bind("<KeyRelease>", self._rename)

        self.template = ctk.CTkOptionMenu(
            bar, values=list(E.TEMPLATES.keys()), width=200, height=36,
            font=T.f(12), fg_color=T.PANEL, button_color=T.PANEL_HI,
            dropdown_fg_color=T.PANEL)
        self.template.set("Blank")
        self.template.pack(side="left")
        ctk.CTkButton(bar, text="+ New", width=76, height=36,
                      font=T.f(12, "bold"), fg_color=T.PANEL,
                      hover_color=T.PANEL_HI, text_color=T.ACCENT_HI,
                      command=self._new).pack(side="left", padx=8)
        ctk.CTkButton(bar, text="Delete", width=74, height=36, font=T.f(12),
                      fg_color=T.PANEL, hover_color=T.RED_DEEP,
                      text_color=T.RED, command=self._delete).pack(side="left")

        # ---- save strip
        self.savebar = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=10,
                                    border_width=1, border_color=T.BORDER)
        self.savebar.pack(fill="x", padx=26, pady=(0, 8))
        self.state = ctk.CTkLabel(self.savebar, text="", font=T.f(12),
                                  text_color=T.TEXT_MUTED, anchor="w")
        self.state.pack(side="left", padx=16, pady=10)
        self.save_btn = ctk.CTkButton(self.savebar, text="Save strategy",
                                      width=150, height=34,
                                      font=T.f(13, "bold"), fg_color=T.ACCENT,
                                      hover_color=T.ACCENT_DEEP,
                                      command=self.save)
        self.save_btn.pack(side="right", padx=(6, 14), pady=8)
        self.revert_btn = ctk.CTkButton(self.savebar, text="Discard changes",
                                        width=130, height=34, font=T.f(12),
                                        fg_color=T.PANEL_DEEP,
                                        hover_color=T.PANEL_HI,
                                        text_color=T.TEXT_MUTED,
                                        command=self.discard)
        self.revert_btn.pack(side="right", pady=8)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        body.grid_columnconfigure(0, minsize=270)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        pal = ctk.CTkFrame(body, fg_color=T.PANEL, corner_radius=10,
                           border_width=1, border_color=T.BORDER)
        pal.grid(row=0, column=0, sticky="nsew", padx=(6, 10))
        ctk.CTkLabel(pal, text="CONDITION PALETTE", font=T.f(10, "bold"),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=14,
                                                 pady=(13, 2))
        ctk.CTkLabel(pal, text="Click to add to the active box", font=T.f(10),
                     text_color=T.TEXT_DIM).pack(anchor="w", padx=14)
        self.palette = ctk.CTkScrollableFrame(pal, fg_color="transparent")
        self.palette.pack(fill="both", expand=True, padx=8, pady=10)

        right = ctk.CTkScrollableFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        self.entry_box = ExpressionBox(
            right, self, "ENTRY CONDITION", "entry", "entry",
            "When all of this is true on a strike, a buy signal is raised.")
        self.entry_box.pack(fill="x", pady=(2, 10))
        self.exit_box = ExpressionBox(
            right, self, "EXIT CONDITION", "exit", "exit",
            "Closes the position. Targets, stops and day limits can still "
            "act first -- see the specification.")
        self.exit_box.pack(fill="x", pady=(0, 10))

        self.late_card = Card(right)
        self.late_card.pack(fill="x", pady=(0, 10))
        lh = ctk.CTkFrame(self.late_card, fg_color="transparent")
        lh.pack(fill="x", padx=16, pady=(12, 0))
        self.late_switch = ctk.CTkSwitch(
            lh, text="Late entry", font=T.f(14, "bold"), text_color=T.AMBER,
            progress_color=T.AMBER, command=self._toggle_late)
        self.late_switch.pack(side="left")
        win = ctk.CTkFrame(lh, fg_color="transparent")
        win.pack(side="right")
        ctk.CTkLabel(win, text="check from bar", font=T.f(11),
                     text_color=T.TEXT_MUTED).pack(side="left", padx=(0, 6))
        self.lx = ctk.CTkEntry(win, width=48, height=28, font=T.f(11),
                               fg_color=T.PANEL_DEEP, border_color=T.BORDER)
        self.lx.pack(side="left")
        ctk.CTkLabel(win, text="to", font=T.f(11),
                     text_color=T.TEXT_MUTED).pack(side="left", padx=6)
        self.ly = ctk.CTkEntry(win, width=48, height=28, font=T.f(11),
                               fg_color=T.PANEL_DEEP, border_color=T.BORDER)
        self.ly.pack(side="left")
        for e in (self.lx, self.ly):
            e.bind("<KeyRelease>", self._window_changed)

        self.late_box = ExpressionBox(
            self.late_card, self, "LATE ENTRY CONFIRMATION", "late", "late",
            "Signal is held. The order is placed only if this turns true "
            "inside the bar window, at the price at that moment.")
        self.late_box.pack(fill="x", padx=10, pady=(8, 12))

        self.boxes = [self.entry_box, self.exit_box, self.late_box]
        self.reload()

    # ------------------------------------------------------ draft handling
    def touch(self):
        self.dirty = True
        self._update_savebar()

    def on_params_changed(self):
        self.touch()
        self.refresh_palette()

    def _update_savebar(self):
        if not self.draft:
            self.state.configure(text="No strategy open.", text_color=T.TEXT_DIM)
            self.save_btn.configure(state="disabled")
            self.revert_btn.configure(state="disabled")
            return
        ok_e, msg_e = E.validate(self.draft.entry, "entry")
        ok_x, msg_x = E.validate(self.draft.exit, "exit")
        ready = ok_e and ok_x
        if self.draft.late_enabled:
            ok_l, _ = E.validate(self.draft.late, "late")
            ready = ready and ok_l

        if not ready:
            problem = msg_e if not ok_e else msg_x
            self.state.configure(text=f"Cannot save yet  \u00b7  {problem}",
                                 text_color=T.AMBER)
        elif self.dirty:
            self.state.configure(
                text="Unsaved changes  \u00b7  press Save to send this "
                     "strategy to the dashboard", text_color=T.ACCENT_HI)
        else:
            self.state.configure(text="Saved. Nothing pending.",
                                 text_color=T.GREEN)
        self.save_btn.configure(state="normal" if (ready and self.dirty)
                                else "disabled")
        self.revert_btn.configure(state="normal" if self.dirty else "disabled")

    def save(self):
        if not self.draft:
            return False
        if self.origin is None:
            self.draft.number = STORE.next_number()
            STORE.bank.strategies.append(self.draft)
            self.origin = self.draft
        else:
            index = STORE.bank.strategies.index(self.origin)
            STORE.bank.strategies[index] = self.draft
            self.origin = self.draft
        STORE.save()
        self.dirty = False
        self.draft = copy.deepcopy(self.origin)
        self.shell.mark_data_changed()
        self.reload(keep=True)
        self.shell.show("Dashboard")
        return True

    def discard(self):
        if self.origin is None:
            self.draft = None
            self.origin = None
        else:
            self.draft = copy.deepcopy(self.origin)
        self.dirty = False
        self.reload(keep=True)

    def has_unsaved(self) -> bool:
        return bool(self.draft and self.dirty)

    def confirm_leave(self) -> bool:
        """True if it is safe to move away."""
        if not self.has_unsaved():
            return True
        choice = ConfirmDialog(self, self.draft.name).ask()
        if choice == "save":
            ok_e, _ = E.validate(self.draft.entry, "entry")
            ok_x, _ = E.validate(self.draft.exit, "exit")
            if not (ok_e and ok_x):
                return False
            if self.origin is None:
                self.draft.number = STORE.next_number()
                STORE.bank.strategies.append(self.draft)
                self.origin = self.draft
            else:
                index = STORE.bank.strategies.index(self.origin)
                STORE.bank.strategies[index] = self.draft
                self.origin = self.draft
            STORE.save()
            self.dirty = False
            self.shell.mark_data_changed()
            return True
        if choice == "discard":
            self.discard()
            return True
        return False

    # ---------------------------------------------------------- strategies
    def reload(self, keep=False):
        stored = STORE.bank.strategies
        labels = [f"{s.number}. {s.name}" for s in stored]
        if self.draft and self.origin is None:
            labels = labels + [f"\u2022 {self.draft.name} (new)"]
        self.picker.configure(values=labels or ["-"])

        if not keep and self.draft is None and stored:
            self.origin = stored[0]
            self.draft = copy.deepcopy(self.origin)
            self.dirty = False

        if not self.draft:
            self.picker.set("-")
            self.name.delete(0, "end")
            self._update_savebar()
            self.refresh_palette()
            return

        if self.origin is None:
            self.picker.set(f"\u2022 {self.draft.name} (new)")
        else:
            self.picker.set(f"{self.origin.number}. {self.origin.name}")

        if self.name.get() != self.draft.name:
            self.name.delete(0, "end")
            self.name.insert(0, self.draft.name)
        (self.late_switch.select() if self.draft.late_enabled
         else self.late_switch.deselect())
        for entry, value in ((self.lx, self.draft.late_x),
                             (self.ly, self.draft.late_y)):
            if entry.get() != str(value):
                entry.delete(0, "end")
                entry.insert(0, str(value))
        self.set_active(self.active or self.entry_box)
        for b in self.boxes:
            b.render()
        self.refresh_palette()
        self._update_savebar()

    def _pick(self, label):
        if not self.confirm_leave():
            self.reload(keep=True)
            return
        if label.startswith("\u2022"):
            return
        for s in STORE.bank.strategies:
            if f"{s.number}. {s.name}" == label:
                self.origin = s
                self.draft = copy.deepcopy(s)
                self.dirty = False
                break
        self.name.delete(0, "end")
        self.reload(keep=True)

    def _new(self):
        if not self.confirm_leave():
            return
        tpl = E.TEMPLATES.get(self.template.get(), E.TEMPLATES["Blank"])
        base = self.template.get().replace(" (from the spec)", "")
        self.origin = None
        self.draft = Strategy(
            number=STORE.next_number(),
            name=base if base != "Blank" else f"Strategy {STORE.next_number()}",
            entry=list(tpl["entry"]), exit=list(tpl["exit"]))
        self.dirty = True
        self.name.delete(0, "end")
        self.reload(keep=True)

    def _delete(self):
        if self.origin is not None:
            STORE.delete_strategy(self.origin)
            self.shell.mark_data_changed()
        self.origin, self.draft, self.dirty = None, None, False
        self.name.delete(0, "end")
        self.reload()

    def _rename(self, _=None):
        if self.draft:
            self.draft.name = self.name.get() or "Untitled"
            self.touch()

    def _toggle_late(self):
        if self.draft:
            self.draft.late_enabled = bool(self.late_switch.get())
            self.touch()

    def _window_changed(self, _=None):
        if not self.draft:
            return
        for entry, attr in ((self.lx, "late_x"), (self.ly, "late_y")):
            try:
                setattr(self.draft, attr, max(0, int(entry.get())))
            except ValueError:
                pass
        self.touch()

    # ------------------------------------------------------------- palette
    def set_active(self, box):
        self.active = box
        for b in self.boxes:
            b.set_active(b is box)
        self.refresh_palette()

    def refresh_palette(self):
        for w in self.palette.winfo_children():
            w.destroy()
        if not self.draft:
            ctk.CTkLabel(self.palette,
                         text="Press + New to start a strategy.",
                         font=T.f(12), text_color=T.TEXT_MUTED).pack(pady=20)
            return
        group = self.active.group if self.active else "entry"
        for cond in C.by_group(group):
            self._palette_row(cond).pack(fill="x", pady=3, padx=4)

    def _palette_row(self, cond):
        colour = T.GROUP_COLOR[cond.group]
        row = ctk.CTkFrame(self.palette, fg_color=T.PANEL_DEEP,
                           corner_radius=8, cursor="hand2")
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(7, 0))
        ctk.CTkLabel(top, text=cond.cid, font=T.fm(12, "bold"),
                     text_color=colour).pack(side="left")
        if cond.cid in (self.active.tokens if self.active else []):
            ctk.CTkLabel(top, text="in use", font=T.f(9, "bold"),
                         text_color=T.GREEN).pack(side="right")
        body = ctk.CTkLabel(row, text=cond.name, font=T.f(11),
                            text_color=T.TEXT, anchor="w", justify="left",
                            wraplength=186)
        body.pack(fill="x", padx=10, pady=(1, 8))
        for w in (row, top, body):
            w.bind("<Button-1>",
                   lambda e, c=cond.cid: self.active and self.active.append(c))
        return row

    def refresh(self):
        self._update_savebar()
