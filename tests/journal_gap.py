# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
EDMC passes on no journal events (4.12.1, journalgap.py).

16.11.2026: the game wrote its journal anew under the same name; EDMC read
on at its old place and passed nothing on for the rest of the session. No
landing, sample or find was stored, the FIS's PLANET showed only the track.
This test pins down that

  * Watch: no look before EDMC passed on an event, none while EDMC is not
    quiet, one every CHECK_S, only when the file changed; missed are the
    events newer than EDMC's last one and LAG_S old, the same second's
    events told apart; a few events are no gap; stored ones are left out
    when EDMC passes them on later; a new event ends the gap;
  * sysdb: an event stored late takes its position from the stored track,
    not from where you are now; a live event keeps the live fix;
  * the whole way through the EDMC hooks: a journal written anew, Status.json
    coming on, the landing, the parked SRV and the sample stored with the
    right positions, the warning in the panel and on the overlay, gone when
    EDMC passes on a new event.

    python tests/journal_gap.py      (from the plugin folder)
"""
import calendar
import json
import os
import sys
import tempfile
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ("config", "theme", "myNotebook", "monitor", "l10n", "companion", "plug",
          "EDMCLogging", "ttkHyperlinkLabel"):
    sys.modules[m] = mock.MagicMock()
try:                                  # CI images may lack Tk; no window is opened
    import tkinter  # noqa: F401
except ImportError:
    for m in ("tkinter", "tkinter.filedialog", "tkinter.ttk"):
        sys.modules[m] = mock.MagicMock()

import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import cockpitinfo, journalgap, maintenance, panel, planning, state, uithread  # noqa: E402
from SHBOXSEARCH.sysdb import SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


def epoch(stamp):
    return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


T0 = epoch("2026-11-16T17:00:00Z")

# ---------------------------------------------------------------- 1. Watch
print("Watch")
W = journalgap.Watch
w = W()
check(not w.due(T0 + 500), "no look before EDMC passed on any event")
w.delivered({"timestamp": iso(T0), "event": "Location"}, T0)
check(not w.due(T0 + 30), "no look while EDMC was heard from 30 s ago")
check(w.due(T0 + 61), "EDMC quiet for 60 s: look")
check(not w.due(T0 + 62), "one look at a time")
w.finish()
check(not w.due(T0 + 70), "the next look CHECK_S later")
check(w.due(T0 + 92), "... and then again")
w.finish()
check(w.changed(("j", 10, 1)) and not w.changed(("j", 10, 1)) and w.changed(("j", 12, 2)),
      "the file is read again only when it changed")

ev = [{"timestamp": iso(T0 - 5), "event": "Music"},
      {"timestamp": iso(T0), "event": "Location"},                  # passed on
      {"timestamp": iso(T0), "event": "Location"},                  # same second, a second one
      {"timestamp": iso(T0 + 20), "event": "Touchdown", "Body": "X 1"},
      {"timestamp": iso(T0 + 21), "event": "MiningRefined", "Type": "$tin_name;"},
      {"timestamp": iso(T0 + 21), "event": "MiningRefined", "Type": "$tin_name;"},
      {"timestamp": iso(T0 + 95), "event": "Music"}]                # too young
miss = w.missed(ev, T0 + 100)
check([e["event"] for e, _k in miss] == ["Location", "Touchdown", "MiningRefined", "MiningRefined"],
      "missed: newer than EDMC's last event, the same second's second one, not the last LAG_S")
check(len({k for _e, k in miss}) == 4, "two tonnes in one second are two events")
w2 = W()
w2.delivered({"timestamp": iso(T0), "event": "Location"}, T0)
check(w2.missed(ev[3:5], T0 + 100) == [], "two events are no gap (main menu, the game closing)")
for _e, k in miss:
    w.take(k)
check(w.stored(miss) and w.gap_since == T0 and w.added == 4, "a gap begins at EDMC's last event")
check(w.high == T0 + 21, "the newest stored event")
check(w.missed(ev, T0 + 100) == [], "stored events are not missed again")
more = ev + [{"timestamp": iso(T0 + 120), "event": "Liftoff"}]
m2 = w.missed(more, T0 + 140)
check([e["event"] for e, _k in m2] == ["Music", "Liftoff"], "in a gap, single events count")
check(not w.stored(m2) and w.added == 6, "the same gap goes on")
check(w.delivered(dict(ev[3]), T0 + 150) == "skip", "EDMC passes on a stored event later: left out")
check(w.gap_since is not None, "... and the gap is not over")
check(w.delivered({"timestamp": iso(T0 + 160), "event": "Embark"}, T0 + 160) == "back",
      "a new event from EDMC ends the gap")
check(w.gap_since is None and w.last_ts == T0 + 160, "EDMC's last event moves on")
lines = journalgap.situation.journal_gap_lines(1234)
check(len(lines) == 2 and all(len(t) <= 44 for t, _c in lines), "overlay lines fit 44 characters")

# ---------------------------------------------------------------- 2. sysdb
print("sysdb: positions of late events")
d0 = tempfile.mkdtemp()
db = SystemDB(os.path.join(d0, "p.sqlite"))
for i, lat in enumerate((1.0, 2.0, 3.0)):
    db.add_track_point(7, {"body": "B 1", "lat": lat, "lon": 0.0, "mode": "foot"}, T0 + 60 * i)
db.note_status({"timestamp": iso(T0 + 200), "BodyName": "B 1", "Latitude": 9.0, "Longitude": 9.0,
                "Flags": 2, "Flags2": 1}, now=T0 + 200)
p = db._pos_at(7, "B 1", T0 + 70)
check(p is not None and p["lat"] == 2.0, "late event: the track point before it, not where you are now")
p = db._pos_at(7, "B 1", T0 + 199)
check(p is not None and p["lat"] == 9.0, "live event: the live fix")
check(db._pos_at(7, "B 1", T0 - 500) is None, "no track near it and the fix is newer: no position")
check(db._pos_at(7, "B 2", T0 + 70) is None, "another body: no position")
mk = {"timestamp": iso(T0 - 900), "SystemAddress": 7}
db._mark(mk, "bio_log", "B 1", "Roseum Brain Tree")
row = db.marks_of(7, "B 1")[0]
check(row["lat"] is None, "stored without a position (no track then)")
db._mark(mk, "bio_log", "B 1", "Roseum Brain Tree", lat=5.0, lon=6.0)
db._mark(mk, "bio_log", "B 1", "Roseum Brain Tree", lat=7.0, lon=8.0)
rows = db.marks_of(7, "B 1")
check(len(rows) == 1 and (rows[0]["lat"], rows[0]["lon"]) == (5.0, 6.0),
      "the same event again (a replay) fills the position in once, then it stays")
db.cx.close()

# ------------------------------------------------- 3. through EDMC's hooks
print("EDMC hooks: a journal written anew")
NOW = [T0]
time.time = lambda: NOW[0]               # plugin, sysdb and journalgap share the time module
plugin_pkg.use_settings({})
panel._set_status = lambda m: None
uithread._ui = lambda f, *a, **k: f()
uithread._run_async = lambda fn, *a, **k: None
for name in ("_request_route", "_maybe_extend", "_update_route_targets"):
    setattr(planning, name, lambda *a, **k: None)
ST = state.ST
ST.overlay = None
journalgap.WATCH = journalgap.Watch()


def je(entry):
    load.journal_entry("Tester", False, "", "", entry, {"FID": "F1"})


def gap_threads():
    for t in threading.enumerate():
        if t.name == "SHBOX-journal gap":
            t.join(10)


def status(t, lat):
    NOW[0] = t
    load.dashboard_entry("Tester", False, {
        "timestamp": iso(t), "Flags": 2, "Flags2": 1, "Latitude": lat, "Longitude": 20.0,
        "Altitude": 0, "Heading": 0, "BodyName": "Gap 1", "PlanetRadius": 1000000.0})
    gap_threads()


def write(path, events, mode):
    with open(path, mode, encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


A = 634480595618
org = {"event": "ScanOrganic", "SystemAddress": A, "Body": 1, "Genus_Localised": "Brain Trees",
       "Species_Localised": "Roseum Brain Tree"}
try:
    with tempfile.TemporaryDirectory() as d:
        maintenance._journal_dir = lambda: d
        ST.db = SystemDB(os.path.join(d, "t.sqlite"))
        jf = os.path.join(d, "Journal.2026-11-16T174337.01.log")
        early = [{"timestamp": iso(T0), "event": "Location", "StarSystem": "Gap", "SystemAddress": A,
                  "StarPos": [1.0, 2.0, 3.0], "Body": "Gap 1", "BodyID": 1, "BodyType": "Planet"},
                 {"timestamp": iso(T0 + 2), "event": "Scan", "ScanType": "Detailed", "BodyName": "Gap 1",
                  "BodyID": 1, "SystemAddress": A, "StarSystem": "Gap", "PlanetClass": "Rocky body",
                  "Radius": 1000000.0, "Landable": True, "DistanceFromArrivalLS": 10.0}]
        write(jf, early, "w")
        for e in early:
            je(e)                                       # EDMC passes these on ...
        # ... then the game writes the journal anew and EDMC passes on nothing
        write(jf, [{"timestamp": iso(T0 + 10), "event": "Fileheader", "part": 1},
                   {"timestamp": iso(T0 + 30), "event": "Touchdown", "SystemAddress": A, "Body": "Gap 1",
                    "BodyID": 1, "Latitude": 10.0, "Longitude": 20.0, "PlayerControlled": True,
                    "OnPlanet": True},
                   {"timestamp": iso(T0 + 35), "event": "Disembark", "SRV": True, "SystemAddress": A,
                    "Body": "Gap 1", "BodyID": 1, "OnPlanet": True}], "w")
        status(T0 + 32, 10.0)
        check(ST.db.marks_of(A, "Gap 1") == [] and ST.journal_gap == "",
              "EDMC quiet for 32 s: nothing looked at yet")
        status(T0 + 75, 10.01)
        kinds = {r["kind"]: r for r in ST.db.marks_of(A, "Gap 1")}
        check("touchdown" in kinds and "srv_parked" in kinds, "the missed landing and parked SRV are stored")
        check(kinds.get("srv_parked") is not None and kinds["srv_parked"]["lat"] == 10.0,
              "the parked SRV where you were then (track), not where you are now")
        check(ST.journal_gap.startswith("EDMC gets no journal events since 17:00 UTC"),
              "panel line: %s" % ST.journal_gap)
        check(cockpitinfo.BOARD.has("journal"), "overlay: the warning")
        write(jf, [dict(org, timestamp=iso(T0 + 80), ScanType="Log")], "a")
        status(T0 + 95, 10.02)
        check(not any(r["kind"] == "bio_log" for r in ST.db.marks_of(A, "Gap 1")),
              "the next look waits CHECK_S")
        status(T0 + 106, 10.03)
        bio = [r for r in ST.db.marks_of(A, "Gap 1") if r["kind"] == "bio_log"]
        check(len(bio) == 1 and bio[0]["label"] == "Roseum Brain Tree" and bio[0]["lat"] == 10.01,
              "the sample is stored where it was taken (track at 17:01:15)")
        check("2 missed" not in ST.journal_gap and "4 missed" in ST.journal_gap,
              "the count goes on: %s" % ST.journal_gap)
        n = len(ST.db.marks_of(A, "Gap 1"))
        NOW[0] = T0 + 110
        je({"timestamp": iso(T0 + 30), "event": "Touchdown", "SystemAddress": A, "Body": "Gap 1",
            "BodyID": 1, "Latitude": 10.0, "Longitude": 20.0, "PlayerControlled": True, "OnPlanet": True})
        check(len(ST.db.marks_of(A, "Gap 1")) == n and ST.journal_gap,
              "EDMC passes on a stored event later: left out, the warning stays")
        NOW[0] = T0 + 120
        je({"timestamp": iso(T0 + 119), "event": "Embark", "SRV": True, "SystemAddress": A,
            "Body": "Gap 1", "BodyID": 1, "OnPlanet": True})
        check(ST.journal_gap == "" and not cockpitinfo.BOARD.has("journal"),
              "a new event from EDMC: warning gone from the panel and the overlay")
        check(any(r["kind"] == "embark" for r in ST.db.marks_of(A, "Gap 1")), "and EDMC's events are stored again")
        ST.db.cx.close()
        ST.db = None
except Exception:
    import traceback
    traceback.print_exc()
    fails += 1

print("journal gap: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
