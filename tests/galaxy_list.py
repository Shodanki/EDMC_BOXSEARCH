# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Galaxy map list test (4.10) - the case of 13.11.2026: "Synuefe RH-U c19-"
lists 1 to 21 in the galaxy map, no "-0". Slot 0 is the catalogue star
HIP 33254; EDDiscovery knows most of the "gaps", just outside the radius it
was read to. No network, no EDMC (stubbed), a temporary database and a small
EDDiscovery-layout file built here.

  * a catalogue star fills its slot: no gap, no probe at "-0";
  * "not there" below the highest known number closes nothing;
  * "list ends at": refused below a known system, the end is the number
    + 1, numbers above what was known become gaps, probes above it go;
  * an end at or below a known system is no end (planner) and is repaired
    once (database);
  * probe candidates are looked up in EDD's file by id64 - only rows whose
    position lies in the id64's boxel count;
  * a restored sphere reads EDD again once for 4.10 (id64s);
  * picking any listed name in the map drops that candidate, not only the
    head of the queue; so does a route that made it known, and "list end"
    counts no such stale entry;
  * EDD is walked upwards per boxel until it has no number - one plan
    rebuild is enough.

    python tests/galaxy_list.py      (from the plugin folder)
"""
import os
import sqlite3
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
from boxelplan import K_GAP, K_PROBE, Planner, Target  # noqa: E402
from sources import EDDiscoverySource, SourceManager  # noqa: E402
from sysdb import SystemDB  # noqa: E402

FAILS = 0
KEY = "Synuefe RH-U c19"
STEP = 1 << 38                       # n2 step of a mass code c id64
ID0 = 84791923370                    # slot 0 = HIP 33254 in the game
CENTER = (550.0, -165.0, -205.0)
# the database knows these (id64 = ID0 + n2 * STEP); positions from the game
KNOWN = {1: (553.625, -166.34375, -217.0), 2: (535.71875, -158.25, -223.4375),
         4: (568.84375, -172.75, -200.6875), 5: (537.78125, -152.28125, -195.15625),
         7: (544.34375, -160.84375, -199.1875), 8: (547.1875, -163.21875, -200.375),
         9: (543.96875, -169.6875, -198.59375), 10: (541.53125, -174.75, -209.875),
         11: (539.9375, -169.34375, -210.5), 12: (539.15625, -145.03125, -189.59375),
         17: (535.0, -159.125, -190.78125), 19: (544.8125, -164.59375, -191.15625),
         20: (542.6875, -163.65625, -196.9375), 21: (541.25, -159.5625, -193.71875)}
HIP_POS = (556.75, -166.375, -216.40625)
C19_3 = (572.9375, -168.1875, -193.40625)


def check(ok, what):
    global FAILS
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    FAILS += 0 if ok else 1


def fill(db):
    for n2, pos in KNOWN.items():
        db.upsert("%s-%d" % (KEY, n2), *pos, id64=ID0 + n2 * STEP, source="navroute")


def gaps_of(plan, kind=K_GAP):
    return sorted(t.n2 for t in plan["targets"] if t.boxel_key == KEY and t.kind == kind)


def plan(db, **kw):
    return Planner(db).build(CENTER, 10.0, masscodes=(2,), origin=CENTER, **kw)


def edd_file(path):
    """A file in EDDiscovery's layout: edsmid = id64, x/y/z * 128."""
    cx = sqlite3.connect(path)
    cx.executescript(
        "CREATE TABLE SystemTable (edsmid INTEGER PRIMARY KEY NOT NULL, sectorid INTEGER,"
        " nameid INTEGER, x INTEGER, y INTEGER, z INTEGER, info INTEGER);"
        "CREATE TABLE Sectors (id INTEGER PRIMARY KEY, gridid INTEGER, name TEXT);"
        "CREATE TABLE Names (id INTEGER PRIMARY KEY, Name TEXT);")
    cx.execute("INSERT INTO Sectors VALUES (1, 0, 'Synuefe')")
    cx.execute("INSERT INTO Sectors VALUES (2, 0, 'HIP')")

    def std(n2):    # RH-U c19-n2: letters 1-based, mass code c = 2, n1 = 19
        return ((1 << 61) | n2 | (19 << 16) | (2 << 24) | (21 << 28) | (8 << 33)
                | (18 << 38))

    def row(i, sector, nameid, pos):
        cx.execute("INSERT INTO SystemTable VALUES (?,?,?,?,?,?,NULL)",
                   (i, sector, nameid) + tuple(int(round(v * 128)) for v in pos))
    for n2, pos in KNOWN.items():
        row(ID0 + n2 * STEP, 1, std(n2), pos)
    row(ID0, 2, (1 << 60) | 33254 | (5 << 42), HIP_POS)          # HIP 33254
    row(ID0 + 3 * STEP, 1, std(3), C19_3)
    # a row whose number is no id64 of its place - must not count
    row(ID0 + 6 * STEP, 1, std(6), (0.0, 0.0, 0.0))
    cx.commit()
    cx.close()


def part_db(tmp):
    print("database and planner")
    db = SystemDB(os.path.join(tmp, "a.sqlite"))
    fill(db)
    p = plan(db)
    check(gaps_of(p) == [0, 3, 6, 13, 14, 15, 16, 18],
          "without the catalogue star, slot 0 looks like a gap")
    check(db.mark_absent(KEY + "-0") is False and db.boxel_end(KEY) is None,
          "'not there' on -0 below the known 21 closes nothing")
    p = plan(db)
    check(0 not in gaps_of(p) and gaps_of(p, K_PROBE) == [22, 23],
          "the boxel stays open: probes 22 and 23 remain")
    db.upsert("HIP 33254", *HIP_POS, id64=ID0, source="EDDiscovery")
    check(db.boxel_known_max(KEY) == 21 and 0 in db.known_n2(KEY),
          "HIP 33254 fills slot 0 (by id64)")
    gap3 = [t for t in plan(db)["targets"] if t.boxel_key == KEY and t.n2 == 3]
    check(bool(gap3) and gap3[0].id64 == ID0 + 3 * STEP, "a gap carries its slot's id64")
    check(db.close_boxel(KEY, 19) is None and db.boxel_end(KEY) is None,
          "list end 19 refused - 21 is known")
    check(db.close_boxel(KEY, 21) == 22, "list end 21 -> the boxel ends at 22")
    p = plan(db)
    check(gaps_of(p) == [3, 6, 13, 14, 15, 16, 18] and gaps_of(p, K_PROBE) == [],
          "closed at 22: the 7 gaps stay, no probes above")
    check(db.close_boxel(KEY, 23) == 24, "a longer list (23) is taken")
    check(gaps_of(plan(db))[-2:] == [22, 23], "numbers above what was known become gaps")
    # an old wrong end (as "not there" on a catalogue slot wrote it up to 4.9)
    db.cx.execute("UPDATE boxels SET n2_end=5, complete=1 WHERE key=?", (KEY,))
    db.cx.commit()
    check(gaps_of(plan(db), K_PROBE) == [22, 23], "planner ignores an end below a known system")
    res = db.repair_boxel_ends()
    check(res["reopened"] == 1 and db.boxel_end(KEY) is None,
          "one-time repair reopens it (%s)" % res)
    db.close()


def part_edd(tmp):
    print("EDDiscovery by id64")
    path = os.path.join(tmp, "EDDSystem.sqlite")
    edd_file(path)
    e = EDDiscoverySource(path)
    check(e.calibrate()[0], "fake EDD file calibrates")
    got = {r["name"]: r for r in e.lookup_id64([ID0, ID0 + 3 * STEP, ID0 + 6 * STEP,
                                                ID0 + 22 * STEP])}
    check(sorted(got) == ["HIP 33254", KEY + "-3"],
          "found: HIP 33254 and -3; -6 refused (wrong place); -22 not there")
    check(got.get("HIP 33254", {}).get("id64") == ID0, "the id64 comes along")
    ball = e.fetch(CENTER, 15.0)
    check(ball and all(r["id64"] for r in ball), "sphere read carries id64s (%d rows)" % len(ball))
    return path


def part_flow(tmp, edd_path):
    print("plugin flow")
    cfg = {load.CFG["src_edd"]: True}
    load.cfg_bool = lambda k, d=False: cfg.get(k, d)
    load.cfg_int = lambda k, d=0: d
    load.get_masscodes = lambda: [2]
    load._set_status = lambda m: None
    load._ui = lambda f, *a, **k: None
    load._update_route_targets = lambda: None
    load._maybe_extend = lambda: None
    load._copy = lambda t: None
    load._run_async = lambda fn, *a, label="", **kw: fn(*a, **kw)
    ST = load.ST
    ST.net.offline = True
    ST.db = SystemDB(os.path.join(tmp, "f.sqlite"))
    ST.planner = Planner(ST.db)
    ST.sources = SourceManager(edd_path, gateway=ST.net)
    ST.center, ST.radius, ST.cur_pos = CENTER, 10.0, CENTER
    ST.active, ST.start_system = True, "test"
    fill(ST.db)
    # a restored sphere: EDD is read again once for 4.10
    load._resume_worker()
    check(bool(ST.db.get_meta(load.EDD_ID64_META)), "restored sphere: EDD read again once")
    hip = ST.db.system("HIP 33254")
    check(hip is not None and hip["id64"] == ID0, "the sphere read brought HIP 33254 with its id64")
    gaps = sorted(t.n2 for t in ST.probe if t.boxel_key == KEY and t.kind == K_GAP)
    check(gaps == [6, 13, 14, 15, 16, 18],
          "c19-3 came from EDD by id64 (beyond the radius); gaps left %s" % gaps)
    check(ST.db.system(KEY + "-3") is not None, "c19-3 stored")
    check(ST.db.system(KEY + "-6") is None, "the wrong-place row is not taken")
    # "not there" below the maximum: only that name goes
    ST.probe.insert(0, Target(KEY + "-0", K_GAP, 0.0, mc=2, boxel_key=KEY, n2=0))
    n_box = sum(1 for q in ST.probe if q.boxel_key == KEY)
    load._probe_absent()
    check(ST.db.boxel_end(KEY) is None
          and sum(1 for q in ST.probe if q.boxel_key == KEY) == n_box - 1,
          "'not there' on -0 drops that name only, boxel open")
    # list ends at 21
    ST.probe.sort(key=lambda q: q.boxel_key != KEY)
    load._list_end_var = mock.MagicMock()
    load._list_end_var.get.return_value = "21"
    load._list_end()
    left = sorted(q.n2 for q in ST.probe if q.boxel_key == KEY)
    check(ST.db.boxel_end(KEY) == 22 and left == [6, 13, 14, 15, 16, 18],
          "list end 21: probes above gone, gaps stay %s" % left)
    load._list_end_var.get.return_value = "12"
    load._list_end()
    check(ST.db.boxel_end(KEY) == 22, "list end 12 refused")
    # picking a name further down the list confirms it
    ST.db.upsert(KEY + "-15", id64=ID0 + 15 * STEP, quality=20, source="destination")
    load._prune_known_probes()
    left = sorted(q.n2 for q in ST.probe if q.boxel_key == KEY)
    check(15 not in left and 6 in left, "a confirmed name leaves the queue, not only the head")
    # a plotted route made a gap known: the next jump/route/scan prunes it
    ST.db.upsert(KEY + "-13", id64=ID0 + 13 * STEP, source="navroute")
    load._prune_queues()
    left = sorted(q.n2 for q in ST.probe if q.boxel_key == KEY)
    check(13 not in left, "a name known from a route leaves the queue (%s)" % left)
    # ... and "list end" drops a name known meanwhile before it counts
    ST.db.upsert(KEY + "-14", id64=ID0 + 14 * STEP, source="navroute")
    load._list_end_var.get.return_value = "21"
    load._list_end()
    left = sorted(q.n2 for q in ST.probe if q.boxel_key == KEY)
    check(left == [6, 16, 18], "'list end' counts no stale entry: gaps left %s" % left)
    ST.db.close()


def part_chain(tmp, edd_path):
    '''EDD knows numbers far above the boxel's maximum: one plan rebuild
    walks them up until EDD has none (4.10 fix - three rebuilds left 12
    known probes in the developer's sphere).'''
    print("EDDiscovery walked upwards")
    ST = load.ST
    ST.db = SystemDB(os.path.join(tmp, "c.sqlite"))
    ST.planner = Planner(ST.db)
    ST.sources = SourceManager(edd_path, gateway=ST.net)
    ST.center, ST.radius, ST.cur_pos, ST.horizon = CENTER, 10.0, CENTER, 10.0
    ST.active, ST.edd_asked = True, set()
    for n2 in (1, 2, 4, 5):
        ST.db.upsert("%s-%d" % (KEY, n2), *KNOWN[n2], id64=ID0 + n2 * STEP, source="navroute")
    rounds = load.EDD_FILL_ROUNDS
    load.EDD_FILL_ROUNDS = 1           # one rebuild only: the walk must do it
    try:
        load._rebuild_plan()
    finally:
        load.EDD_FILL_ROUNDS = rounds
    stored = sorted(n for n in range(0, 23) if ST.db.system("%s-%d" % (KEY, n)))
    check(stored == [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12],
          "walked up from 7 to 12, where EDD has no 13 (stored %s)" % stored)
    gaps = sorted(q.n2 for q in ST.probe if q.boxel_key == KEY and q.kind == K_GAP)
    probes = sorted(q.n2 for q in ST.probe if q.boxel_key == KEY and q.kind == K_PROBE)
    check(gaps == [6] and probes == [13, 14],
          "left: gap 6 (EDD's row is in the wrong place), probes 13 and 14 (%s / %s)"
          % (gaps, probes))
    check(ST.db.system("HIP 33254") is not None, "slot 0 came as HIP 33254")
    ST.db.close()


def main():
    print("galaxy map list (4.10)")
    tmp = tempfile.mkdtemp()
    part_db(tmp)
    edd = part_edd(tmp)
    part_flow(tmp, edd)
    part_chain(tmp, edd)
    print("failures:", FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
