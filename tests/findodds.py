# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
FX3 (5.0): the chance of a find (findodds) and its V0 loop (findlog): the
counting leans on broader cells, the first arrival keeps one prediction
from what was known before (not spoilt by the arrival star's scan that
follows the jump), a revisit keeps none, and the calibration sets the kept
predictions against what the scans showed.

    python tests/findodds.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import findlog, findodds, state  # noqa: E402
from SHBOXSEARCH.procgen import MASSCODES, parse_name  # noqa: E402
from SHBOXSEARCH.sysdb import CMDR_READY, SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


print("mass code and star groups")
for n in ("Synuefe WD-G b44-0", "Synuefe XT-Q c21-13", "Pyroifoo AA-A h0", "Col 285 Sector AB-C d1-23",
          "Eol Prou RS-T d3-94", "Shinrarta Dezhra", "HIP 22961", "Sol", "Wregoe ZE-B c28-0", ""):
    p = parse_name(n)
    want = MASSCODES[p.mc] if p else "named"
    check(findodds.kind_of(n) == want, "%r -> %s (procgen says %s)" % (n, findodds.kind_of(n), want))
for sc, g in (("M", "M"), ("K", "K"), ("G", "FG"), ("F", "FG"), ("B", "OBA"), ("A", "OBA"), ("T", "LTY"),
              ("Y", "LTY"), ("TTS", "rest"), ("DA", "rest"), ("N", "rest"), ("MS", "rest"), (None, "")):
    check(findodds.star_group(sc) == g, "star %r -> %s" % (sc, g))

print("counting leans on broader cells")
empty = findodds.FindOdds()
p0 = empty.predict("Synuefe WD-G b44-0", "M", "unchecked")
check(abs(p0["p"] - findodds.PRIOR["pg"]) < 1e-9 and p0["n"] == 0 and p0["why"] == "prior",
      "no data: the prior %.2f (got %.3f, %s)" % (findodds.PRIOR["pg"], p0["p"], p0["why"]))
check(p0["low"] <= p0["p"] <= p0["high"], "the range holds the chance")
named = empty.predict("Shinrarta Dezhra", "K", "inhabited")
check(abs(named["p"] - findodds.PRIOR["named"]) < 1e-9, "named systems have their own prior")
m = findodds.FindOdds()
for i in range(40):                       # b + M pays one in two, everything else never
    m.add("b", "M", "", i % 2 == 0)
    m.add("c", "T", "", False)
pb = m.predict("Synuefe WD-G b44-0", "M")
pc = m.predict("Synuefe XT-Q c21-13", "T")
check(0.35 < pb["p"] < 0.55 and pb["n"] == 40, "b/M learnt from 40: %.2f" % pb["p"])
check(pc["p"] < 0.05, "c/T never paid: %.3f" % pc["p"])
check(pb["learnt"] == 80, "learnt from all 80 visits")
pk = m.predict("Synuefe GV-D b45-4", "K")
check(0.2 < pk["p"] < pb["p"] and pk["why"] == "pg/?/b",
      "b/K without data leans on b: %.2f (%s)" % (pk["p"], pk["why"]))
lv = m.predict("Synuefe WD-G b44-0", "M", "checked")
check(abs(lv["p"] - pb["p"]) < 1e-9, "a level without data changes nothing")
check(pb["high"] - pb["low"] < p0["high"] - p0["low"], "more data, narrower range")
hm = findodds.FindOdds()
for i in range(60):                       # above the plane one in four, near it never
    hm.add("c", "K", "", i % 4 == 0, "high")
    hm.add("c", "K", "", False, "low")
hi_, lo_ = hm.predict("Synuefe XT-Q c21-13", "K", "", 250.0), hm.predict("Synuefe XT-Q c21-13", "K", "", -40.0)
check(hi_["height"] == "high" and lo_["height"] == "low" and hi_["p"] > 0.18 > 0.03 > lo_["p"],
      "height splits: above %.2f, near the plane %.3f" % (hi_["p"], lo_["p"]))
nb = hm.predict("Synuefe GV-D b45-4", "M", "", 300.0)
check(0.1 < nb["p"] < hi_["p"] and nb["why"] == "pg/high", "b/M above the plane leans on 'high': %.2f (%s)"
      % (nb["p"], nb["why"]))
check(findodds.height_band(None) == "?" and findodds.height_band(-100.0) == "high", "height bands")

print("V0: the first arrival keeps one prediction")
ST = state.ST
ST.db = SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
ST.db.set_meta(CMDR_READY, "test")
ST.db.set_commander("F1", "Cmdr")
T = "2027-01-15T08:%02d:00Z"


def jump(minute, name, sid, pos, star="M"):
    e = {"event": "FSDJump", "timestamp": T % minute, "StarSystem": name, "SystemAddress": sid,
         "StarPos": list(pos), "StarClass": star}
    ST.db.ingest_journal_event(e)
    return e


def scan(minute, name, sid, body, discovered, ls=0.0):
    ST.db.ingest_journal_event({"event": "Scan", "timestamp": T % minute, "ScanType": "AutoScan",
                                "StarSystem": name, "SystemAddress": sid, "BodyID": body,
                                "BodyName": name if not body else "%s %d" % (name, body), "StarType": "M",
                                "DistanceFromArrivalLS": ls, "WasDiscovered": discovered})


def all_found(minute, name, sid, count):
    ST.db.ingest_journal_event({"event": "FSSAllBodiesFound", "timestamp": T % minute, "SystemName": name,
                                "SystemAddress": sid, "Count": count})


A, B = "Synuefe WD-G b44-0", "Synuefe GV-D b45-4"
started = []
findlog.threading = type("T", (), {"Thread": lambda **kw: started.append(kw) or type(
    "X", (), {"start": lambda self: None})()})
e = jump(0, A, 101, (500.0, -140.0, -115.0))
findlog.on_jump(e)
check(len(started) == 1, "first arrival: the prediction goes to a worker thread")
scan(1, A, 101, 0, True)                  # the arrival star's scan lands before the worker runs
pred = findlog.keep_prediction(started[0]["args"][0])
row = ST.db.cx.execute("SELECT * FROM find_log WHERE sys_id64=101").fetchone()
check(pred is not None and row is not None, "kept although the arrival star was scanned meanwhile")
check(row is not None and row["kind"] == "b" and row["star"] == "M" and row["level"] == "unchecked"
      and row["height"] == "high", "kind b, star M, level unchecked (no database asked), above the plane")
check(row is not None and abs(row["p"] - findodds.PRIOR["pg"]) < 1e-9, "nothing learnt yet: the prior")
scan(2, A, 101, 1, False, 500.0)          # a find
all_found(3, A, 101, 2)
check(findlog.keep_prediction(started[0]["args"][0]) is None, "a second prediction for A is not kept")
started.clear()
findlog.on_jump(jump(4, A, 101, (500.0, -140.0, -115.0)))
check(not started, "a revisit (own scans there) predicts nothing")
findlog.on_jump(jump(5, B, 102, (505.0, -200.0, -103.0)))
pb = findlog.keep_prediction(started[0]["args"][0])
check(pb is not None and pb["learnt"] == 1 and pb["p"] > findodds.PRIOR["pg"],
      "B learns from A's find: %.2f from %s visit" % (pb["p"] if pb else -1, pb["learnt"] if pb else "?"))
scan(6, B, 102, 0, True)

print("calibration: predictions against scans")
q = lambda s, a: ST.db.cx.execute(s, a).fetchall()  # noqa: E731
cal = findodds.calibration(q)
check(cal["logged"] == 2 and cal["waiting"] == 1, "2 kept, B waits for a completed FSS (%s)" % cal)
b1 = cal["bands"][findodds.band(findodds.PRIOR["pg"])]
check(b1["n"] == 1 and b1["hits"] == 1 and b1["rate"] == 1.0, "A's band: 1 of 1 found")
check(cal["learnt"] == 1 and cal["base"].get("pg") == {"n": 1, "hits": 1}, "base: procgen 1 of 1")
all_found(7, B, 102, 1)
cal = findodds.calibration(q)
check(cal["waiting"] == 0 and cal["learnt"] == 2, "B settled without a find")
check(sum(b["n"] for b in cal["bands"]) == 2, "both in the bands")
check(findodds.calibration(lambda s, a: (_ for _ in ()).throw(RuntimeError("no table")))["logged"] == 0,
      "no table: an empty calibration, no error")

print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
