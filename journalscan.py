# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
journalscan.py - reading the game's journal files (H6, first part of load.py)
=============================================================================
Plain Python, no EDMC, no Tk. load.py used to hold all of this inline; the
logic is unchanged, it only lives here now so it can be tested on its own:

* journal_files()    the journal files of a folder, oldest first
* newest_location()  the last FSDJump / Location / CarrierJump (system, id64, pos)
* last_body()        the last body we were at (ApproachBody, Touchdown, ...)
* approached_bodies() the bodies approached in one system, in order (route review)
* WorkMeter          times DSS mapping and sampling, and collects the
                     body-to-body supercruise legs - the SAME code for the
                     replay at start and for the live events (up to 4.9 the
                     live path was a separate, smaller copy)
* replay_work()      a WorkMeter fed with whole journal files
* replay_fuel()      ship, tank and fuel per jump into a deepspace.FuelState

    python tests/journalscan_selftest.py      (self test, no game needed)
"""

from __future__ import annotations

import calendar
import glob
import json
import os
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

if __package__:     # inside the plugin package (EDMC)
    from .procgen import star_pos
else:               # on its own: the FIS, plain imports
    from procgen import star_pos

__all__ = ["journal_files", "newest_location", "last_body", "approached_bodies", "WorkMeter",
           "replay_work", "replay_fuel", "replay_fuel_events", "read_events", "read_events_matching"]

LOCATION_EVENTS = ("FSDJump", "Location", "CarrierJump")
BODY_EVENTS = ("ApproachBody", "SupercruiseExit", "Touchdown", "Liftoff", "SAAScanComplete")


def journal_files(folder: Optional[str], last: Optional[int] = None) -> List[str]:
    """Journal files of the folder, oldest first (both name styles)."""
    if not folder:
        return []
    files = sorted(glob.glob(os.path.join(folder, "Journal.*.log"))
                   + glob.glob(os.path.join(folder, "Journal_*.log")))
    return files[-last:] if last else files


def _lines_backwards(files: List[str]) -> Iterator[str]:
    for fn in reversed(files):
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if line:
                yield line


def read_events(files: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Every parseable event of the files, in order; unreadable files are skipped."""
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict):
                        yield e
        except OSError:
            continue


def read_events_matching(files: Iterable[str], needles: Sequence[str]) -> Iterator[Dict[str, Any]]:
    """4.12: the events of the files whose line holds one of the needles
    (e.g. '"MarketSell"'), in order - only those lines are parsed, so every
    journal can be read for a few event names."""
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not any(n in line for n in needles):
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict):
                        yield e
        except OSError:
            continue


def newest_location(folder: Optional[str]
                    ) -> Optional[Tuple[str, int, Tuple[float, float, float]]]:
    """
    The current system straight out of the newest journal files.

    EDMC synthesises StartUp when the game is already running, so a session
    that begins parked in a system never sees FSDJump or Location. Scanning
    the newest journals backwards for the last location event answers it
    exactly - name, id64 and coordinates, no guessing.
    """
    for line in _lines_backwards(journal_files(folder, 3)):
        if '"StarSystem"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") not in LOCATION_EVENTS:
            continue
        pos = star_pos(e.get("StarPos"))
        if e.get("StarSystem") and e.get("SystemAddress") and pos:
            return (e["StarSystem"], e["SystemAddress"], pos)
    return None


def last_body(folder: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    The last body we were at: the newest ApproachBody / SupercruiseExit /
    Touchdown / Liftoff / SAAScanComplete. The live position appears in no
    journal event, so this is the closest thing to it.
    """
    for line in _lines_backwards(journal_files(folder, 3)):
        if '"BodyID"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") in BODY_EVENTS and e.get("BodyID") is not None:
            return {"body_id": e["BodyID"],
                    "name": e.get("Body") or e.get("BodyName") or "",
                    "sys": e.get("SystemAddress")}
    return None


def approached_bodies(folder: Optional[str], sys_id64: Any, last: int = 8
                      ) -> List[Tuple[str, float]]:
    """
    (body name, unix time) for every body approached in this system, in
    order: the first ApproachBody / SupercruiseExit / SAAScanComplete per
    body in the newest `last` journals. Read from the files rather than kept
    in memory, so it also covers a system flown before the plugin ran.
    """
    out: List[Tuple[str, float]] = []
    seen = set()
    for fn in journal_files(folder, last):
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"Body' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("SystemAddress") != sys_id64:
                        continue
                    if e.get("event") not in ("ApproachBody", "SupercruiseExit",
                                              "SAAScanComplete"):
                        continue
                    nm = e.get("Body") or e.get("BodyName")
                    if not nm or nm in seen:
                        continue
                    ts = event_time(e)
                    if ts is None:
                        continue
                    seen.add(nm)
                    out.append((nm, ts))
        except OSError:
            continue
    out.sort(key=lambda p: p[1])
    return out


def event_time(e: Dict[str, Any]) -> Optional[float]:
    """The event's timestamp as Unix time, or None."""
    try:
        return float(calendar.timegm(time.strptime(e["timestamp"], "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, KeyError, TypeError):
        return None


class WorkMeter:
    """
    Times the work at a body as it happens, from the events alone.

    A surface scan is bracketed by the arrival at the body (ApproachBody or
    SupercruiseExit) and SAAScanComplete; most mapping is done straight from
    supercruise without either, so the gap between two mappings in one
    system counts as well (transfer plus probe run = the per-body rate the
    estimate needs). A sample is bracketed by its own Log and Analyse.
    Supercruise legs body A -> body B inside one system are collected for
    the travel fit; the first leg after a jump has no start body and is left
    out on purpose.
    """

    def __init__(self) -> None:
        self.dss: List[float] = []
        self.bio: List[float] = []
        # (system, body A, body B, entry time, seconds)
        self.sc_legs: List[Tuple[int, str, str, float, float]] = []
        self._arrive: Dict[str, float] = {}
        self._blog: Dict[Tuple, float] = {}
        self._last_saa: Dict[Any, float] = {}
        self._here: Dict[str, Any] = {"sys": None, "body": None}
        self._sc_from: Optional[Tuple[Any, str, float]] = None

    def feed(self, e: Dict[str, Any], ts: float) -> Optional[Tuple[str, float]]:
        """One event at time ts; returns ("dss" | "bio", seconds) when one was timed."""
        v = e.get("event")
        self._track_place(v, e, ts)
        if v in ("ApproachBody", "SupercruiseExit"):
            if e.get("Body"):
                self._arrive[e["Body"]] = ts
        elif v == "SAAScanComplete":
            return self._time_dss(e, ts)
        elif v == "ScanOrganic":
            return self._time_bio(e, ts)
        return None

    def _track_place(self, v: Any, e: Dict[str, Any], ts: float) -> None:
        """Where we are (system, body) and the supercruise legs between bodies."""
        if v in LOCATION_EVENTS:
            self._here = {"sys": e.get("SystemAddress"), "body": None}
            self._sc_from = None
        elif v == "SupercruiseEntry":
            h = self._here
            self._sc_from = (h["sys"], h["body"], ts) if h["sys"] and h["body"] else None
        elif v == "SupercruiseExit":
            b = e.get("Body")
            f = self._sc_from
            if (f and b and b != f[1] and e.get("SystemAddress") == f[0]
                    and 5 < ts - f[2] < 3600):
                self.sc_legs.append((f[0], f[1], b, f[2], ts - f[2]))
            self._sc_from = None
            if b and e.get("SystemAddress"):
                self._here = {"sys": e["SystemAddress"], "body": b}
        elif v in ("ApproachBody", "Touchdown", "Liftoff"):
            if e.get("Body") and e.get("SystemAddress"):
                self._here = {"sys": e["SystemAddress"], "body": e["Body"]}
        elif v in ("Shutdown", "LoadGame", "Died", "Resurrect"):
            self._sc_from = None

    def _time_dss(self, e: Dict[str, Any], ts: float) -> Optional[Tuple[str, float]]:
        """A surface scan: from the arrival at the body, else from the mapping before."""
        out: Optional[Tuple[str, float]] = None
        t0 = self._arrive.pop(e.get("BodyName"), None)
        prev = self._last_saa.get(e.get("SystemAddress"))
        if t0 and 10 < ts - t0 < 1800:
            out = ("dss", ts - t0)
        elif prev and 20 < ts - prev < 1800:
            out = ("dss", ts - prev)
        self._last_saa[e.get("SystemAddress")] = ts
        if out:
            self.dss.append(out[1])
        return out

    def _time_bio(self, e: Dict[str, Any], ts: float) -> Optional[Tuple[str, float]]:
        """A sample: from its first Log (or Sample) to its Analyse."""
        key = (e.get("SystemAddress"), e.get("Body"), e.get("Species"))
        kind = e.get("ScanType")
        if kind in ("Log", "Sample"):
            self._blog.setdefault(key, ts)
        elif kind == "Analyse":
            t0 = self._blog.pop(key, None)
            if t0 and 20 < ts - t0 < 3600:
                out = ("bio", ts - t0)
                self.bio.append(out[1])
                return out
        return None


def replay_work(files: Iterable[str], since: Optional[float] = None) -> WorkMeter:
    """A WorkMeter fed with every timed event of the files - from `since`
    on, when the model was reset then (SK3, learnreset)."""
    m = WorkMeter()
    for e in read_events(files):
        ts = event_time(e)
        if ts is not None and (since is None or ts >= since):
            m.feed(e, ts)
    return m


def replay_fuel(files: Iterable[str], fuel: Any) -> Any:
    """Ship, tank, jump range, mass and fuel per jump into a
    deepspace.FuelState (its feed(), as the plugin does live)."""
    return replay_fuel_events(read_events(files), fuel)


def replay_fuel_events(events: Iterable[Dict[str, Any]], fuel: Any) -> Any:
    """replay_fuel() for any journal lines in order - 5.0: the EDDiscovery
    archive's older lines first, then the journal files."""
    cmdr: Optional[str] = None
    for e in events:
        v = e.get("event")
        try:
            if v in ("Commander", "LoadGame"):
                cmdr = e.get("Name") or e.get("Commander") or cmdr
            fuel.feed(e, cmdr, event_time(e))
        except (TypeError, ValueError, AttributeError):
            continue
    return fuel
