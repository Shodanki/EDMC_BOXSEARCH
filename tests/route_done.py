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

print("bio found by the DSS keeps the stop open (test finding k-brain, 17.11.)")
cfg[state.CFG["route_all"]] = False
cfg[state.CFG["route_done_tour"]] = True
ST.cur_id64, ST.cur_system = 78, "Bio Sys"
B = "Bio Sys A 5"
ST.db.ingest_journal_event({"event": "FSDJump", "timestamp": T % 20, "StarSystem": "Bio Sys",
                            "SystemAddress": 78, "StarPos": [4.0, 5.0, 6.0]})
ST.db.ingest_journal_event({"event": "Scan", "timestamp": T % 21, "ScanType": "AutoScan", "StarSystem": "Bio Sys",
                            "SystemAddress": 78, "BodyID": 0, "BodyName": "Bio Sys", "StarType": "K",
                            "DistanceFromArrivalLS": 0.0, "WasDiscovered": True})
ST.db.ingest_journal_event({"event": "Scan", "timestamp": T % 22, "ScanType": "Detailed", "StarSystem": "Bio Sys",
                            "SystemAddress": 78, "BodyID": 11, "BodyName": B,
                            "PlanetClass": "High metal content body", "Landable": True,
                            "DistanceFromArrivalLS": 44.0, "WasDiscovered": True, "WasMapped": False,
                            "Parents": [{"Star": 0}]})
routewin._rebuild_route()
check(ST.route is not None and any(s.body.name == B for s in ST.route.stops), "the planet is a stop (DSS)")
# the game's order: SAAScanComplete, then SAASignalsFound in the same second
ST.db.ingest_journal_event({"event": "SAAScanComplete", "timestamp": T % 23, "SystemAddress": 78,
                            "BodyName": B, "BodyID": 11, "ProbesUsed": 4, "EfficiencyTarget": 6})
routewin._route_auto_tick(B, "mapped")
check(11 in ST.route_done, "mapped: ticked off while no bio is known yet")
ST.db.ingest_journal_event({"event": "SAASignalsFound", "timestamp": T % 23, "SystemAddress": 78,
                            "BodyName": B, "BodyID": 11,
                            "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 1}],
                            "Genuses": [{"Genus": "$Codex_Ent_Brancae_Name;", "Genus_Localised": "Brain Trees"}]})
routewin._route_reopen_bio(B)
check(11 not in ST.route_done, "the DSS found Brain Trees: the stop is back on the list")
check(not any(r["route_done"] for r in ST.db.bodies_of(78) if r["body_id"] == 11), "... and in the database")
routewin._rebuild_route()
from SHBOXSEARCH import overlay  # noqa: E402
lines = overlay.targets_lines(ST.route, ST.route_done)
row = [ln for ln in lines if "A 5" in ln[0] or B in ln[0]]
check(row and "BIO" in row[0][0] and row[0][1] == overlay.COL["warn"],
      "NEXT TARGETS shows it amber with BIO: %r" % (row,))
routewin._route_auto_tick(B, "approach")
check(11 not in ST.route_done, "approach and landing do not tick it off while bio is open")
ST.db.ingest_journal_event({"event": "ScanOrganic", "timestamp": T % 30, "ScanType": "Analyse",
                            "SystemAddress": 78, "Body": 11, "Genus": "$Codex_Ent_Brancae_Name;",
                            "Genus_Localised": "Brain Trees", "Species": "$Codex_Ent_Brancae_04_Name;",
                            "Species_Localised": "Ostrinum Brain Tree"})
# the game's form: ScanOrganic gives "Body" as the BodyID, a number (19.11.: B 2 in
# Synuefe AZ-K b27-1 was analysed at 18:37 and only ticked off at the next ApproachBody)
routewin._route_auto_tick(99, "sampled")
check(11 not in ST.route_done, "another body's id ticks nothing")
routewin._route_auto_tick(11, "sampled")
check(11 in ST.route_done, "the species analysed: ticked off right away, by its BodyID")

print("the first estimate after the FSS is kept (own-4)")
est = ST.db.cx.execute("SELECT * FROM route_estimates").fetchall()
check(not any(r["sys_id64"] == 78 for r in est), "FSS not complete: nothing kept yet")
routewin._rebuild_route()
check(ST.route_full and not ST.db.cx.execute("SELECT 1 FROM route_estimates WHERE sys_id64=78").fetchone(),
      "nothing left, the full tour shown: no estimate")
ST.db.ingest_journal_event({"event": "Scan", "timestamp": T % 39, "ScanType": "Detailed", "StarSystem": "Bio Sys",
                            "SystemAddress": 78, "BodyID": 12, "BodyName": "Bio Sys A 6",
                            "PlanetClass": "High metal content body", "Landable": True,
                            "DistanceFromArrivalLS": 60.0, "WasDiscovered": True, "WasMapped": False,
                            "Parents": [{"Star": 0}]})
ST.db.ingest_journal_event({"event": "FSSAllBodiesFound", "timestamp": T % 40, "SystemName": "Bio Sys",
                            "SystemAddress": 78, "Count": 3})
routewin._rebuild_route()
first = ST.db.cx.execute("SELECT * FROM route_estimates WHERE sys_id64=78").fetchone()
check(first is not None and first["fid"] == "F1" and first["stops"] >= 1 and first["total_s"] > 0,
      "FSS complete: kept (%s)" % (dict(first) if first else None))
ST.db.cx.execute("UPDATE route_estimates SET total_s=12345 WHERE sys_id64=78")
routewin._rebuild_route()
check(ST.db.cx.execute("SELECT total_s FROM route_estimates WHERE sys_id64=78").fetchone()[0] == 12345,
      "later routes do not replace it")

print("route done: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
