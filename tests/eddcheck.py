# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
FX4 (5.0): systems never looked up (plotted routes from before the I1
route check) are asked in EDDiscovery's file by id64: what EDD has becomes
"known", what it lacks with an exact position "checked" (in no database),
an estimate stays "not checked"; the backfill runs once per session, the
FSDTarget check only for a system not checked yet, and the first arrival's
prediction (findlog) then carries the level.

    python tests/eddcheck.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import boxelplan, eddcheck, findlog, shells, state  # noqa: E402
from SHBOXSEARCH.sysdb import CMDR_READY, Q_ESTIMATE, Q_JOURNAL, SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


class FakeEDD:
    """lookup_id64 like EDDiscoverySource: the rows it has, None when busy."""
    name = "EDDiscovery"

    def __init__(self, have):
        self.have, self.asked, self.busy = dict(have), [], False

    def available(self):
        return True, "test"

    def lookup_id64(self, ids):
        self.asked.append(list(ids))
        if self.busy:
            return None
        return [dict(self.have[i], id64=i) for i in ids if i in self.have]


class FakeSources:
    def __init__(self, edd):
        self.sources = {"edd": edd}
        self.ref = None

    def set_reference(self, id64, pos):
        self.ref = (id64, pos)


ST = state.ST
ST.db = SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
ST.db.set_meta(CMDR_READY, "test")
ST.db.set_commander("F1", "Cmdr")
db = ST.db

KNOWN, ABSENT, EST, OLD = "Oochorrs CM-F a93-0", "Oochoxt JL-B b47-2", "Oochoxt PP-I c12-3", "Synuefe UL-M b40-1"
db.upsert(KNOWN, 1118.40625, -39.21875, -1345.21875, id64=5487357347608, quality=Q_JOURNAL, source="navroute")
db.upsert(ABSENT, 1200.0, -70.0, -1400.0, id64=5094770549649, quality=Q_JOURNAL, source="navroute")
db.upsert(EST, id64=911975813482, quality=Q_ESTIMATE, source="navroute")
db.upsert(OLD, 621.0, -219.5625, -203.1875, id64=2878298531161, quality=Q_JOURNAL, source="EDSM")
db.upsert("Col 70 Sector KJ-G d11-14", 10.0, -245.0, 20.0, id64=7000, quality=30, source="external")
db.cx.commit()


def level(name):
    row = db.system(name)
    pos = (row["x"], row["y"], row["z"]) if (row["quality"] or 0) > Q_ESTIMATE else None
    regions = {k: db.valid_shells(k) for k in ("edd", "spansh", "edsm")}
    return shells.info_level(set((row["sources"] or "").split(",")), pos, regions)[0]


print("which systems are asked")
todo = eddcheck.unlooked(db)
names = sorted(n for n, _i, _p in todo)
check(names == sorted([KNOWN, ABSENT, EST, "Col 70 Sector KJ-G d11-14"]),
      "never looked up: the four without a named database source (%s)" % names)
check([p for n, _i, p in todo if n.startswith("Col 70")] == [None], "an old import ('external') gets no check")
check(all(p is None for n, _i, p in todo if n == EST) and all(p for n, _i, p in todo if n in (KNOWN, ABSENT)),
      "an estimated position is no exact position")

print("backfill: known, checked, estimate")
edd = FakeEDD({5487357347608: {"name": KNOWN, "x": 1118.40625, "y": -39.21875, "z": -1345.21875}})
ST.sources = FakeSources(edd)
ST.cur_id64, ST.cur_pos = 2878298531161, (621.0, -219.5625, -203.1875)
res = eddcheck.run_backfill()
check(res == (1, 1), "1 known, 1 checked (got %s)" % (res,))
check(len(edd.asked) == 1 and len(edd.asked[0]) == 4, "one lookup for all four ids")
check(level("Col 70 Sector KJ-G d11-14") == "unchecked", "not in EDD, old import: never 'in no database'")
check(ST.sources.ref == (ST.cur_id64, ST.cur_pos), "EDD calibrates against the current system")
check(level(KNOWN) == "known" and "EDDiscovery" in db.system(KNOWN)["sources"], "EDD has it: known")
check(abs(db.system(KNOWN)["x"] - 1118.40625) < 1e-9 and db.system(KNOWN)["quality"] == Q_JOURNAL,
      "the journal's exact position stays")
check(level(ABSENT) == "checked", "EDD lacks it, exact position: checked - in no database")
check(level(EST) == "unchecked", "EDD lacks it, estimate only: still not checked")
check(level(OLD) == "known", "a system with a source is untouched")
again = eddcheck.unlooked(db)
want = [("Col 70 Sector KJ-G d11-14", True), (ABSENT, True), (EST, True)]
check(sorted((n, p is None) for n, _i, p in again) == want,
      "asked again next time: the estimate, and the absent one without a new check (%s)" % again)
shells_before = db.cx.execute("SELECT COUNT(*) FROM fetched_shells").fetchone()[0]
edd.have[5094770549649] = {"name": ABSENT, "x": 1200.0, "y": -70.0, "z": -1400.0}
res = eddcheck.run_backfill()
check(res == (1, 0) and level(ABSENT) == "known", "EDD learnt it since: now known (%s)" % (res,))
check(db.cx.execute("SELECT COUNT(*) FROM fetched_shells").fetchone()[0] == shells_before,
      "no check is kept twice")
del edd.have[5094770549649]

print("busy or switched off: nothing changes")
edd.busy = True
db.upsert("Oochoxt HO-P b39-1", 1210.0, -71.0, -1401.0, id64=4000, quality=Q_JOURNAL, source="navroute")
check(eddcheck.run_backfill() is None and level("Oochoxt HO-P b39-1") == "unchecked", "EDD busy: asked later")
edd.busy = False
ST.sources = None
check(eddcheck.run_backfill() is None, "no sources: nothing asked")
ST.sources = FakeSources(edd)

print("once per session")
started = []
eddcheck.threading = type("T", (), {"Thread": lambda **kw: started.append(kw) or type(
    "X", (), {"start": lambda self: None})()})
ST.edd_backfilled = False
eddcheck.backfill()
eddcheck.backfill()
check(len(started) == 1 and started[0]["target"] is eddcheck.run_backfill, "the backfill starts once")

print("FSDTarget: the selected system before the jump")
started.clear()
eddcheck.check_target({"event": "FSDTarget", "Name": "Oochoxt HO-P b39-1", "SystemAddress": 4000})
check(len(started) == 1, "FSDTarget hands the check to a worker thread")
edd.asked.clear()
res = eddcheck.run_target("Oochoxt HO-P b39-1", 4000)
check(res == (0, 1) and level("Oochoxt HO-P b39-1") == "checked", "not in EDD: checked (%s)" % (res,))
check(eddcheck.run_target("Oochoxt HO-P b39-1", 4000) is None and len(edd.asked) == 1,
      "checked already: EDD is not asked again")
check(eddcheck.run_target(KNOWN, 5487357347608) is None, "known already: nothing asked")
eddcheck.check_target({"event": "FSDTarget", "Name": "X"})
check(len(started) == 1, "no SystemAddress: nothing started")

print("the first arrival's prediction carries the level")
pred = findlog.keep_prediction({"event": "FSDJump", "timestamp": "2027-01-15T08:00:00Z",
                                "StarSystem": "Oochoxt HO-P b39-1", "SystemAddress": 4000,
                                "StarPos": [1210.0, -71.0, -1401.0], "StarClass": "M"})
row = db.cx.execute("SELECT level FROM find_log WHERE sys_id64=4000").fetchone()
check(pred is not None and row is not None and row["level"] == "checked",
      "find_log: level checked (%s)" % (row["level"] if row else None))

print("absence proofs: kept for good, counted as calibration hits")
proofs = db.absence_names()
check(proofs == {"Oochoxt HO-P b39-1", ABSENT}, "both checked as in no database have a proof (%s)" % sorted(proofs))
check(level(ABSENT) == "known", "ABSENT is known now (EDD learnt it) - its proof stays: nobody had it then")
db.cx.execute("UPDATE fetched_shells SET expires_at=0")
db.cx.commit()
check(db.absence_names() == proofs and level("Oochoxt HO-P b39-1") == "unchecked",
      "the check expired, the proof stays")
db.upsert("Oochoxt XX-A b1-0", 1300.0, -60.0, -1500.0, id64=4100, quality=Q_JOURNAL, source="navroute")
db.upsert("Oochoxt XX-A b1-1", 1310.0, -60.0, -1500.0, id64=4101, quality=Q_JOURNAL, source="EDSM")
db.upsert("Oochoxt XX-A b1-2", 1320.0, -60.0, -1500.0, id64=4102, quality=Q_JOURNAL, source="navroute")
for x, svc, n in ((1300.0, "edd", 0), (1310.0, "edd", 0), (1320.0, "edd", 0), (1320.0, "edsm", 1)):
    db.record_shell(svc, (x, -60.0, -1500.0), 0.0, 0.1, n, 86400)
new = db.proofs_from_checks(boxelplan.CLIENT_SOURCES)
check(new == 1 and "Oochoxt XX-A b1-0" in db.absence_names(), "a client-proved system in an empty check: proof")
check("Oochoxt XX-A b1-1" not in db.absence_names(), "no client source (an EDSM row): no proof")
check("Oochoxt XX-A b1-2" not in db.absence_names(), "EDD had nothing but EDSM had it: no proof")
check(db.proofs_from_checks(boxelplan.CLIENT_SOURCES) == 0, "kept once")


class Cx:
    proof_boxels = {"Oochoxt XX-A b1"}
    client_boxels = {"Oochoxt XX-A b1", "Synuefe AB-C b2"}
    db_boxels = {"Oochoxt XX-A b1", "Synuefe AB-C b2"}


check(boxelplan._calib_hit(Cx, ["Oochoxt XX-A b1"]), "a proof counts although a database knows the boxel now")
check(not boxelplan._calib_hit(Cx, ["Synuefe AB-C b2"]), "client and database without a proof: no hit")
Cx.db_boxels = set()
check(boxelplan._calib_hit(Cx, ["Synuefe AB-C b2"]), "client only (no database at all): a hit as before")

print("")
print("FAILED: %d" % fails if fails else "all OK")
sys.exit(1 if fails else 0)
