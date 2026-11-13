# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The hand-over from worker threads to Tk.

EDMC allows a sub-thread exactly one Tk call, ``event_generate()``
(PLUGINS.md, "All tkinter calls in main thread"). Workers queue their
update with ``_ui()``; the main thread runs the queue when the virtual
event arrives. Nothing is sent while EDMC shuts down. ``_run_async()``
starts the plugin's worker threads. ``tests/ui_threads.py`` checks that
no function a worker can reach touches Tk.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

# EDMC API
from config import config

from .state import ST, logger
from . import panel


def _run_async(fn, *args, label: str = "working", **kw) -> None:
    """Run fn(*args, **kw) in a daemon worker thread named SHBOX-<label>.
    The panel shows "<label> ..." meanwhile; a failure is logged, never
    raised. The worker reaches Tk only through _ui()."""
    def wrapper():
        ST.busy = True
        panel._set_status(label + " ...")
        try:
            fn(*args, **kw)
        except Exception:
            logger.exception("background task '%s' failed", label)
            panel._set_status("error - see log")
        finally:
            ST.busy = False
            _ui(panel._refresh)
    threading.Thread(target=wrapper, daemon=True, name="SHBOX-" + label).start()


# Worker threads never touch Tk themselves (EDMC PLUGINS.md, "All tkinter
# calls in main thread"): they queue the update and send one virtual event,
# the only Tk call a sub-thread may make. The main thread runs the queue.
# The event goes to EDMC's top-level window: Tk drops virtual events for a
# widget that is not mapped yet, the top level receives them even hidden.
_UI_EVENT = "<<SHBOXSEARCHUpdate>>"
_ui_queue: "queue.Queue[Any]" = queue.Queue()
_ui_target: Any = None


def _shutting_down() -> bool:
    """EDMC is closing: no more events (config.shutting_down is a property)."""
    return bool(getattr(config, "shutting_down", False))


def _ui(fn) -> None:
    """Run fn on Tk's main thread, from any thread."""
    if not panel._frame or _ui_target is None or _shutting_down():
        return
    if threading.current_thread() is threading.main_thread():
        try:
            panel._frame.after(0, fn)          # after the current handler, as before
            panel._frame.after(0, _ui_drain)   # and whatever workers left waiting
        except Exception:
            pass
        return
    _ui_queue.put(fn)
    try:
        _ui_target.event_generate(_UI_EVENT, when="tail")
    except Exception:
        pass                             # window gone - nothing left to update


def _ui_drain(_event: Any = None) -> None:
    """Main thread: run every queued UI update."""
    while True:
        try:
            fn = _ui_queue.get_nowait()
        except queue.Empty:
            return
        if _shutting_down():
            continue                     # empty the queue, draw nothing
        try:
            fn()
        except Exception:
            logger.exception("UI update failed")
