# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
A replayed old death takes no data that was gathered after it (LD1, 5.0.1).

22.11.2026: the connection dropped, the game wrote its journal anew (the
events of the three hours before were gone from the file), and the
journal-gap warning advised "Replay journals". The replay met the one real
death of 11.07. again and reset everything open that day (74 bodies); the
later events opened most of it again - but not what the game had cut. After
the sale 26 bodies still showed as "lost in a crash". The sequence here is
built from that day (system and body names made up, no commander data):

  * the old journal: scans, then Died (the real crash) - stays lost;
  * live (EDMC) only: three scans, the part the game cut from its journal;
  * the rewritten journal: one more scan; then the replay;
  * nothing of the second system is lost; the sale clears everything;
  * a real death now still takes what is open, rows from before 5.0.1
    (without open_ts) too.

    python tests/lost_on_replay.py      (from the plugin folder)
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH import sysdb  # noqa: E402
from SHBOXSEARCH.sysdb import SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def scan(sysname, addr, bid, ts):
    return {"event": "Scan", "ScanType": "Detailed", "StarSystem": sysname, "SystemAddress": addr,
            "BodyName": "%s %d" % (sysname, bid), "BodyID": bid, "PlanetClass": "Icy body",
            "DistanceFromArrivalLS": 100.0 * bid, "timestamp": ts}


def write(path, events):
    with open(path, "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


LOGIN = [{"event": "Commander", "FID": "F7", "Name": "Tester"},
         {"event": "LoadGame", "FID": "F7", "Commander": "Tester"}]
OLD, GAP = 7001, 7002
with tempfile.TemporaryDirectory() as d:
    db = SystemDB(os.path.join(d, "p.sqlite"))
    db.set_meta(sysdb.CMDR_READY, "2026-07-01T00:00:00Z")
    old = [dict(LOGIN[0], timestamp="2026-07-11T18:00:00Z"), dict(LOGIN[1], timestamp="2026-07-11T18:00:01Z"),
           {"event": "FSDJump", "StarSystem": "Old Sys", "SystemAddress": OLD, "StarPos": [1.0, 0.0, 0.0],
            "timestamp": "2026-07-11T18:10:00Z"},
           scan("Old Sys", OLD, 1, "2026-07-11T18:11:00Z"), scan("Old Sys", OLD, 2, "2026-07-11T18:12:00Z"),
           {"event": "Died", "timestamp": "2026-07-11T19:20:06Z"}]
    write(os.path.join(d, "Journal.2026-07-11T200000.01.log"), old)
    db.import_journals(d)
    lost = {x["name"] for x in db.lost_summary("F7")}
    check(lost == {"Old Sys"}, "the real crash of 11.07.: Old Sys lost (%s)" % sorted(lost))

    # 22.11., live: EDMC passes everything on, the plugin stores it
    live = [dict(LOGIN[0], timestamp="2026-11-22T16:41:28Z"), dict(LOGIN[1], timestamp="2026-11-22T16:41:30Z"),
            {"event": "FSDJump", "StarSystem": "Gap Sys", "SystemAddress": GAP, "StarPos": [2.0, 0.0, 0.0],
             "timestamp": "2026-11-22T17:00:00Z"}]
    live += [scan("Gap Sys", GAP, b, "2026-11-22T17:0%d:00Z" % b) for b in (1, 2, 3)]
    for e in live:
        db.ingest_journal_event(e)
    kept = [{"event": "Fileheader", "part": 1, "timestamp": "2026-11-22T19:39:13Z"},
            scan("Gap Sys", GAP, 4, "2026-11-22T19:42:34Z")]
    db.ingest_journal_event(kept[1])
    # the game wrote the journal of that session anew: from 19:39 on only
    write(os.path.join(d, "Journal.2026-11-22T174128.01.log"), kept)

    db.import_journals(d)                         # "Replay journals", as the warning advised
    gap = {r["body_id"]: r for r in db.bodies_for(GAP, "F7")}
    check(all(not gap[b]["lost_what"] for b in (1, 2, 3, 4)),
          "the replay of the old death takes nothing gathered after it")
    check(all(gap[b]["scanned"] == 1 for b in (1, 2, 3, 4)), "the four scans stay scanned")
    open_ = db.cx.execute("SELECT COUNT(*) FROM cmdr_bodies WHERE fid='F7' AND sys_id64=? AND scan_open=1",
                          (GAP,)).fetchone()[0]
    check(open_ == 4, "all four still carried unsold (%d)" % open_)
    lost = {x["name"] for x in db.lost_summary("F7")}
    check(lost == {"Old Sys"}, "LOST DATA: only the real crash (%s)" % sorted(lost))

    db.ingest_journal_event({"event": "MultiSellExplorationData", "Discovered": [{"SystemName": "Gap Sys"}],
                             "timestamp": "2026-11-23T12:00:00Z"})
    open_ = db.cx.execute("SELECT COUNT(*) FROM cmdr_bodies WHERE fid='F7' AND scan_open=1").fetchone()[0]
    check(open_ == 0, "the sale clears everything carried")
    check({x["name"] for x in db.lost_summary("F7")} == {"Old Sys"}, "and leaves no Gap Sys leftovers")

    # a real death today still counts - also for a row from before 5.0.1 (no open_ts)
    now = time.time()
    db.ingest_journal_event(scan("Gap Sys", GAP, 5, iso(now - 60)))
    db.ingest_journal_event(scan("Gap Sys", GAP, 6, iso(now - 50)))
    db.cx.execute("UPDATE cmdr_bodies SET open_ts=NULL WHERE sys_id64=? AND body_id=6", (GAP,))
    db.ingest_journal_event({"event": "Died", "timestamp": iso(now)})
    gap = {r["body_id"]: r for r in db.bodies_for(GAP, "F7")}
    check(json.loads(gap[5]["lost_what"] or "[]") == ["scan"] and gap[5]["scanned"] == 0,
          "a real death now: the open scan is lost")
    check(json.loads(gap[6]["lost_what"] or "[]") == ["scan"], "... a row without open_ts too")
    check(not gap[4]["lost_what"], "sold data stays")

    # the same old death replayed once more: a row without open_ts is left alone
    db.ingest_journal_event(scan("Gap Sys", GAP, 7, iso(now)))
    db.cx.execute("UPDATE cmdr_bodies SET open_ts=NULL WHERE sys_id64=? AND body_id=7", (GAP,))
    db.ingest_journal_event({"event": "Died", "timestamp": "2026-07-11T19:20:06Z"})
    gap = {r["body_id"]: r for r in db.bodies_for(GAP, "F7")}
    check(not gap[7]["lost_what"] and gap[7]["scanned"] == 1, "an old death replayed: an unknown row stays")
    db.cx.close()

print("lost on replay: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
