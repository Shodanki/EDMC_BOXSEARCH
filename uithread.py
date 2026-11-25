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
import time
from typing import Any

# EDMC API
from config import config

from .state import ST, logger
from . import panel


WORKER_PREFIX = "shbox-"       # every thread of the plugin is named SHBOX-<what>


def _join_workers(timeout: float = 2.0) -> list:
    """N8: wait for the plugin's worker threads, at most ``timeout`` seconds
    in all (EDMC is closing - it must not hang). The names of those still
    running afterwards are returned; they are daemon threads and end with
    EDMC."""
    deadline = time.monotonic() + timeout
    me = threading.current_thread()
    for t in threading.enumerate():
        if t is me or not t.name.lower().startswith(WORKER_PREFIX):
            continue
        left = deadline - time.monotonic()
        if left > 0:
            t.join(left)
    return sorted(t.name for t in threading.enumerate()
                  if t is not me and t.is_alive() and t.name.lower().startswith(WORKER_PREFIX))


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
# M6 (5.1.0): the queue is bounded - while Tk is busy the same update (the
# panel refresh) is queued once, and past UI_QUEUE_MAX updates are dropped
# (logged once) instead of piling up without end
UI_QUEUE_MAX = 200
_ui_lock = threading.Lock()
_ui_pending: set = set()          # updates queued and not yet run (hashable ones)
_ui_dropped = [False]


def _enqueue(fn) -> bool:
    """Queue an update unless the same one already waits or the queue is
    full; True when queued."""
    with _ui_lock:
        try:
            hash(fn)
            key = fn
        except TypeError:
            key = None
        if key is not None and key in _ui_pending:
            return False
        if _ui_queue.qsize() >= UI_QUEUE_MAX:
            if not _ui_dropped[0]:
                logger.warning("UI queue full (%d) - updates dropped until Tk catches up", UI_QUEUE_MAX)
            _ui_dropped[0] = True
            return False
        _ui_dropped[0] = False
        if key is not None:
            _ui_pending.add(key)
        _ui_queue.put(fn)
        return True


def _done(fn) -> None:
    with _ui_lock:
        try:
            _ui_pending.discard(fn)
        except TypeError:
            pass


def _shutting_down() -> bool:
    """EDMC is closing: no more events (config.shutting_down is a property)."""
    return bool(getattr(config, "shutting_down", False))


def _ui(fn) -> None:
    """Run fn on Tk's main thread, from any thread. Before plugin_app built
    the panel an update waits in the queue (M6) - no Tk call - and runs
    when plugin_app drains it."""
    if _shutting_down():
        return
    if not panel._frame or _ui_target is None:
        _enqueue(fn)
        return
    if threading.current_thread() is threading.main_thread():
        try:
            panel._frame.after(0, fn)          # after the current handler, as before
            panel._frame.after(0, _ui_drain)   # and whatever workers left waiting
        except Exception:
            pass
        return
    if not _enqueue(fn):
        return                           # the same update already waits (or the queue is full)
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
        _done(fn)
        if _shutting_down():
            continue                     # empty the queue, draw nothing
        try:
            fn()
        except Exception:
            logger.exception("UI update failed")
