# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
A finished system and the in-system route (4.12, user 15.11.2026): with
nothing left to do the route shows the full tour (as before) - or, with
"show the full tour anyway" switched off, no route at all; "route every
body, always" routes every body whatever is done.

    python tests/route_done.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import panel, routewin, state, uithread  # noqa: E402
from SHBOXSEARCH.sysdb import CMDR_READY, SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


ST = state.ST
ST.db = SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
ST.db.set_meta(CMDR_READY, "test")
ST.db.set_commander("F1", "Cmdr")
cfg = {}
plugin_pkg.use_settings(cfg)
uithread._ui = lambda fn: None
ST.cur_id64, ST.cur_system = 77, "Done Sys"
T = "2027-01-15T08:%02d:00Z"
ST.db.ingest_journal_event({"event": "FSDJump", "timestamp": T % 0, "StarSystem": "Done Sys",
                            "SystemAddress": 77, "StarPos": [1.0, 2.0, 3.0]})
ST.db.ingest_journal_event({"event": "Scan", "timestamp": T % 1, "ScanType": "AutoScan", "StarSystem": "Done Sys",
                            "SystemAddress": 77, "BodyID": 0, "BodyName": "Done Sys", "StarType": "K",
                            "DistanceFromArrivalLS": 0.0, "WasDiscovered": True})
for i, ls in ((1, 400.0), (2, 900.0)):
    ST.db.ingest_journal_event({"event": "Scan", "timestamp": T % (1 + i), "ScanType": "Detailed",
                                "StarSystem": "Done Sys", "SystemAddress": 77, "BodyID": i,
                                "BodyName": "Done Sys %d" % i, "PlanetClass": "Icy body", "Landable": False,
                                "DistanceFromArrivalLS": ls, "WasDiscovered": True, "WasMapped": True,
                                "Parents": [{"Star": 0}]})
    ST.db.ingest_journal_event({"event": "SAAScanComplete", "timestamp": T % (5 + i), "SystemAddress": 77,
                                "BodyName": "Done Sys %d" % i, "BodyID": i, "ProbesUsed": 3,
                                "EfficiencyTarget": 4})
ST.db.ingest_journal_event({"event": "FSSAllBodiesFound", "timestamp": T % 9, "SystemName": "Done Sys",
                            "SystemAddress": 77, "Count": 3})

print("nothing left to do here")
routewin._rebuild_route()
check(ST.route is not None and ST.route.stops and ST.route_full,
      "by default: the full tour anyway (%d stops)" % (len(ST.route.stops) if ST.route else -1))
cfg[state.CFG["route_done_tour"]] = False
routewin._rebuild_route()
check(ST.route is not None and not ST.route.stops and not ST.route_full, "tour switched off: no route")
panel._v_route = type("V", (), {"set": lambda self, v: setattr(self, "v", v)})()
panel._lbl_route = None
panel._refresh_route_line()
check(getattr(panel._v_route, "v", "") == "in-system: all done here", "the panel says so: %s"
      % getattr(panel._v_route, "v", None))
cfg[state.CFG["route_all"]] = True
routewin._rebuild_route()
check(ST.route.stops and not ST.route_full, "route every body, always: the bodies all the same")

print("route done: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
