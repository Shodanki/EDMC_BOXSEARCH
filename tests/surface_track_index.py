# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""R1 (5.1.0): a refined tonne no longer scans the whole surface track in
EDMC's main thread - the Rhino lookup by time uses an index."""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from sysdb import SystemDB  # noqa: E402

SQL = ("SELECT sys_id64, body_name, lat, lon FROM surface_track WHERE mode='srv'"
       " AND ts BETWEEN ? AND ? ORDER BY ABS(ts - ?) LIMIT 1")


def main():
    with tempfile.TemporaryDirectory() as d:
        db = SystemDB(os.path.join(d, "t.sqlite"))
        try:
            src = open(os.path.join(HERE, "sysdb.py"), encoding="utf-8").read()
            assert SQL.split(" FROM")[0] in src and "ts BETWEEN ? AND ? ORDER BY ABS(ts - ?)" in src, \
                "the query in _rig_refined changed - update this test"
            plan = " ".join(str(tuple(r)) for r in db.cx.execute("EXPLAIN QUERY PLAN " + SQL, (1, 2, 1)).fetchall())
            assert "surface_track_ts" in plan, plan
            t0 = 1.7e9
            db.cx.executemany("INSERT INTO surface_track (sys_id64, body_name, ts, lat, lon, mode) VALUES (?,?,?,?,?,?)",
                              [(1, "B", t0 + i, 1.0, 2.0, "ship" if i % 7 else "srv") for i in range(50000)])
            db.cx.commit()
            start = time.perf_counter()
            for i in range(200):
                db.cx.execute(SQL, (t0 + i * 100 - 15, t0 + i * 100 + 15, t0 + i * 100)).fetchone()
            ms = (time.perf_counter() - start) * 1000 / 200
            assert ms < 2.0, "%.2f ms per refined tonne on 50 000 track rows" % ms
            row = db.cx.execute(SQL, (t0 + 700 - 15, t0 + 700 + 15, t0 + 700)).fetchone()
            assert row is not None and row[1] == "B"
        finally:
            db.close()
    print("surface track index: ok (%.2f ms a lookup on 50 000 rows)" % ms)


if __name__ == "__main__":
    main()
