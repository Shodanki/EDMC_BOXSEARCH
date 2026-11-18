# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Life support off (5.0, R8, lifesupport.py): the game writes no event for
it - a replay of the developer's AFMU session of 18.11.2026 20:07-20:13
(DockSRV, Loadout, Touchdown, ModuleInfo, AfmuRepairs ...) with DANGER lit
in Status.json, and the sure cases from Loadout and ModulesInfo.json.

    python tests/life_support.py      (from the plugin folder)
"""
import calendar
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lifesupport as ls  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


def ts(hms):
    return float(calendar.timegm(time.strptime("2026-11-18T" + hms, "%Y-%m-%dT%H:%M:%S")))


IN_SHIP, LANDED, DANGER, DOCKED, OVERHEAT = 1 << 24, 1 << 1, 1 << 22, 1 << 0, 1 << 20
LS_ON = {"Slot": "LifeSupport", "Item": "int_lifesupport_size5_class2", "On": True, "Health": 1.0}
LOADOUT = {"event": "Loadout", "timestamp": "2026-11-18T20:07:37Z",
           "Modules": [LS_ON, {"Slot": "MainEngines", "Item": "int_engine_size7_class5", "On": False}]}
SESSION = [
    ("20:07:37", "Loadout", LOADOUT),
    ("20:08:42", "ModuleInfo", {}),
    ("20:09:15", "AfmuRepairs", {"Module": "$int_engine_size7_class5_gravityoptimised_mkii_name;"}),
    ("20:09:37", "AfmuRepairs", {"Module": "$int_shieldgenerator_size6_class2_name;"}),
    ("20:10:08", "AfmuRepairs", {"Module": "$int_fuelscoop_size5_class5_name;"}),
    ("20:10:30", "AfmuRepairs", {"Module": "$int_lifesupport_size5_class2_name;", "FullyRepaired": True}),
    ("20:11:02", "AfmuRepairs", {"Module": "$modularcargobaydoor_name;"}),
    ("20:13:13", "AfmuRepairs", {"Module": "$int_detailedsurfacescanner_tiny_name;"}),
]

print("replay 18.11. 20:07-20:13 (landed, DANGER lit, AFMU at work)")
w = ls.LifeSupportWatch()
seen = []
for hms, ev, e in SESSION:
    w.feed(ev, e, ts(hms))
    v, changed = w.check(IN_SHIP | LANDED | DANGER, ts(hms) + 1)
    if changed:
        seen.append((hms, v and v["state"]))
check(seen == [("20:08:42", "probable")],
      "probable from the ModuleInfo on: %s" % seen)
v, _ = w.check(IN_SHIP | LANDED | DANGER, ts("20:13:20"))
check(v == {"state": "probable", "why": "afmu"}, "still probable after the last repair")
check(ls.overlay_lines(v) == [("LIFE SUPPORT OFF?", ls.RED)], "overlay: red, with a question mark")
v, changed = w.check(IN_SHIP | LANDED, ts("20:14:00"))
check(v is None and changed, "DANGER gone (switched back on): off again")
v, _ = w.check(IN_SHIP | LANDED | DANGER | OVERHEAT, ts("20:14:10"))
check(v is None, "DANGER with heat: not blamed on life support")
v, _ = w.check(IN_SHIP | LANDED | DANGER, ts("22:40:00"))
check(v is None, "hours later DANGER (a hostile ship): no stale guess")
v, _ = w.check(DANGER | LANDED, ts("20:13:20"))
check(v is None, "not in the ship (on foot): no lamp")

print("sure cases")
off = dict(LOADOUT, Modules=[dict(LS_ON, On=False)])
check(ls.judge(IN_SHIP, off) == {"state": "off", "why": "loadout"}, "Loadout On:false - sure, no DANGER needed")
check(ls.judge(IN_SHIP, dict(LOADOUT, Modules=[dict(LS_ON, Health=0)]))["state"] == "off", "Loadout Health 0")
check(ls.judge(IN_SHIP | DOCKED, off) is None, "docked: the station keeps you alive")
info = {"timestamp": "2026-11-18T20:08:42Z", "Modules": [{"Slot": "LifeSupport", "Item": "int_lifesupport_size5_class2",
                                                          "Power": 0.0}]}
check(ls.judge(IN_SHIP, LOADOUT, info, (), 0, ts("20:07:37"), ts("20:08:42")) == {"state": "off", "why": "modules"},
      "ModulesInfo.json newer than the Loadout, power 0")
check(ls.judge(IN_SHIP, LOADOUT, info, (), 0, ts("20:09:00"), ts("20:08:42")) is None,
      "ModulesInfo.json older than the Loadout: not trusted")
info_on = {"Modules": [dict(info["Modules"][0], Power=0.64)]}
check(ls.judge(IN_SHIP, LOADOUT, info_on, (), 0, ts("20:07:37"), ts("20:08:42")) is None, "power 0.64: on")
check(ls.judge("x") is None and ls.judge(None) is None, "bad flags: nothing")
w.feed("LoadGame", {}, ts("21:00:00"))
check(w.loadout is None and not w.service, "a new game forgets")

print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
