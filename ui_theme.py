from __future__ import annotations

import platform
import tkinter as tk
from tkinter import ttk
from typing import Callable

FONT = "Helvetica Neue" if platform.system() == "Darwin" else "Segoe UI"

COLORS = {
    "bg": "#F5F7FA",
    "card": "#FFFFFF",
    "text": "#172033",
    "muted": "#667085",
    "line": "#E4E7EC",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_soft": "#EFF6FF",
    "success": "#067647",
    "success_soft": "#ECFDF3",
    "warning": "#B54708",
    "warning_soft": "#FFFAEB",
    "danger": "#B42318",
    "danger_soft": "#FEF3F2",
    "neutral": "#EEF2F6",
    "neutral_hover": "#E4E7EC",
}


class FlatButton(tk.Label):
    """Cross-platform flat button whose colors are not overridden by OS themes."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        text: str,
        command: Callable[[], None],
        bg: str,
        fg: str,
        hover_bg: str,
        hover_fg: str | None = None,
        font_size: int = 11,
        bold: bool = True,
        padx: int = 14,
        pady: int = 11,
        border: bool = False,
    ) -> None:
        self.command = command
        self.normal_bg = bg
        self.normal_fg = fg
        self.hover_bg = hover_bg
        self.hover_fg = hover_fg or fg
        self.enabled = True

        super().__init__(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            font=(FONT, font_size, "bold" if bold else "normal"),
            padx=padx,
            pady=pady,
            cursor="hand2",
            takefocus=1,
            bd=0,
            relief="flat",
            highlightthickness=1 if border else 0,
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["line"],
        )

        self.bind("<Button-1>", self._activate)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)

    def _activate(self, _event=None) -> str:
        if self.enabled:
            self.command()
        return "break"

    def _enter(self, _event=None) -> None:
        if self.enabled:
            self.configure(bg=self.hover_bg, fg=self.hover_fg)

    def _leave(self, _event=None) -> None:
        if self.enabled:
            self.configure(bg=self.normal_bg, fg=self.normal_fg)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self.configure(
                bg=self.normal_bg,
                fg=self.normal_fg,
                cursor="hand2",
            )
        else:
            self.configure(
                bg=COLORS["neutral"],
                fg=COLORS["muted"],
                cursor="arrow",
            )


def configure_ttk(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "Course.TEntry",
        fieldbackground=COLORS["card"],
        foreground=COLORS["text"],
        bordercolor=COLORS["line"],
        lightcolor=COLORS["line"],
        darkcolor=COLORS["line"],
        padding=(8, 8),
    )
    style.configure(
        "Course.Horizontal.TProgressbar",
        troughcolor=COLORS["neutral"],
        background=COLORS["primary"],
        borderwidth=0,
        thickness=7,
    )


def make_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    kind: str = "secondary",
    compact: bool = False,
) -> FlatButton:
    palettes = {
        # Only dark/strong backgrounds use white text.
        "primary": (COLORS["primary"], "#FFFFFF", COLORS["primary_hover"]),
        # Light backgrounds always use dark text for contrast.
        "secondary": (COLORS["card"], COLORS["text"], COLORS["neutral"]),
        "soft": (COLORS["neutral"], COLORS["text"], COLORS["neutral_hover"]),
        "danger": (COLORS["danger_soft"], COLORS["danger"], "#FEE4E2"),
    }
    bg, fg, hover_bg = palettes[kind]
    return FlatButton(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        hover_bg=hover_bg,
        font_size=9 if compact else 11,
        padx=10 if compact else 14,
        pady=7 if compact else 11,
        border=(kind == "secondary"),
    )


def make_toggle(
    parent: tk.Misc,
    *,
    enabled: bool,
    on_text: str,
    off_text: str,
    command: Callable[[], None],
) -> FlatButton:
    if enabled:
        return FlatButton(
            parent,
            text=on_text,
            command=command,
            bg=COLORS["primary"],
            fg="#FFFFFF",
            hover_bg=COLORS["primary_hover"],
            font_size=9,
            padx=13,
            pady=8,
        )

    return FlatButton(
        parent,
        text=off_text,
        command=command,
        bg=COLORS["neutral"],
        fg=COLORS["text"],
        hover_bg=COLORS["neutral_hover"],
        font_size=9,
        padx=13,
        pady=8,
    )


def make_card(parent: tk.Misc) -> tk.Frame:
    return tk.Frame(
        parent,
        bg=COLORS["card"],
        highlightbackground=COLORS["line"],
        highlightthickness=1,
        bd=0,
    )


def title_label(
    parent: tk.Misc,
    text: str,
    *,
    bg: str = COLORS["bg"],
    size: int = 24,
) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=COLORS["text"],
        font=(FONT, size, "bold"),
    )


def muted_label(
    parent: tk.Misc,
    text: str,
    *,
    bg: str = COLORS["bg"],
    size: int = 9,
    justify: str = "left",
    wraplength: int | None = None,
) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=COLORS["muted"],
        font=(FONT, size),
        justify=justify,
        wraplength=wraplength,
    )


def section_label(
    parent: tk.Misc,
    text: str,
    *,
    bg: str = COLORS["card"],
) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=COLORS["text"],
        font=(FONT, 11, "bold"),
    )
