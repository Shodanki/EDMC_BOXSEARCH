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

    python journalscan.py      (self test, no game needed)
"""

from __future__ import annotations

import calendar
import glob
import json
import os
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

__all__ = ["journal_files", "newest_location", "last_body", "approached_bodies", "WorkMeter",
           "replay_work", "replay_fuel", "read_events"]

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
        pos = e.get("StarPos") or []
        if e.get("StarSystem") and e.get("SystemAddress") and len(pos) >= 3:
            return (e["StarSystem"], e["SystemAddress"], (pos[0], pos[1], pos[2]))
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
        out: Optional[Tuple[str, float]] = None
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
        if v in ("ApproachBody", "SupercruiseExit"):
            if e.get("Body"):
                self._arrive[e["Body"]] = ts
        elif v == "SAAScanComplete":
            t0 = self._arrive.pop(e.get("BodyName"), None)
            prev = self._last_saa.get(e.get("SystemAddress"))
            if t0 and 10 < ts - t0 < 1800:
                out = ("dss", ts - t0)
            elif prev and 20 < ts - prev < 1800:
                out = ("dss", ts - prev)
            self._last_saa[e.get("SystemAddress")] = ts
            if out:
                self.dss.append(out[1])
        elif v == "ScanOrganic":
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


def replay_work(files: Iterable[str]) -> WorkMeter:
    """A WorkMeter fed with every timed event of the files."""
    m = WorkMeter()
    for e in read_events(files):
        ts = event_time(e)
        if ts is not None:
            m.feed(e, ts)
    return m


def replay_fuel(files: Iterable[str], fuel: Any) -> Any:
    """Ship, tank, jump range and fuel per jump into a deepspace.FuelState."""
    cmdr: Optional[str] = None
    for e in read_events(files):
        v = e.get("event")
        try:
            if v in ("Commander", "LoadGame"):
                cmdr = e.get("Name") or e.get("Commander") or cmdr
            if v in ("LoadGame", "Loadout") and e.get("ShipID") is not None:
                fuel.set_ship((cmdr, e.get("ShipID")))
            if v == "Loadout":
                if e.get("MaxJumpRange"):
                    fuel.max_jump = float(e["MaxJumpRange"])
                cap = (e.get("FuelCapacity") or {}).get("Main")
                if cap:
                    fuel.capacity = float(cap)
            elif v == "FSDJump":
                if e.get("FuelUsed") is not None:
                    fuel.add_jump(e.get("JumpDist"), e.get("FuelUsed"))
                if e.get("FuelLevel") is not None:
                    fuel.level = float(e["FuelLevel"])
        except (TypeError, ValueError):
            continue
    return fuel


# --------------------------------------------------------------------------
def _selftest() -> int:
    import tempfile
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    def t(s: int) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1_800_000_000 + s))

    ev1 = [
        {"event": "Commander", "Name": "Tester"},
        {"event": "Loadout", "ShipID": 3, "MaxJumpRange": 55.0, "FuelCapacity": {"Main": 32.0}},
        {"event": "FSDJump", "StarSystem": "Js A", "SystemAddress": 11, "StarPos": [1, 2, 3],
         "JumpDist": 40.0, "FuelUsed": 4.0, "FuelLevel": 28.0},
        {"event": "SupercruiseExit", "Body": "Js A 1", "BodyID": 1, "SystemAddress": 11},
        {"event": "SAAScanComplete", "BodyName": "Js A 1", "BodyID": 1, "SystemAddress": 11},
        {"event": "SupercruiseEntry", "SystemAddress": 11},
        {"event": "SupercruiseExit", "Body": "Js A 2", "BodyID": 2, "SystemAddress": 11},
        {"event": "SAAScanComplete", "BodyName": "Js A 3", "BodyID": 3, "SystemAddress": 11},
    ]
    times1 = [0, 1, 10, 100, 190, 300, 360, 600]
    ev2 = [
        {"event": "ScanOrganic", "ScanType": "Log", "SystemAddress": 11, "Body": 2, "Species": "S"},
        {"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 11, "Body": 2, "Species": "S"},
        {"event": "Location", "StarSystem": "Js B", "SystemAddress": 12, "StarPos": [4, 5, 6]},
        {"event": "Touchdown", "Body": "Js B 4", "BodyID": 4, "SystemAddress": 12},
    ]
    times2 = [700, 1100, 1200, 1300]
    with tempfile.TemporaryDirectory() as d:
        for fn, evs, ts in (("Journal.2026-11-13T010000.01.log", ev1, times1),
                            ("Journal.2026-11-13T020000.01.log", ev2, times2)):
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                for e, s in zip(evs, ts):
                    f.write(json.dumps(dict(e, timestamp=t(s))) + "\n")
                f.write("not json\n")
        files = journal_files(d)
        check(len(files) == 2 and files[0].endswith("010000.01.log"), "journal files oldest first")
        check(newest_location(d) == ("Js B", 12, (4, 5, 6)), "newest location: the later Location")
        lb = last_body(d)
        check(lb == {"body_id": 4, "name": "Js B 4", "sys": 12}, "last body: the Touchdown")
        m = replay_work(files)
        check(m.dss == [90.0, 410.0], "DSS: arrival bracket 90 s, then gap since last mapping 410 s")
        check(m.bio == [400.0], "sampling: Log -> Analyse 400 s")
        check(m.sc_legs == [(11, "Js A 1", "Js A 2", 1_800_000_300.0, 60.0)],
              "one body-to-body supercruise leg")

        class Fuel:
            def __init__(self):
                self.ship, self.jumps, self.level = None, [], None
                self.max_jump = self.capacity = None

            def set_ship(self, s):
                self.ship = s

            def add_jump(self, dist, used):
                self.jumps.append((dist, used))

        fu = replay_fuel(files, Fuel())
        check(fu.ship == ("Tester", 3) and fu.capacity == 32.0 and fu.max_jump == 55.0
              and fu.jumps == [(40.0, 4.0)] and fu.level == 28.0, "fuel replay")
        check(approached_bodies(d, 11) == [("Js A 1", 1_800_000_100.0),
                                           ("Js A 2", 1_800_000_360.0),
                                           ("Js A 3", 1_800_000_600.0)]
              and approached_bodies(d, 99) == [], "bodies approached in one system, in order")
        check(newest_location(os.path.join(d, "none")) is None and journal_files(None) == [],
              "no folder -> nothing")
    live = WorkMeter()
    check(live.feed({"event": "ApproachBody", "Body": "X 1", "SystemAddress": 5}, 0.0) is None
          and live.feed({"event": "SAAScanComplete", "BodyName": "X 1", "SystemAddress": 5}, 5.0)
          is None, "under 10 s is no measurement")
    print("journalscan self test: %s" % ("all OK" if not fails else "%d FAILED" % fails))
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
