# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
EDSM by name (4.12, H3 #5): probe candidates EDSM knows - some only by their
name, without a position. Those become flight targets at the centre of their
boxel ("existence confirmed"); the request is one bundle, never repeated for
a name within 14 days, and never sent while EDSM is switched off.

    python tests/edsm_names.py      (from the plugin folder; no network)
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import planning, state  # noqa: E402
from SHBOXSEARCH.boxelplan import K_GAP, Target  # noqa: E402
from SHBOXSEARCH.procgen import decode_id64, id64_of_slot, boxel_index_of_coords, make_name  # noqa: E402
from SHBOXSEARCH.procgen import computed_sector_name  # noqa: E402
from SHBOXSEARCH.sysdb import Q_CONFIRMED, SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


cfg = {}
plugin_pkg.use_settings(cfg)
ST = state.ST

# a real boxel near Sol, mass code d (3): names and id64s from the same maths
MC = 3
gidx = boxel_index_of_coords(30.0, 5.0, 40.0, MC)
per = 128 >> MC
sector_idx = tuple(g // per for g in gidx)
sector = computed_sector_name(sector_idx)
boxel = tuple(g % per for g in gidx)


def cand(n2):
    nm = make_name(sector, MC, boxel, n2)
    return Target(nm, K_GAP, 10.0, mc=MC, boxel_key=None, n2=n2, pos=(30.0, 5.0, 40.0),
                  id64=id64_of_slot(MC, gidx, n2))


probe = [cand(n) for n in range(1, 46)]           # 45 candidates: one request takes 40
asked = []


class FakeEDSM:
    name = "EDSM"
    answer = "normal"

    def lookup(self, names, endpoint="systems"):
        asked.append(list(names))
        FakeEDSM.endpoint = endpoint
        if FakeEDSM.answer == "none":
            return None                              # not asked: offline, cap, rest
        out = {probe[2].name.lower(): {"name": probe[2].name, "id64": probe[2].id64, "source": "EDSM"},
               probe[5].name.lower(): {"name": probe[5].name, "id64": probe[5].id64, "source": "EDSM",
                                       "x": 31.0, "y": 5.5, "z": 41.0}}
        return {k: v for k, v in out.items() if v["name"] in names}


class FakeSources:
    sources = {"edsm": FakeEDSM()}


planning._log_net = lambda *a: None
planning._flush_net_log = lambda: []

with tempfile.TemporaryDirectory() as d:
    ST.db = SystemDB(os.path.join(d, "t.sqlite"))
    ST.sources = FakeSources()
    print("switched off / not asked")
    cfg[state.CFG["src_edsm"]] = False
    check(planning._edsm_names(probe) == 0 and asked == [], "EDSM switched off: nothing asked")
    cfg[state.CFG["src_edsm"]] = True
    FakeEDSM.answer = "none"
    check(planning._edsm_names(probe) == 0 and len(asked) == 1, "no answer (offline, cap): nothing stored")
    check(ST.db.edsm_names_asked() == set(), "and nothing marked - asked again later")
    FakeEDSM.answer = "normal"
    asked.clear()
    print("one bundled request")
    n = planning._edsm_names(probe)
    check(n == 2 and len(asked) == 1 and len(asked[0]) == 40, "40 names in one request, 2 known (%r)" % n)
    row = ST.db.system(probe[2].name)
    centre = decode_id64(probe[2].id64)["center"]
    check(row is not None and row["quality"] == Q_CONFIRMED and math.dist((row["x"], row["y"], row["z"]), centre) < 1e-6,
          "known by name only: existence confirmed, at the boxel centre")
    check("EDSM" in (row["sources"] or ""), "source EDSM (the briefing says where it is known)")
    row5 = ST.db.system(probe[5].name)
    check(row5 is not None and (row5["x"], row5["z"]) == (31.0, 41.0), "known with a position: stored with it")
    check(any(r["name"] == probe[2].name and not r["visited"] for r in ST.db.sphere((30.0, 5.0, 40.0), 60.0)),
          "the name-only system is in the sphere, unvisited - the planner makes it a flight target")
    print("never twice")
    asked.clear()
    planning._edsm_names(probe)
    check(len(asked) == 1 and asked[0] == [t.name for t in probe[40:]],
          "the next request asks only the 5 names not asked yet")
    asked.clear()
    check(planning._edsm_names(probe) == 0 and asked == [], "all asked within 14 days: no request")
    check(FakeEDSM.endpoint == "systems/names", "its own label in the call log")
    print("a budget of its own: 10 of EDSM's 50 a day")
    import time as _t
    ST.db.cx.execute("DELETE FROM edsm_names")
    ST.db.cx.executemany("INSERT INTO external_calls(ts, service, endpoint, status, ok, ms) VALUES (?,?,?,?,?,?)",
                         [(_t.time(), "edsm", "systems/names", 200, 1, 50)] * 10)
    ST.db.cx.commit()
    asked.clear()
    check(planning._edsm_names(probe) == 0 and asked == [], "10 name requests today: no 11th")
    ST.db.cx.execute("UPDATE external_calls SET ts = ts - 86400")
    ST.db.cx.commit()
    check(planning._edsm_names(probe) > 0 and len(asked) == 1, "the next UTC day: asked again")
    ST.db.cx.close()
    ST.db = None

print("edsm names: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
