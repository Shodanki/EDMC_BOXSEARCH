# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Reality check from the command line (5.0, R4) - a developer tool, no
parameters: a scripted journal (mining with rocks and collector waves) and
fixed model figures go through the same functions the FIS uses for
STATISTICS > LEARNING STATUS (FIS/fis/realitycheck.py, the plugin's
miningstat.RockYield, FIS mining.collector_waves). It prints the table and
fails when a row is missing, wrongly judged or the shape changed.

    python tests/realitycheck.py      (from the plugin folder)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "FIS"))
import miningstat  # noqa: E402
from fis import mining, realitycheck  # noqa: E402

fails = 0
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")      # "·" on a Windows console


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


def stamp(i):
    return "2026-11-10T%02d:%02d:%02dZ" % (8 + i // 3600, i // 60 % 60, i % 60)


def journal():
    """Two mining runs: rocks of 5 % platinum giving 4-6 t, and collector
    waves of about five minutes (launched, collecting, done)."""
    evs, t = [], 0

    def add(ev, **kw):
        nonlocal t
        t += 20
        evs.append(dict({"timestamp": stamp(t), "event": ev}, **kw))
    add("Loadout", Ship="python",
        Modules=[{"Slot": "Slot01_Size5", "Item": "int_dronecontrol_collection_size5_class5"}])
    for run in range(2):
        add("SupercruiseExit", Body="Belt A")
        for tonnes in (4, 5, 6, 5, 4, 5, 6, 5):
            add("LaunchDrone", Type="Prospector")
            add("ProspectedAsteroid", Materials=[{"Name": "Platinum", "Proportion": 5.0}],
                Content="$AsteroidMaterialContent_Medium;")
            add("LaunchDrone", Type="Collection")
            for _ in range(tonnes):
                add("MiningRefined", Type="$platinum_name;")
        add("SupercruiseEntry")
    return evs


FIXED = {"kepler": {"ok_pct": 95.8, "checked": 2106, "systems": 202, "moons_checked": 40, "moons_ok_pct": 92.5},
         "fuel": {"median_pct": 0.8, "p90_pct": 10.1, "n": 646},
         "route": {"ratio": 1.1, "ratio_n": 12},
         "work": {"dss_s": 224, "bio_s": 172, "dss_n": 300, "bio_n": 171},
         "value": {"factor": 0.91, "lo": 0.75, "hi": 1.29, "n": 12},
         "finds": {"gap_pp": 1.5, "n": 100},
         "bio": {"bodies": 104, "recall_top3": 0.76, "top1_right": 0.88}}

print("reality check over a scripted journal and fixed model figures")
evs = journal()
parts = dict(FIXED)
parts["rocks"] = realitycheck.rock_yield(evs, miningstat.RockYield)
parts["collectors"] = realitycheck.collectors(mining.collector_waves(evs))
rows = realitycheck.build(parts)
w = max(len(r["label"]) for r in rows)
for r in rows:
    mark = {True: "ok", False: "off", None: "thin"}[r["good"]]
    n = " · n %d" % r["n"] if r["n"] else ""
    print("    %-*s  %-5s %s%s" % (w, r["label"], mark, r["value"] or "no data yet", n))
keys = [r["key"] for r in rows]
check(keys == ["kepler", "kepler_moons", "fuel", "route", "work", "value", "finds", "bio", "scoop", "rocks", "collectors"],
      "every model has its row, in order: %s" % ", ".join(keys))
check(all(set(r) >= {"key", "label", "value", "n", "good"} for r in rows), "rows keep their shape")
by = {r["key"]: r for r in rows}
check(parts["rocks"] and parts["rocks"]["n"] == 11, "rocks judged by the ones before: %s" % parts["rocks"])
check(by["rocks"]["good"] is True, "steady rocks: tonnes per rock ok")
check(all(by[k]["good"] is True for k in list(FIXED) + ["kepler_moons"]), "fixed figures all within their bars")
check(by["collectors"]["value"] is None or by["collectors"]["good"] in (True, None),
      "collectors: judged or thin, never wrong on steady waves")
bad = realitycheck.build(dict(FIXED, route={"ratio": 2.1, "ratio_n": 12}))
check({r["key"]: r for r in bad}["route"]["good"] is False, "twice the route estimate is flagged")
print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
