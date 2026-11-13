# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Plugin hook test (E20, 5.0): load.journal_entry() against a scripted session
- no network, no EDMC (its modules are stubbed), no window. It pins down what
the journal dispatch does today, so load.py can be split up (H6) without
changing behaviour:

  position after FSDJump / Location, fuel per jump, Loadout, plotted route,
  DSS and sampling timings, the own carrier after a carrier jump, a second
  commander, the target briefing, Status.json (fuel, selected destination),
  survey start (free / carrier), queue pruning after a jump or a target
  selection, sphere end and overlap,
  and that a broken event never escapes the hook.

    python tests/plugin_hooks.py      (from the plugin folder)
"""
import os
import sys
import tempfile
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

import load  # noqa: E402
from sysdb import SystemDB  # noqa: E402
from boxelplan import Planner  # noqa: E402

cfg = {}
load.cfg_bool = lambda k, d=False: cfg.get(k, d)
load.cfg_int = lambda k, d=0: d
load.cfg_str = lambda k, d="": cfg.get(k, d)
load._set_status = lambda m: None
load._ui = lambda f, *a, **k: None
calls = []
for name in ("_request_route", "_maybe_extend", "_update_route_targets",
             "_maybe_route_check", "_recheck_route", "_route_auto_tick"):
    setattr(load, name, (lambda n: lambda *a, **k: calls.append(n))(name))
load._overlay_briefing = lambda kind, *a, **k: calls.append("briefing " + kind)
load._run_async = lambda fn, *a, label="", **kw: calls.append("async " + label)
ST = load.ST
ST.overlay = None

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


NOW = [1_800_000_000.0]
load.time.time = lambda: NOW[0]          # load.py and sysdb share the time module


def je(entry, cmdr="Tester", state=None):
    entry.setdefault("timestamp", "2026-11-13T01:00:00Z")
    load.journal_entry(cmdr, False, "", "", entry, state if state is not None else {"FID": "F1"})


try:
    with tempfile.TemporaryDirectory() as d:
        ST.db = SystemDB(os.path.join(d, "t.sqlite"))
        ST.active = False

        # 1) Location, then a jump with fuel
        je({"event": "Location", "StarSystem": "Hook A", "SystemAddress": 1001,
            "StarPos": [1.0, 2.0, 3.0]})
        check(ST.cur_system == "Hook A" and ST.cur_id64 == 1001 and ST.cur_pos == (1.0, 2.0, 3.0),
              "Location sets system, id64 and position")
        check(ST.cmdr == "Tester" and ST.db.fid == "F1", "commander and FID taken from the hook")
        je({"event": "Loadout", "ShipID": 7, "MaxJumpRange": 61.5,
            "FuelCapacity": {"Main": 32.0, "Reserve": 0.6}})
        check(ST.max_jump == 61.5 and ST.fuel.capacity == 32.0, "Loadout: jump range and tank")
        calls.clear()
        NOW[0] += 60
        je({"event": "FSDJump", "StarSystem": "Hook B", "SystemAddress": 1002,
            "StarPos": [40.0, 2.0, 3.0], "StarClass": "K", "JumpDist": 39.0,
            "FuelUsed": 4.2, "FuelLevel": 27.8})
        check(ST.cur_system == "Hook B" and ST.cur_pos == (40.0, 2.0, 3.0), "FSDJump moves us")
        check(ST.fuel.level == 27.8, "FSDJump: fuel level kept")
        check("briefing arrival" in calls and "_request_route" in calls,
              "FSDJump: arrival briefing and a route request")
        check(ST.db.system("Hook B") is not None, "FSDJump stored in the database")

        # 2) plotted route
        je({"event": "NavRoute", "Route": [
            {"StarSystem": "Hook B", "StarClass": "K", "StarPos": [40.0, 2.0, 3.0]},
            {"StarSystem": "Hook C", "StarClass": "M", "StarPos": [80.0, 2.0, 3.0]}]})
        check([h[0] for h in ST.navroute] == ["Hook B", "Hook C"], "NavRoute kept as hops")
        je({"event": "NavRouteClear"})
        check(ST.navroute == [], "NavRouteClear empties it")

        # 3) DSS timing: ApproachBody ... SAAScanComplete (was never started up to 4.9)
        ST.work_dss.clear()
        je({"event": "ApproachBody", "StarSystem": "Hook B", "SystemAddress": 1002,
            "Body": "Hook B 1", "BodyID": 1})
        NOW[0] += 95
        je({"event": "SAAScanComplete", "BodyName": "Hook B 1", "BodyID": 1,
            "SystemAddress": 1002, "ProbesUsed": 5, "EfficiencyTarget": 6})
        check(ST.work_dss == [95.0], "DSS timed from ApproachBody to SAAScanComplete")
        je({"event": "SAAScanComplete", "BodyName": "Hook B 2", "BodyID": 2,
            "SystemAddress": 1002, "ProbesUsed": 5, "EfficiencyTarget": 6})
        check(ST.work_dss == [95.0], "no approach seen -> no timing")
        NOW[0] += 30
        je({"event": "SupercruiseExit", "StarSystem": "Hook B", "SystemAddress": 1002,
            "Body": "Hook B 3", "BodyID": 3, "BodyType": "Planet"})
        NOW[0] += 70
        je({"event": "SAAScanComplete", "BodyName": "Hook B 3", "BodyID": 3,
            "SystemAddress": 1002, "ProbesUsed": 4, "EfficiencyTarget": 6})
        check(ST.work_dss == [95.0, 70.0],
              "live like the replay: SupercruiseExit at the body starts the timing too")
        NOW[0] += 200
        je({"event": "SAAScanComplete", "BodyName": "Hook B 4", "BodyID": 4,
            "SystemAddress": 1002, "ProbesUsed": 6, "EfficiencyTarget": 6})
        check(ST.work_dss == [95.0, 70.0, 200.0],
              "live like the replay: no arrival -> the gap since the last mapping")

        # 4) sampling timing: Log ... Analyse of one species
        ST.work_bio.clear()
        org = {"event": "ScanOrganic", "SystemAddress": 1002, "Body": 1,
               "Genus": "$Codex_Ent_Bacterial_Genus_Name;",
               "Species": "$Codex_Ent_Bacterial_01_Name;"}
        je(dict(org, ScanType="Log"))
        NOW[0] += 300
        je(dict(org, ScanType="Sample"))
        NOW[0] += 200
        je(dict(org, ScanType="Analyse"))
        check(ST.work_bio == [500.0], "sampling timed from Log to Analyse")

        # 5) own carrier: CarrierLocation, then a jump aboard it
        je({"event": "CarrierLocation", "CarrierType": "FleetCarrier", "CarrierID": 3700000001,
            "StarSystem": "Hook B", "SystemAddress": 1002, "BodyID": 0})
        check(ST.carrier and ST.carrier["system"] == "Hook B", "CarrierLocation: own carrier")
        NOW[0] += 900
        je({"event": "CarrierJump", "Docked": True, "StationType": "FleetCarrier",
            "MarketID": 3700000001, "StarSystem": "Hook D", "SystemAddress": 1004,
            "StarPos": [200.0, 0.0, 0.0], "Body": "Hook D", "BodyID": 0, "BodyType": "Star"})
        check(ST.cur_system == "Hook D", "CarrierJump moves us")
        check(ST.carrier and ST.carrier["system"] == "Hook D",
              "CarrierJump aboard the own carrier moves the carrier (was stale up to 4.9)")

        # 6) a broken event never escapes the hook
        try:
            je({"event": "FSDJump", "StarSystem": "Hook E", "SystemAddress": 1005,
                "StarPos": "garbage", "FuelUsed": "x", "JumpDist": None})
            ok = True
        except Exception:
            ok = False
        check(ok, "a malformed event does not raise out of journal_entry")

        # 6b) briefing (what the overlay shows before a jump), own data only
        calls.clear()
        je({"event": "FSDTarget", "Name": "Hook B", "SystemAddress": 1002, "StarClass": "K"})
        check("briefing target" in calls, "FSDTarget asks for a target briefing")
        bi = load._briefing_info("target", "Hook B", 1002, "K")
        check(bi.get("visited") and bi.get("scoopable") and bi["level"] == "unchecked"
              and bi["known_sources"] == [],
              "briefing: Hook B visited, scoopable, in no data frame (no source asked)")
        bi = load._briefing_info("target", "Nowhere Q", None, "Y")
        check(not bi.get("visited") and bi.get("scoopable") is False and bi["level"] == "unchecked",
              "briefing: unknown brown dwarf - not scoopable, not visited")

        # 6c) Status.json: fuel and a selected destination (id64 in no database)
        load.dashboard_entry("Tester", False, {"Flags": 0, "Fuel": {"FuelMain": 21.5}})
        check(ST.fuel.level == 21.5, "Status.json: fuel level")
        dest = {"Flags": 0, "Destination": {"System": 422810994947, "Body": 0,
                                            "Name": "Synuefe XV-C d12"}}
        load.dashboard_entry("Tester", False, dest)
        row = ST.db.system_by_id64(422810994947)
        check(row is not None and row["name"] == "Synuefe XV-C d12",
              "Status.json: the selected destination is stored with its id64")
        seen = []
        real = ST.db.ingest_status_destination
        ST.db.ingest_status_destination = lambda d: seen.append(d) or real(d)
        load.dashboard_entry("Tester", False, dest)
        ST.db.ingest_status_destination = real
        check(seen == [], "the same destination again is not looked at twice")

        # 6d) survey start / queue pruning / sphere end (offline: no request)
        status = []
        load._set_status = status.append
        je({"event": "Location", "StarSystem": "Hook D", "SystemAddress": 1004,
            "StarPos": [200.0, 0.0, 0.0]})     # step 6 left a garbage position behind
        ST.planner = Planner(ST.db)
        ST.net.offline = True
        load._radius_var = mock.Mock(get=lambda: "40")
        load._carrier_var = mock.Mock(get=lambda: 1)
        ST.carrier = None
        calls.clear()
        load._start_survey()
        check(not ST.active and status[-1:] == ["no carrier position known - dock at it once"]
              and "async starting survey" not in calls,
              "carrier start without a carrier position: refused, nothing started")
        load._carrier_var = mock.Mock(get=lambda: 0)
        load._start_survey()
        check(ST.active and ST.center == ST.cur_pos and ST.radius == 40.0
              and ST.start_system == ST.cur_system and "async starting survey" in calls,
              "free start: sphere around the current system, worker started")
        sp = ST.db.list_spheres()
        check(len(sp) == 1 and sp[0]["origin"] == "free" and sp[0]["closed"] is None
              and ST.sphere_id == sp[0]["id"], "free start: sphere recorded, still open")
        sv = ST.db.load_survey()
        check(sv["active"] == 1 and sv["radius"] == 40.0, "free start: survey saved as active")
        first_id = ST.sphere_id
        load._start_survey()
        check(ST.sphere_id == first_id and len(ST.db.list_spheres()) == 1,
              "the same sphere started again is not recorded twice")
        status.clear()
        load._start_worker()
        check(ST.horizon == ST.radius and ST.plan_info,
              "offline worker: horizon = sphere, a plan from local data")
        # pruning: a new system flown to is dropped, a probe that now exists too
        here = ST.cur_pos
        ST.flight = [load.Target("Hook P", load.K_NEW, 5.0, pos=(here[0] + 5, here[1], here[2])),
                     load.Target("Hook Q", load.K_NEW, 9.0, pos=(here[0] + 9, here[1], here[2]))]
        ST.probe = [load.Target("Hook Probe AB-C d1", load.K_PROBE, 7.0, mc=3)]
        je({"event": "FSDJump", "StarSystem": "Hook P", "SystemAddress": 1016,
            "StarPos": [here[0] + 5, here[1], here[2]], "StarClass": "G", "JumpDist": 5.0},
           cmdr="Tester")
        check([t.name for t in ST.flight] == ["Hook Q"],
              "FSDJump to a flight target: it leaves the queue, the next stays")
        check([t.name for t in ST.probe] == ["Hook Probe AB-C d1"],
              "unknown probe stays in the queue")
        load.dashboard_entry("Tester", False, {"Flags": 0, "Destination": {
            "System": 7268024264082, "Body": 0, "Name": "Hook Probe AB-C d1"}})
        check(ST.probe == [], "probe confirmed by the target selection: dropped")
        # sphere end: closed only when the plan says finished
        ST.stats = {}
        load._stop_survey()
        check(not ST.active and ST.db.list_spheres()[0]["closed"] is None
              and ST.flight == [] and ST.probe == [],
              "stop with work left: sphere stays open, queues empty")
        check(ST.db.load_survey()["active"] == 0, "stop: survey saved as inactive")
        load._start_survey()
        ST.stats = {"finished": True}
        load._stop_survey()
        closed = {r["id"]: r["closed"] for r in ST.db.list_spheres()}
        check(len(closed) == 2 and closed[ST.sphere_id] is not None and closed[first_id] is None,
              "stop of a finished sphere: that one closed in the history, the first still open")
        status.clear()
        load._carrier_var = mock.Mock(get=lambda: 0)
        load._start_survey()
        check(any(s.startswith("overlap 100%") for s in status),
              "start on an earlier sphere: the overlap is reported (%r)" % status[:1])
        load._stop_survey()
        ST.net.offline = False
        load._set_status = lambda m: None

        # 7) a second commander: nothing of the first one's position is kept
        je({"event": "LoadGame", "Commander": "Other"}, cmdr="Other", state={"FID": "F2"})
        check(ST.cmdr == "Other" and ST.db.fid == "F2", "second commander taken over")
        check(ST.cur_system is None and ST.cur_id64 is None and ST.awaiting_position,
              "switch: position dropped, waiting for the new commander's")
        je({"event": "Location", "StarSystem": "Hook Z", "SystemAddress": 1026,
            "StarPos": [0.0, 0.0, 9.0]}, cmdr="Other", state={"FID": "F2"})
        check(ST.cur_system == "Hook Z" and not ST.awaiting_position,
              "the new commander's Location sets the system again")
        ST.db.cx.close()
        ST.db = None
except Exception:
    import traceback
    traceback.print_exc()
    fails += 1

print("plugin hooks: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
