# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Colours and fonts of the plugin's own windows.

Follows EDMC's theme (light, dark, transparent) so the route, statistics,
probe and mining windows match the main window.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Dict

# EDMC API
from config import config

from .state import cfg_str
from . import panel

_MONO_FAMILY = "Consolas" if sys.platform == "win32" else "TkFixedFont"
_MONO = (_MONO_FAMILY, 9)
_FONT_GROUP = (_MONO_FAMILY, 11, "bold")   # planetary system header
_FONT_BODY = (_MONO_FAMILY, 9)             # a planet
_FONT_MOON = (_MONO_FAMILY, 8)             # a moon, visually subordinate
_FONT_SMALL = (_MONO_FAMILY, 8)
# Markers that make the hierarchy readable at a glance
_MARK_PLANET = "\u25cf"    # filled circle - a planetary system heading
_MARK_BODY = "\u25cb"      # hollow circle - the planet itself
_MARK_MOON = "\u00b7"      # middle dot - a moon of that planet


def _theme_colours() -> Dict[str, str]:
    """
    Work out the host application's colours.

    EDMC's theme module registers widgets it created itself; a Toplevel a
    plugin opens is not part of that, and Tk gives new widgets its own
    defaults - black text on a light grey button, which is unreadable on the
    dark theme. So the colours are read live from the plugin frame, which does
    follow whatever theme is active.

    EDMC's own config is consulted first, because the frame can report an
    empty string before it has been mapped; the frame is the fallback, and a
    dark default the last resort.
    """
    bg = fg = ""

    # 1. EDMC's theme setting, if it exposes one
    try:
        idx = config.get_int("theme")
    except Exception:
        idx = None
    if idx is not None:
        try:
            bg = cfg_str("dark_background") if idx else ""
            fg = cfg_str("dark_text") if idx else ""
        except Exception:
            bg = fg = ""

    # 2. live values off the plugin frame
    if not bg and panel._frame is not None:
        bg = _frame_background()
    if not fg and panel._frame is not None:
        fg = _frame_foreground()

    # 3. a readable pair rather than Tk's defaults
    if not bg:
        bg = "#000000"
    if not fg or fg == bg:
        fg = "#ffffff" if _is_dark(bg) else "#000000"
    return {"bg": bg, "fg": fg}


def _frame_background() -> str:
    """The background of the plugin frame or its master, "" if neither says."""
    for widget in (panel._frame, getattr(panel._frame, "master", None)):
        if widget is None:
            continue
        try:
            v = str(widget.cget("background"))
        except Exception:
            continue
        if v:
            return v
    return ""


def _frame_foreground() -> str:
    """The text colour of the first child of the plugin frame that has one."""
    try:
        for child in panel._frame.winfo_children():
            try:
                v = str(child.cget("foreground"))
            except Exception:
                continue
            if v:
                return v
    except Exception:
        pass
    return ""


def _is_dark(colour: str) -> bool:
    """Rough luminance test, so a fallback foreground is at least readable."""
    try:
        c = colour.strip()
        if c.startswith("#") and len(c) == 7:
            r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
            return (0.299 * r + 0.587 * g + 0.114 * b) < 128
    except Exception:
        pass
    return True


def _dim(colour: str, factor: float = 0.45) -> str:
    """A muted version of a colour, for disabled controls and finished stops."""
    try:
        c = colour.strip()
        if c.startswith("#") and len(c) == 7:
            r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
            return "#%02x%02x%02x" % (int(r * factor), int(g * factor),
                                      int(b * factor))
    except Exception:
        pass
    return "#7a7a7a"


def _apply_theme(widget, colours: Dict[str, str], is_text: bool = False,
                 is_button: bool = False) -> None:
    """
    Paint one widget in the host application's colours.

    Buttons need more than background and foreground. Tk keeps separate
    colours for the pressed and the disabled state, and on Windows a button
    left at its defaults draws black text on whatever background it was given
    - which is exactly the unreadable combination on a dark theme. All four
    are therefore set together.
    """
    bg, fg = colours.get("bg"), colours.get("fg")
    opts = {}
    if bg:
        opts["background"] = bg
    if (is_text or is_button) and fg:
        opts["foreground"] = fg
    if is_button:
        if bg:
            opts["activebackground"] = bg
            opts["highlightbackground"] = bg
        if fg:
            opts["activeforeground"] = fg
            opts["disabledforeground"] = _dim(fg)
        opts["relief"] = tk.FLAT
        opts["borderwidth"] = 1
        opts["highlightthickness"] = 1
    if not opts:
        return
    try:
        widget.configure(**opts)
        return
    except Exception:
        pass
    # some option combinations are rejected per widget class - set them singly
    for key, value in opts.items():
        try:
            widget.configure(**{key: value})
        except Exception:
            continue


def _theme_menu(widget, colours: Dict[str, str]) -> None:
    """
    Colour the dropdown of an OptionMenu.

    The popup is a separate Tk Menu hanging off the button, not a child in the
    widget tree, so walking the children never reaches it - which is how it
    ended up black text on a black background. It has to be fetched via the
    widget's "menu" option and configured on its own.
    """
    bg, fg = colours.get("bg"), colours.get("fg")
    if not (bg and fg):
        return
    try:
        name = widget.cget("menu")
    except Exception:
        return
    if not name:
        return
    try:
        menu = widget.nametowidget(name)
    except Exception:
        return
    for opts in ({"background": bg, "foreground": fg,
                  "activebackground": fg, "activeforeground": bg,
                  "selectcolor": fg, "borderwidth": 1},
                 {"background": bg, "foreground": fg}):
        try:
            menu.configure(**opts)
            return
        except Exception:
            continue


def _theme_tree(widget, colours: Dict[str, str]) -> None:
    """Apply the colours to a widget and everything below it."""
    cls = widget.__class__.__name__
    if cls in ("OptionMenu", "Menubutton"):
        _theme_menu(widget, colours)
    _apply_theme(widget, colours,
                 is_text=cls in ("Label", "Checkbutton", "Entry"),
                 is_button=cls in ("Button", "Menubutton", "Radiobutton"))
    if cls == "Radiobutton" and colours.get("bg"):
        # tab buttons: the chosen one keeps the background (its text says
        # which one it is) - Tk would paint it white otherwise
        try:
            widget.configure(selectcolor=colours["bg"], offrelief=tk.FLAT)
        except Exception:
            pass
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for child in children:
        _theme_tree(child, colours)
