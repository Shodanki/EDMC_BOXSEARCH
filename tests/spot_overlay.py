# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SP2 (5.1.0, user 25.11.): a ring hotspot set as target shows the SPOT item
in the overlay's situation column - the chance of a good field (MP4) and
what the commander got there before (MP3), from miningfields.py. End to
end: journal events and Status.json in through the plugin's hooks, the
board's lines out; every line within 44 characters.

    python tests/spot_overlay.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import cockpitinfo, miningfields, situation, state, uithread  # noqa: E402
from SHBOXSEARCH.sysdb import CMDR_READY, SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


ST = state.ST
ST.db = SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
ST.db.set_meta(CMDR_READY, "test")
plugin_pkg.use_settings({})
uithread._run_async = lambda fn, *a, label="": fn(*a)
STATE = {"FID": "F42"}
SYS = 4242


def ev(e, day, minute):
    e = dict(e, timestamp="2027-01-%02dT10:%02d:00Z" % (day, minute))
    load.journal_entry("Cmdr", False, "", "", e, STATE)


def ring_scan(ring, body_id, mats, day):
    ev({"event": "SAASignalsFound", "SystemAddress": SYS, "BodyName": ring, "BodyID": body_id,
        "Signals": [{"Type": m, "Count": 1} for m in mats]}, day, 0)


def session(ring, day, shares, prospectors, tonnes):
    """Mining in a ring: prospectors, rocks with these tritium shares, tonnes refined, docked."""
    ev({"event": "SupercruiseExit", "StarSystem": "Spot Sys", "SystemAddress": SYS, "Body": ring,
        "BodyType": "PlanetaryRing"}, day, 1)
    for _i in range(prospectors):
        ev({"event": "LaunchDrone", "Type": "Prospector"}, day, 2)
    for s in shares:
        ev({"event": "ProspectedAsteroid", "Content": "$AsteroidMaterialContent_Medium;",
            "Materials": [{"Name": "Tritium", "Proportion": s}] if s else [{"Name": "Bromellite", "Proportion": 9.0}]},
           day, 3)
    for _i in range(tonnes):
        ev({"event": "MiningRefined", "Type": "$tritium_name;", "Type_Localised": "Tritium"}, day, 4)
    ev({"event": "Docked", "StationName": "V2L-07J", "StationType": "FleetCarrier", "MarketID": 1}, day, 50)


def dest(body_id, name="$SAA_RingHotspot:#type=$Tritium_name;;", loc="Tritium Hotspot"):
    load.dashboard_entry("Cmdr", False, {"event": "Status", "timestamp": "2027-01-09T10:00:00Z", "Flags": 1 << 24,
                                         "Destination": {"System": SYS, "Body": body_id, "Name": name,
                                                         "Name_Localised": loc}})


def spot():
    it = cockpitinfo.BOARD.items.get("spot")
    return [t for t, _c in it[1]] if it else []


print("the field book")
fb = miningfields.FieldBook()
fb.add({"event": "FSDJump", "timestamp": "2027-01-01T10:00:00Z", "StarSystem": "X", "Factions": [1, 2, 3]})
fb.add({"event": "Music", "timestamp": "2027-01-01T10:00:01Z"})
check(fb.events == [{"event": "FSDJump", "timestamp": "2027-01-01T10:00:00Z"}],
      "only the events the fields need, borders slimmed: %s" % fb.events)
fb.load([{"event": "Docked", "timestamp": "2026-12-01T10:00:00Z", "StationName": "S"}])
check([e["event"] for e in fb.events] == ["Docked", "FSDJump"] and fb.loaded,
      "the history first, the live event that came meanwhile kept")
check(miningfields.hotspot_material("$SAA_RingHotspot:#type=$LowTemperatureDiamond_name;;")
      == "lowtemperaturediamond" and miningfields.hotspot_material("Some Station") is None, "the target's material")

print("before the history is read")
cockpitinfo.FIELDS = miningfields.FieldBook()
ev({"event": "FSDJump", "StarSystem": "Spot Sys", "SystemAddress": SYS, "StarPos": [1.0, 2.0, 3.0]}, 1, 0)
ring_scan("Spot Sys 1 A Ring", 11, ["Tritium"], 1)
dest(11)
check(spot()[:2] == ["SPOT  Tritium · 1 A Ring", "      fields still counting ..."], "SPOT, counting: %s" % spot())

print("learnt from the commander's fields")
cockpitinfo.FIELDS.load([])
for day, ring in ((1, "Spot Sys 1 A Ring"), (2, "Spot Sys 2 A Ring"), (3, "Spot Sys 3 A Ring")):
    ring_scan(ring, 10 + day, ["Tritium"], day)
    session(ring, day, [30, 25, 20], 3, 30)
for day, ring in ((4, "Spot Sys 4 A Ring"), (5, "Spot Sys 5 A Ring")):
    ring_scan(ring, 10 + day, ["Bromellite"], day)
    session(ring, day, [10, 0, 0, 0, 0, 0, 12], 20, 10)
ring_scan("Spot Sys 6 A Ring", 16, ["Tritium", "Alexandrite"], 6)
dest(16)
lines = spot()
check(lines[0] == "SPOT  Tritium · 6 A Ring", "the ring of the target hotspot: %s" % lines[:1])
check(lines[1].startswith("      ") and "% good field · from 5 fields" in lines[1]
      and int(lines[1].split("%")[0]) >= 65, "a hotspot ring like the good ones: likely good - %s" % lines[1:2])
check(lines[2] == "      not mined here yet", "never mined there")
dest(14)
lines = spot()
check(lines[2].startswith("      you: poor · ") and ("prosp/good" in lines[2] or "no good rock" in lines[2]),
      "a field mined before: its rating - %s" % lines[2:3])
check(all(len(t) <= situation.LINE_MAX for t in lines), "every line within %d characters" % situation.LINE_MAX)
load.dashboard_entry("Cmdr", False, {"event": "Status", "timestamp": "2027-01-09T10:01:00Z", "Flags": 1 << 24})
check(not spot(), "no target: the SPOT item goes")
dest(11, name="$MULTIPLAYER_SCENARIO42_TITLE;", loc="Nav Beacon")
check(not spot(), "a target that is no ring hotspot: none")
check("spot" in cockpitinfo.GROUPS["place"] and situation.PRIORITY["spot"] < situation.PRIORITY["ring"],
      "a place item, above the ring's hotspot list")

print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
