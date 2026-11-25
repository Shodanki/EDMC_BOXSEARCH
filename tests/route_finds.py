# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
F5 (5.1.0): a plotted route checked in passing - after the route check
(EDDiscovery locally, then one EDSM request) the ROUTE item says how many
hops no database knows, a first discovery possible at no extra flight;
within 44 characters, nothing when every hop is known.

    python tests/route_finds.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import cockpitinfo, shells, situation, state  # noqa: E402
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
hops = [("Start", "K", (0.0, 0.0, 0.0)), ("Known One", "M", (10.0, 0.0, 0.0)),
        ("Blank Two", "F", (20.0, 0.0, 0.0)), ("Blank Three", "G", (30.0, 0.0, 0.0))]
BLANK = {"Blank Two", "Blank Three"}
for name, _c, pos in hops:
    ST.db.upsert(name, *pos, source="navroute")
real = shells.info_level
shells.info_level = lambda srcs, pos=None, regions=None, **kw: (
    ("checked", []) if pos and pos[0] >= 20 else ("known", []))

print("the route item")
cockpitinfo.route_finds(hops)
it = cockpitinfo.BOARD.items.get("route")
lines = [t for t, _c in it[1]] if it else []
check(lines and lines[0].startswith("ROUTE  3 jumps"), "the ROUTE head: %s" % lines[:1])
check("      2 of 3 in no database: first finds" in lines, "two hops in no database: %s" % lines)
check(all(len(t) <= situation.LINE_MAX for t in lines), "within 44 characters")
check(it and it[1][-1][1] == situation.COL["new"], "in the colour of a first discovery")

print("all known")
cockpitinfo.BOARD.drop("route")
shells.info_level = lambda srcs, pos=None, regions=None, **kw: ("known", [])
cockpitinfo.route_finds(hops)
check("route" not in cockpitinfo.BOARD.items, "every hop known: nothing added")
check(situation.route_find_line(0, 5) == [] and situation.route_find_line(1, 0) == [], "nothing to say: no line")
shells.info_level = real

print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
