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
  commander, and that a broken event never escapes the hook.

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

cfg = {}
load.cfg_bool = lambda k, d=False: cfg.get(k, d)
load.cfg_int = lambda k, d=0: d
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
