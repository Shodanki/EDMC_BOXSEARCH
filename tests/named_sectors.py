# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Named-sector test (4.10): the sphere planner and the id64 naming where a
hand-authored sector lies over the procedural grid - no network, a
temporary database.

  * inside NGC 2232 Sector the probes carry that sector's name, not the
    procedural one (before 4.10 every boxel there got a name the galaxy
    map can never find);
  * a boxel the surface of NGC 2244 Sector cuts ("Pyurks FH-J d10" =
    "NGC 2244 Sector GW-M d7", the case found by the systematic-boxel-survey
    project) shares its system numbers: a gap is found across both names,
    "not there" under one name brings up the other, both ruled out ends it;
  * a name seen with a position is tried first;
  * an id64 alone gives a name only where the boxel has one.

    python tests/named_sectors.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import procgen  # noqa: E402
from boxelplan import Planner, K_GAP  # noqa: E402
from sysdb import SystemDB  # noqa: E402

FAILS = 0


def check(ok, what):
    global FAILS
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    FAILS += 0 if ok else 1


def gidx_of(id64):
    d = procgen.decode_id64(id64)
    per = 128 >> d["mc"]
    return d, tuple(s * per + b for s, b in zip(d["sector_idx"], d["boxel"]))


def main():
    print("named sectors (4.10)")
    if procgen._edts is None:
        print("  edts_pgnames missing - nothing to test")
        return 1
    tmp = tempfile.mkdtemp()
    db = SystemDB(os.path.join(tmp, "t.sqlite"))
    pl = Planner(db)

    # --- inside NGC 2232 Sector (real system of a survey, game id64)
    pos = (539.0625, -123.46875, -982.90625)
    db.upsert("NGC 2232 Sector KO-P b6-1", *pos, id64=2877225116705, source="journal")
    plan = pl.build(pos, 15.0, masscodes=(1,), include_tasks=False)
    names = [t.name for t in plan["probe"]]
    check(names and all(n.startswith("NGC 2232 Sector ") for n in names),
          "all %d probes inside NGC 2232 Sector carry its name" % len(names))
    check("NGC 2232 Sector KO-P b6-0" in names,
          "the gap below the known KO-P b6-1 is found")
    check(not plan["sectors_missing"], "no sector is missing a name")

    # --- the edge boxel of NGC 2244 Sector: Pyurks FH-J d10 = GW-M d7
    d, g = gidx_of(10997434331)                      # NGC 2244 Sector GW-M d7-0
    centre = procgen.boxel_center(g, d["mc"])
    labels = procgen.boxel_labels(g, d["mc"])
    keys = [procgen.boxel_key_of(s, d["mc"], b) for s, b in labels]
    check(keys == ["Pyurks FH-J d10", "NGC 2244 Sector GW-M d7"],
          "two labels for the cut boxel: %s" % keys)
    db.upsert("NGC 2244 Sector GW-M d7-0", *centre, id64=10997434331, source="journal")
    id2 = procgen.id64_from_parts(d["sector_idx"], d["mc"], d["boxel"], 2)
    db.upsert("Pyurks FH-J d10-2", *centre, id64=id2, source="journal")

    def edge_gaps():
        p = pl.build(centre, 1.0, masscodes=(d["mc"],), include_tasks=False,
                     include_empty=False)
        return [t for t in p["targets"] if t.kind == K_GAP]

    gaps = edge_gaps()
    check([t.n2 for t in gaps] == [1],
          "n2 0 under one name, 2 under the other: the gap is n2 = 1")
    first = gaps[0].name if gaps else ""
    check(first in ("Pyurks FH-J d10-1", "NGC 2244 Sector GW-M d7-1")
          and "also named" in (gaps[0].detail if gaps else ""),
          "the gap names a seen label and says the other: %s | %s"
          % (first, gaps[0].detail if gaps else ""))
    db.mark_absent(first)
    gaps = edge_gaps()
    other = gaps[0].name if gaps else ""
    check(other and other != first and other.endswith("-1"),
          "'not there' under one name brings up the other: %s" % other)
    db.mark_absent(other)
    check(edge_gaps() == [], "both names ruled out: no gap left")

    # --- names from an id64 alone
    check(db.name_from_id64(2877225116705) == "NGC 2232 Sector KO-P b6-1",
          "id64 inside NGC 2232 Sector: its name")
    check(db.name_from_id64(procgen.id64_from_parts(d["sector_idx"], d["mc"], d["boxel"], 7))
          is None, "id64 in the cut boxel: no name invented")
    check(db.name_from_id64(422810994947) is None,
          "Synuefe XV-C d12: its 80 ly boxel touches Col 70 Sector - no guess")
    syn = db.name_from_id64(2690637597019)
    check(syn == "Synuefe WG-J d10-78", "procedural id64 named without any learnt sector: %s" % syn)

    # --- the registry keeps procedural sectors only
    db.learn_sector("NGC 2232 Sector KO-P b6-1", id64=2877225116705)
    check(db.sectors.index_of("NGC 2232 Sector") is None,
          "a hand-authored name never becomes a sector of the registry")
    db.cx.close()
    print("failures: %d" % FAILS)
    return FAILS


if __name__ == "__main__":
    raise SystemExit(main())
