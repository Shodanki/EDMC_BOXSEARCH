# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
4.12.1: when EDMC stops passing on journal events.

After a lost connection to the server the game can write its journal anew
under the same file name (seen 06.11. and 16.11.2026). EDMC's journal
monitor then reads on at its old place in the file and passes on nothing,
for many minutes or until it is restarted, while Status.json still
arrives. The plugin stored no landings, samples or finds meanwhile, and
the FIS's PLANET showed only the track.

Watch notes every event EDMC passes on. When Status.json keeps coming but
EDMC has been quiet for QUIET_S, a worker looks at the newest journal
file. If it holds events EDMC never passed on (older than LAG_S), the
plugin

  * warns - one line in EDMC's window and on the overlay: restart EDMC;
  * stores the missed events itself, in their order, in the database
    (sysdb.ingest_journal_event; positions come from the stored track).
    The live displays pick up again when EDMC passes events on again;
  * leaves those events out should EDMC pass them on later after all.

The warning goes when EDMC passes on a new event again. Only the journal
folder is read, only the newest file, and only while EDMC is quiet and
the file has changed since the last look.

Watch is plain Python (tests/journal_gap.py); the hooks below it run in
EDMC: journal_event() and status_tick() on the main thread, the look at
the file in a worker thread that reaches Tk only through uithread._ui().
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple

from . import cockpitinfo
from . import journalscan
from . import maintenance
from . import panel
from . import situation
from . import uithread
from .state import ST, logger

QUIET_S = 60.0       # s without an event from EDMC before the journal is looked at
CHECK_S = 30.0       # s between two looks
LAG_S = 10.0         # an event this old that EDMC has not passed on is missed
MIN_MISSED = 3       # fewer missed events (main menu, the game closing) are no gap
KEEP_KEYS = 20000    # events stored by the plugin, remembered to leave them out later
CHUNK = 50           # events stored per database lock

Pair = Tuple[Dict[str, Any], str]


def base_key(e: Dict[str, Any]) -> str:
    """What tells two events apart (the n-th one of the same second gets #n)."""
    what = e.get("ScanType") or ""
    name = e.get("Name") or e.get("Species") or e.get("BodyName") or e.get("Type") or ""
    return "%s|%s|%s|%s|%s" % (e.get("timestamp"), e.get("event"),
                               e.get("BodyID", e.get("Body", "")), what, name)


def keys_of(events: Iterable[Dict[str, Any]]) -> List[str]:
    """The key of every event, in order: base_key plus how often the same
    base key came before it."""
    seen: Dict[str, int] = {}
    out = []
    for e in events:
        b = base_key(e)
        n = seen.get(b, 0)
        seen[b] = n + 1
        out.append("%s#%d" % (b, n))
    return out


class Watch:
    """What EDMC passed on, and what the plugin stored itself."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_ts: Optional[float] = None    # game time of the newest event EDMC passed on
        self.last_wall = 0.0                    # wall time EDMC passed on its last event
        self.high: Optional[float] = None       # newest event the plugin stored itself
        self.checked = 0.0
        self.busy = False
        self.gap_since: Optional[float] = None  # game time of EDMC's last event before the gap
        self.added = 0                          # events stored by the plugin in this gap
        self.sig: Optional[Tuple[str, int, int]] = None   # the file as it was at the last look
        self._sec: Optional[str] = None         # the second of EDMC's last event ...
        self._sec_n: Dict[str, int] = {}
        self._sec_keys: Set[str] = set()        # ... and the keys passed on in it
        self._done: Set[str] = set()
        self._order: Deque[str] = deque()

    def delivered(self, e: Dict[str, Any], wall: float) -> Optional[str]:
        """An event EDMC passes on: "skip" when the plugin stored it already,
        "back" when it is the first new one after a gap, else None."""
        stamp = e.get("timestamp")
        with self.lock:
            if stamp != self._sec:
                self._sec, self._sec_n, self._sec_keys = stamp, {}, set()
            b = base_key(e)
            n = self._sec_n.get(b, 0)
            self._sec_n[b] = n + 1
            key = "%s#%d" % (b, n)
            if key in self._done:
                return "skip"
            self._sec_keys.add(key)
            t = journalscan.event_time(e)
            if t is not None:
                self.last_ts = t if self.last_ts is None else max(self.last_ts, t)
            self.last_wall = wall
            if self.gap_since is None:
                return None
            self.gap_since = None
            return "back"

    def due(self, wall: float) -> bool:
        """Status.json arrived: time to look at the journal? (EDMC has passed
        on an event before, has been quiet for QUIET_S, the last look was
        CHECK_S ago and is finished.) True marks the look as running."""
        with self.lock:
            if self.busy or self.last_ts is None:
                return False
            if wall - self.last_wall < QUIET_S or wall - self.checked < CHECK_S:
                return False
            self.busy = True
            self.checked = wall
            return True

    def finish(self) -> None:
        """The look at the journal is over."""
        with self.lock:
            self.busy = False

    def changed(self, sig: Tuple[str, int, int]) -> bool:
        """The newest journal file (path, size, mtime) differs from the last look."""
        with self.lock:
            if sig == self.sig:
                return False
            self.sig = sig
            return True

    def missed(self, events: List[Dict[str, Any]], wall: float) -> List[Pair]:
        """The events of the journal EDMC has not passed on and the plugin
        has not stored: newer than both, at least LAG_S old. Fewer than
        MIN_MISSED at the start of a gap are no gap."""
        keys = keys_of(events)
        with self.lock:
            since = max(t for t in (self.last_ts, self.high) if t is not None)
            out: List[Pair] = []
            for e, k in zip(events, keys):
                t = journalscan.event_time(e)
                if t is None or t < since or t > wall - LAG_S:
                    continue
                if k in self._done or (t == self.last_ts and k in self._sec_keys):
                    continue
                out.append((e, k))
            if self.gap_since is None and len(out) < MIN_MISSED:
                return []
        return out

    def take(self, key: str) -> None:
        """The plugin stores this event itself (before it does)."""
        with self.lock:
            self._done.add(key)
            self._order.append(key)
            while len(self._order) > KEEP_KEYS:
                self._done.discard(self._order.popleft())

    def stored(self, pairs: List[Pair]) -> bool:
        """The plugin has stored these events; True when a gap begins."""
        times = [t for t in (journalscan.event_time(e) for e, _k in pairs) if t is not None]
        with self.lock:
            if times:
                self.high = max(times + ([self.high] if self.high is not None else []))
            new = self.gap_since is None
            if new:
                self.gap_since = self.last_ts
                self.added = 0
            self.added += len(pairs)
            return new


WATCH = Watch()
_board_t = 0.0


def _clock(t: Optional[float]) -> str:
    return time.strftime("%H:%M", time.gmtime(t)) if t is not None else "?"


def gap_text() -> str:
    """The panel line while EDMC passes nothing on, else ""."""
    w = WATCH
    if w.gap_since is None:
        return ""
    return ("EDMC gets no journal events since %s UTC - restart EDMC "
            "(%d missed ones stored by the plugin)" % (_clock(w.gap_since), w.added))


def journal_event(entry: Dict[str, Any]) -> bool:
    """journal.journal_entry, first (main thread): note the event. False:
    the plugin stored it itself during a gap - leave it out."""
    r = WATCH.delivered(entry, time.time())
    if r == "back":
        logger.info("journal | EDMC passes on journal events again (%d missed ones were stored "
                    "by the plugin)", WATCH.added)
        _show()
    return r != "skip"


def status_tick() -> None:
    """journal.dashboard_entry (main thread): Status.json arrived. Keeps the
    overlay warning up during a gap; when EDMC has been quiet long enough,
    a worker looks at the journal."""
    global _board_t
    now = time.time()
    if WATCH.gap_since is not None and now - _board_t >= CHECK_S:
        _board_t = now
        _board()
    if ST.db is None or not WATCH.due(now):
        return
    threading.Thread(target=_look, name="SHBOX-journal gap", daemon=True).start()


def _look() -> None:
    """Worker: read the newest journal file if it changed; store what EDMC
    missed. Never raises."""
    try:
        files = journalscan.journal_files(maintenance._journal_dir(), last=1)
        if not files:
            return
        st = os.stat(files[0])
        if not WATCH.changed((files[0], st.st_size, st.st_mtime_ns)):
            return
        todo = WATCH.missed(list(journalscan.read_events(files)), time.time())
        if todo:
            _store(todo)
    except Exception:
        logger.exception("journal | looking for missed events failed")
    finally:
        WATCH.finish()


def _store(todo: List[Pair]) -> None:
    """Worker: store the missed events in order, CHUNK per database lock."""
    for i in range(0, len(todo), CHUNK):
        part = todo[i:i + CHUNK]
        with ST.lock:
            for e, k in part:
                WATCH.take(k)
                try:
                    ST.db.ingest_journal_event(e)
                except Exception:
                    logger.debug("journal | storing a missed %s failed", e.get("event"), exc_info=True)
    new = WATCH.stored(todo)
    first, last = todo[0][0].get("timestamp"), todo[-1][0].get("timestamp")
    if new:
        logger.warning("journal | EDMC has passed on no journal event since %s UTC, the journal holds "
                       "%d more (%s .. %s) - the game wrote its journal anew? Stored them; restart "
                       "EDMC", _clock(WATCH.gap_since), len(todo), first, last)
    else:
        logger.info("journal | %d more missed events stored (%s .. %s)", len(todo), first, last)
    uithread._ui(_show)


def _show() -> None:
    """Main thread: the panel line and the overlay warning, or neither."""
    ST.journal_gap = gap_text()
    _board()
    panel._refresh()


def _board() -> None:
    """The overlay warning while the gap lasts; gone when it ends."""
    w = WATCH
    lines = situation.journal_gap_lines(w.added) if w.gap_since is not None else []
    cockpitinfo._put("journal", lines, CHECK_S * 3)
