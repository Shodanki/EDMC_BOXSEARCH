# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Ground mining in the Rhino (4.12, groundmine.py): rigs from the tonnes
collected, the Rhino's hold and the ship's (which takes the Rhino's load),
the smaller limit; the overlay block below the compass; a start in the
field read from the newest journal; the FIS with the same numbers.

The event pattern follows the developer's session of 14.11.2026: a 128 t
ship with 22 t of tritium, the Rhino out, rigs collected 1-2 s per tonne.

    python tests/ground_mining.py      (from the plugin folder)
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import groundmine, journal, maintenance, state, survey, surfacenav, uithread  # noqa: E402
from SHBOXSEARCH.overlay import CockpitOverlay  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


T0 = 1_800_000_000.0


def iso(t):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def session(srv_end=51):
    """(event, time) of a Rhino trip: rig 1 6 t, rig 2 12 t, rig 3 12 t
    right after (a full rig ends it), then 21 t in one run - a rig holds
    12 t at most, so that is rig 4 (12 t) and rig 5 (9 t)."""
    out = [({"event": "Loadout", "Ship": "explorer_nx", "CargoCapacity": 128}, T0),
           ({"event": "Cargo", "Vessel": "Ship", "Count": 22,
             "Inventory": [{"Name": "tritium", "Count": 22}]}, T0 + 3),
           ({"event": "LaunchSRV", "SRVType": "mev_rhino", "SRVType_Localised": "SRV Rhino"}, T0 + 60),
           ({"event": "Cargo", "Vessel": "SRV", "Count": 0}, T0 + 70)]
    t, n = T0 + 500, 0
    for rig in (6, 12, 12, srv_end - 30):
        for _ in range(rig):
            out.append(({"event": "MiningRefined", "Type": "$tritium_name;"}, t))
            n += 1
            t += 1.2
        out.append(({"event": "Cargo", "Vessel": "SRV", "Count": n}, t))
        t += 0 if rig == 12 and n == 18 else 300       # rig 3 follows rig 2 at once
    return out, t


print("the rigs and the two holds")
evs, t_end = session()
gm = groundmine.GroundMine().replay(evs)
check(gm.in_rhino and gm.rigs == [6, 12, 12, 12, 9], "rigs split by pause and by a full rig: %s" % gm.rigs)
check(groundmine.RIG_GAP_S == surfacenav.RIG_GAP_S, "the same rig pause as the surface map")
r = gm.room()
check((r["rhino_used"], r["rhino_free"], r["ship_free_after"]) == (51, 21, 55),
      "Rhino 51/72 -> 21 free; ship 128 - 22 - 51 = 55 free with the Rhino aboard")
check((r["room"], r["room_rigs"], r["limit"], r["short"]) == (21, 1, "rhino", False),
      "the Rhino is the limit: 21 t, one full rig")
last_tonne = max(ts for e, ts in evs if e["event"] == "MiningRefined")
g = gm.rig(last_tonne + 2)
check(gm.rig(t_end)["collecting"] is False, "five minutes after the last tonne: not collecting now")
check(g["n"] == 5 and g["t"] == 9 and g["trip_t"] == 51 and g["collecting"], "rig 5 being collected, 9 t, 51 t this trip")
gm.ship_cargo = 90
r = gm.room()
check((r["ship_free_after"], r["limit"], r["short"]) == (0, "ship", True),
      "ship nearly full (90 t): nothing more fits - the ship is the limit")
lines = [t for t, _c in gm.lines(t_end)]
check(any("SHIP full - make room" in ln for ln in lines), "the block says so: %s" % lines[-1])
gm.ship_cargo, gm.srv_cargo = 50, 30
r = gm.room()
check((r["room"], r["limit"], r["room_rigs"]) == (42, "rhino", 3),
      "Rhino 42 free, ship 48: the Rhino is the limit, 3 full rigs")
gm.ship_cargo = 70
r = gm.room()
lines = [t for t, _c in gm.lines(t_end)]
check((r["room"], r["limit"], r["room_rigs"]) == (28, "ship", 2) and any("LIMIT" in ln for ln in lines),
      "Rhino 42 free but ship only 28: 'LIMIT the ship: 28 t more (2 full rigs)'")
gm.status({"Flags": groundmine.SRV_FLAG, "Cargo": 33.0})
check(gm.srv_cargo == 33, "Status.json in the SRV: its Cargo is the Rhino's load")
gm.feed({"event": "DockSRV"}, t_end)
check(not gm.in_rhino and gm.rigs == [] and not gm.lines(t_end)[1:] == [], "back aboard: the trip ends")
scarab = groundmine.GroundMine()
scarab.feed({"event": "LaunchSRV", "SRVType": "testbuggy", "SRVType_Localised": "SRV Scarab"}, T0)
check(not scarab.in_rhino, "a Scarab is no Rhino")

print("the overlay: the ground block below the compass")


class Client:
    def __init__(self):
        self.sent = []

    def send_message(self, mid, text, colour, x, y, ttl=4, size="normal"):
        self.sent.append((mid, text, y))


client = Client()
ST = state.ST
ST.overlay = CockpitOverlay(client=client)
ST.ground = groundmine.GroundMine()
plugin_pkg.use_settings({})
for e, ts in evs:
    e = dict(e, timestamp=iso(ts))
    journal._mining_event(e["event"], e, {})
mine = [(m, t, y) for m, t, y in client.sent if m.startswith("shbox-mine-") and t]
check(mine and mine[-1][1].startswith("RHINO") or any(t.startswith("RHINO") for _m, t, _y in mine),
      "the ground block is drawn (%s)" % (mine[-1][1] if mine else None))
check(any(t.startswith("SHIP") for _m, t, _y in mine), "with the ship's line")
ST.overlay.draw("nav", [("NAV", "#fff"), ("SHIP 262 m", "#fff"), ("SRV 40 m", "#fff")], ttl=4)
y_nav_last = max(y for m, t, y in client.sent if m.startswith("shbox-nav-") and t)
journal._mining_overlay(force=True)
y_mine_first = min(y for m, t, y in client.sent[-6:] if m.startswith("shbox-mine-") and t)
check(y_mine_first > y_nav_last, "the block starts below the compass (y %d > %d)" % (y_mine_first, y_nav_last))

print("EDMC started while out in the Rhino")
jdir = tempfile.mkdtemp()
with open(os.path.join(jdir, "Journal.2027-01-15T080000.01.log"), "w", encoding="utf-8") as fh:
    for e, ts in evs:
        fh.write(json.dumps(dict(e, timestamp=iso(ts))) + "\n")
ST.ground = groundmine.GroundMine()
maintenance._journal_dir = lambda: jdir
uithread._ui = lambda fn: fn()
survey._bootstrap_ground()
check(ST.ground.in_rhino and ST.ground.rigs == [6, 12, 12, 12, 9] and ST.ground.ship_cargo == 22,
      "the trip so far read from the newest journal")

print("the ship's hold known even when the panel is not up yet")
docked = [(e, ts) for e, ts in evs if e["event"] != "LaunchSRV"][:2]       # Loadout + ship Cargo only
with open(os.path.join(jdir, "Journal.2027-01-15T090000.01.log"), "w", encoding="utf-8") as fh:
    for e, ts in docked:
        fh.write(json.dumps(dict(e, timestamp=iso(ts + 3600))) + "\n")
ST.ground = groundmine.GroundMine()
uithread._ui = lambda fn: None                    # as while EDMC builds its window: dropped
survey._bootstrap_ground()
check((ST.ground.ship_cargo, ST.ground.ship_capacity) == (22, 128),
      "taken over without the main-thread hand-over that drops calls before the panel exists")
unknown = groundmine.GroundMine()
unknown.feed({"event": "LaunchSRV", "SRVType": "mev_rhino"}, T0)
check(any(t.startswith("SHIP   hold not known") for t, _c in unknown.lines(T0)),
      "ship's hold unknown: the block says so instead of leaving the line out")
ran = []
uithread._run_async = lambda fn, label="": ran.append(fn)
ST.ground = groundmine.GroundMine()
journal._mining_event("LaunchSRV", {"event": "LaunchSRV", "SRVType": "mev_rhino", "timestamp": iso(T0)}, {})
check(ran == [survey._bootstrap_ground], "Rhino out without the ship's numbers: the journal is read again")
ran.clear()
ST.ground.ship_capacity, ST.ground.ship_cargo = 128, 22
journal._mining_event("LaunchSRV", {"event": "LaunchSRV", "SRVType": "mev_rhino", "timestamp": iso(T0)}, {})
check(ran == [], "numbers known: nothing read again")
ok_lines = ST.ground.lines(T0)
check(any(t.startswith("SHIP   106 t free") for t, _c in ok_lines)
      and [c for t, c in ok_lines if t.startswith("SHIP")][0] == [c for t, c in ok_lines if t.startswith("HOLD")][0],
      "the SHIP line as bright as HOLD when it is not the limit")

print("the FIS: the same numbers")
sys.path.insert(0, os.path.join(ROOT, "FIS"))
from fis import model, mining  # noqa: E402
model._plugin = None
sys.path.insert(0, ROOT)                     # the FIS finds the plugin's modules here
live = {"vehicle": "SRV Rhino", "status": {"cargo": 51, "flags": groundmine.SRV_FLAG}}
fis_evs = [dict(e, timestamp=iso(ts)) for e, ts in evs]
h = mining.rhino_hold(live, evs=fis_evs, now=t_end)
check(h and (h["free"], h["ship_free_after"], h["room"], h["limit"]) == (21, 55, 21, "rhino"),
      "FIS: Rhino 21 free, ship 55, limit the Rhino (%s)" % {k: h.get(k) for k in ("free", "ship_free_after")})
check(h["rig"]["n"] == 5 and h["rig"]["trip_t"] == 51, "FIS: rig 5, 51 t this trip")
check(mining.rhino_hold(live)["limit"] == "rhino" and "ship_free_after" not in mining.rhino_hold(live),
      "without the journal events: the Rhino alone, as before")

print("ground mining: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
