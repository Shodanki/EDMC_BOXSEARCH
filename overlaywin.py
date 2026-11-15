# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
D3 (4.12): the cockpit overlay in a window of the plugin's own - an option
beside EDMCModernOverlay, no extra package (tkinter and ctypes only).

``WindowClient`` speaks the one call CockpitOverlay uses,
``send_message(id, text, colour, x, y, ttl, size)`` on a 1280 x 960
virtual canvas, so briefing, targets, compass, bio and mining blocks look as
they do through ModernOverlay. The window:

* has no frame, stays on top, is transparent but for the text, and lets
  every mouse click through to the game; it never takes the focus;
* shows only while the game is the window in front (Alt+Tab hides it);
* needs the game in a borderless window - an exclusive full screen covers
  every other window (ModernOverlay's too).

It only DISPLAYS; nothing is sent to the game. Worker threads only store
the text: drawing runs on Tk's main thread, through the hand-over the
plugin gives it (uithread._ui).
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

CANVAS_W, CANVAS_H = 1280, 960        # ModernOverlay's virtual canvas
KEY = "#010203"                       # the transparent colour (no text uses it)
FONT_PT = {"small": 10, "normal": 12}
TICK_MS = 1000                        # expiry and "is the game in front?"
GAME_TITLE = "Elite - Dangerous (CLIENT)"

# Windows extended window styles for a click-through, never-focused overlay
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000

Message = Tuple[str, str, int, int, str, float]   # text, colour, x, y, size, until


def supported() -> bool:
    """Click-through needs the Windows API; elsewhere the window would block
    the game's mouse, so the option is not offered."""
    return sys.platform == "win32"


def game_in_front() -> bool:
    """True when the game window has the focus (Windows), else True."""
    if not supported():
        return True
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value == GAME_TITLE
    except Exception:
        return True


class WindowClient:
    """The edmcoverlay call, drawn into a window of our own."""

    def __init__(self, schedule: Callable[[Callable[[], None]], None],
                 root: Callable[[], Any], in_front: Callable[[], bool] = game_in_front,
                 window_factory: Optional[Callable[[Any], Any]] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._schedule = schedule            # runs a function on Tk's main thread
        self._root = root                    # EDMC's top-level window (main thread)
        self._in_front = in_front
        self._factory = window_factory or _make_window
        self._clock = clock
        self._lock = threading.Lock()
        self._msgs: Dict[str, Message] = {}
        self._pending = False                # a redraw is queued already
        self._win: Any = None                # (toplevel, canvas, width, height)
        self._ticking = False

    # -- any thread -----------------------------------------------------------
    def send_message(self, mid: str, text: str, colour: str, x: int, y: int,
                     ttl: int = 4, size: str = "normal") -> None:
        """Store one line (an empty text removes it) and ask for a redraw."""
        with self._lock:
            if text:
                self._msgs[mid] = (text, colour, int(x), int(y), size, self._clock() + max(1, int(ttl)))
            else:
                self._msgs.pop(mid, None)
            if self._pending:
                return
            self._pending = True
        self._schedule(self.redraw)

    def lines(self) -> Dict[str, Message]:
        """The lines on screen now (for the tests)."""
        with self._lock:
            return dict(self._msgs)

    # -- main thread ------------------------------------------------------------
    def redraw(self) -> None:
        """Draw what is not expired; hide while the game is not in front."""
        with self._lock:
            self._pending = False
            now = self._clock()
            self._msgs = {k: m for k, m in self._msgs.items() if m[5] > now}
            msgs = list(self._msgs.values())
        if self._win is None:
            if not msgs:
                return
            self._win = self._factory(self._root())
        top, canvas, w, h = self._win
        canvas.delete("all")
        show = bool(msgs) and self._in_front()
        for text, colour, x, y, size, _until in msgs:
            pt = max(8, round(FONT_PT.get(size, 10) * h / CANVAS_H))
            canvas.create_text(x * w / CANVAS_W, y * h / CANVAS_H, anchor="nw", text=text,
                               fill=colour, font=("Consolas", pt))
        if show:
            top.deiconify()
        else:
            top.withdraw()
        if msgs and not self._ticking:
            self._ticking = True
            top.after(TICK_MS, self._tick)

    def _tick(self) -> None:
        self._ticking = False
        self.redraw()

    def close(self) -> None:
        """Remove the window (EDMC closing, or the other overlay chosen)."""
        with self._lock:
            self._msgs.clear()
        if self._win is not None:
            try:
                self._win[0].destroy()
            except Exception:
                pass
            self._win = None


def _make_window(root: Any) -> Tuple[Any, Any, int, int]:
    """The overlay window over the whole primary screen (main thread)."""
    import tkinter as tk
    top = tk.Toplevel(root)
    top.withdraw()
    top.overrideredirect(True)
    w, h = top.winfo_screenwidth(), top.winfo_screenheight()
    top.geometry("%dx%d+0+0" % (w, h))
    top.configure(bg=KEY)
    top.attributes("-topmost", True)
    try:
        top.attributes("-transparentcolor", KEY)
    except Exception:
        pass
    canvas = tk.Canvas(top, width=w, height=h, bg=KEY, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    top.update_idletasks()
    _click_through(top)
    return top, canvas, w, h


def _click_through(top: Any) -> None:
    """Windows: mouse clicks go to the window below, the focus never comes here."""
    if not supported():
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(top.winfo_id()) or top.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception:
        pass
