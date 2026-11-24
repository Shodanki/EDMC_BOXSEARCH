# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
False loss marks are taken back on every start and after every replay (LM1, 5.0.1).

A loss mark is valid only if a real Died made it and the lost work was open
before that death. Up to 5.0.0, "Replay journals" met an old real death
again and marked what was open that day - also data the game had cut from
its rewritten journal (22.11.2026: 23 bodies of one system and 3 of another
stayed "lost in a crash" after the sale). Those marks are in the databases
of 5.0.0 users; LD1 only stops new ones. The sequence here rebuilds that day
(names made up, no commander data):

  * 11.07.: scans in Old Sys, then the real Died - stays lost;
  * 22.11. live: arrival in Gap Sys, scans, a map and a species; the 5.0.0
    replay of the old death marks them lost; the sale of Gap Sys comes after;
  * the next start takes the Gap Sys marks back: scanned, mapped, analysed,
    counted as sold; the plugin's and the FIS's LOST DATA both show Old Sys only;
  * a mark of a minute the replay read without a death goes after the replay;
  * a real death now still counts, also after a start and a replay.

    python tests/false_losses.py      (from the plugin folder)
"""
import json
import os
import sys
import tempfile
import threading
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "FIS"))      # the FIS's own reader
for m in ("config", "theme", "myNotebook", "monitor", "l10n", "companion", "plug",
          "EDMCLogging", "ttkHyperlinkLabel"):
    sys.modules[m] = mock.MagicMock()
try:                                  # CI images may lack Tk; no window is opened
    import tkinter  # noqa: F401
except ImportError:
    for m in ("tkinter", "tkinter.filedialog", "tkinter.ttk"):
        sys.modules[m] = mock.MagicMock()

import plugin_pkg  # noqa: E402
plugin_pkg.import_plugin()
from SHBOXSEARCH import maintenance, sysdb  # noqa: E402
from SHBOXSEARCH.state import ST  # noqa: E402
from SHBOXSEARCH.sysdb import SystemDB  # noqa: E402
from fis.data import Database  # noqa: E402

fails = 0
FID = "F7"


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


def rows(db, addr):
    return {r["body_id"]: r for r in db.cx.execute(
        "SELECT * FROM cmdr_bodies WHERE fid=? AND sys_id64=?", (FID, addr))}


def lost_names(summary):
    return sorted(d["name"] for d in summary)


LOGIN = [{"event": "Commander", "FID": FID, "Name": "Tester"},
         {"event": "LoadGame", "FID": FID, "Commander": "Tester"}]
OLD, GAP = 7001, 7002
DIED = "2026-07-11T19:20:06Z"
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
    path = os.path.join(d, "p.sqlite")
    db = SystemDB(path)
    db.set_meta(sysdb.CMDR_READY, "2026-07-01T00:00:00Z")
    old = [dict(LOGIN[0], timestamp="2026-07-11T18:00:00Z"), dict(LOGIN[1], timestamp="2026-07-11T18:00:01Z"),
           {"event": "FSDJump", "StarSystem": "Old Sys", "SystemAddress": OLD, "StarPos": [1.0, 0.0, 0.0],
            "timestamp": "2026-07-11T18:10:00Z"}]
    old += [scan("Old Sys", OLD, b, "2026-07-11T18:1%d:00Z" % b) for b in (1, 2, 3, 4)]
    old += [{"event": "Died", "timestamp": DIED},
            {"event": "Resurrect", "Option": "rebuy", "timestamp": "2026-07-11T19:25:00Z"}]
    write(os.path.join(d, "Journal.2026-07-11T180000.01.log"), old)
    db.import_journals(d)
    check(lost_names(db.lost_summary(FID)) == ["Old Sys"], "the real crash of 11.07.: Old Sys lost")

    # 22.11., live (EDMC); 5.0.0 kept no open_ts
    db.ingest_journal_event(dict(LOGIN[0], timestamp="2026-11-22T16:41:28Z"))
    db.ingest_journal_event(dict(LOGIN[1], timestamp="2026-11-22T16:41:30Z"))
    db.ingest_journal_event({"event": "FSDJump", "StarSystem": "Gap Sys", "SystemAddress": GAP,
                             "StarPos": [2.0, 0.0, 0.0], "timestamp": "2026-11-22T17:00:00Z"})
    for b in (1, 2, 3, 4):
        db.ingest_journal_event(scan("Gap Sys", GAP, b, "2026-11-22T17:0%d:00Z" % b))
    db.ingest_journal_event({"event": "SAAScanComplete", "SystemAddress": GAP, "BodyName": "Gap Sys 2",
                             "BodyID": 2, "timestamp": "2026-11-22T17:10:00Z"})
    db.ingest_journal_event({"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": GAP, "Body": 3,
                             "Genus_Localised": "Bacterium", "Species_Localised": "Bacterium Tela",
                             "timestamp": "2026-11-22T17:20:00Z"})
    db.cx.execute("UPDATE cmdr_bodies SET open_ts=NULL WHERE sys_id64=? AND body_id IN (1,2,3)", (GAP,))
    db.cx.execute("UPDATE systems SET body_count=4 WHERE id64=?", (GAP,))
    db.ingest_journal_event({"event": "FSSAllBodiesFound", "SystemName": "Gap Sys", "SystemAddress": GAP,
                             "Count": 4, "timestamp": "2026-11-22T17:30:00Z"})
    # the 5.0.0 replay of the old death: it took every open row, whatever its age
    with mock.patch.object(sysdb, "LIVE_DIED_S", 1e12):
        db.ingest_journal_event({"event": "Died", "timestamp": DIED})
    gap = rows(db, GAP)
    check(all(gap[b]["lost_what"] for b in (1, 2, 3)) and not gap[4]["lost_what"],
          "5.0.0 picture: three Gap Sys bodies marked lost by the death of 11.07.")
    db.ingest_journal_event({"event": "MultiSellExplorationData", "Discovered": [{"SystemName": "Gap Sys"}],
                             "timestamp": "2026-11-22T20:07:25Z"})
    db.ingest_journal_event({"event": "SellOrganicData", "BioData": [{"Species_Localised": "Bacterium Tela",
                             "Value": 1000, "Bonus": 0}], "timestamp": "2026-11-22T20:09:07Z"})
    check(lost_names(db.lost_summary(FID)) == ["Gap Sys", "Old Sys"], "... and they stay lost after the sale")
    # a mark no death made: a minute the journal has, without a Died
    db.cx.execute("INSERT INTO cmdr_bodies(fid, sys_id64, body_id, lost_what, lost_ts) "
                  "VALUES (?, ?, 9, '[\"scan\"]', '2026-07-11T19:25:00Z')", (FID, OLD))
    db.cx.commit()
    db.cx.close()

    # the next start
    db = SystemDB(path)
    check(db.lost_taken_back == 3, "start: 3 false loss marks taken back (%d)" % db.lost_taken_back)
    gap = rows(db, GAP)
    check(all(not gap[b]["lost_what"] and gap[b]["scanned"] == 1 for b in (1, 2, 3)), "Gap Sys scanned again")
    check(gap[2]["mapped"] == 1 and gap[2]["map_sold"] == 1, "the map is back, and sold")
    check(all(gap[b]["scan_sold"] == 1 and gap[b]["scan_open"] == 0 for b in (1, 2, 3)),
          "the later sale of the system counts")
    sp = [x["species"] for x in json.loads(gap[3]["bio_species"] or "[]")]
    check(sp == ["Bacterium Tela"] and not gap[3]["bio_open"], "the species is analysed again, and sold")
    cs = db.cx.execute("SELECT lost_ts, fss_complete FROM cmdr_systems WHERE fid=? AND sys_id64=?",
                       (FID, GAP)).fetchone()
    check(cs["lost_ts"] is None and cs["fss_complete"] == 1, "the system's own loss mark goes, FSS complete")
    old_rows = rows(db, OLD)
    check(all(json.loads(old_rows[b]["lost_what"] or "[]") == ["scan"] for b in (1, 2, 3, 4)),
          "the real crash stays")
    check(rows(db, OLD)[9]["lost_what"], "a start alone does not judge the mark without a death")
    check(lost_names(db.lost_summary(FID)) == ["Old Sys"], "plugin LOST DATA: Old Sys only")
    check(lost_names(Database(path).lost_summary(FID)) == ["Old Sys"], "FIS LOST DATA agrees")
    db.cx.close()
    db = SystemDB(path)
    db.ingest_journal_event(dict(LOGIN[0], timestamp="2026-11-23T10:00:00Z"))
    check(db.lost_taken_back == 0, "the next start finds nothing more")

    # "Replay journals": the minute 19:25 is in the journal, without a death
    ST.db, ST.lock, ST.active = db, threading.RLock(), False
    maintenance._journal_dir = lambda: d
    maintenance._import_journals()
    check(not rows(db, OLD)[9]["lost_what"], "replay: the mark no death made goes")
    check("1 false loss mark taken back" in ST.status, "panel: %r" % ST.status)
    check(maintenance.lost_back_text(26) == "26 false loss marks taken back", "panel text for 26")
    old_rows = rows(db, OLD)
    check(all(old_rows[b]["lost_what"] for b in (1, 2, 3, 4)), "the real crash still stays after the replay")
    check(not any(r["lost_what"] for r in rows(db, GAP).values()), "Gap Sys stays clean after the replay")

    # a real death now still counts - after a start and a replay too
    now = time.time()
    live = [scan("Gap Sys", GAP, 5, iso(now - 60)), {"event": "Died", "timestamp": iso(now)}]
    for e in live:
        db.ingest_journal_event(e)
    write(os.path.join(d, "Journal.%s.01.log" % time.strftime("%Y-%m-%dT%H%M%S", time.gmtime(now - 120))),
          [dict(LOGIN[0], timestamp=iso(now - 120))] + live)
    check(json.loads(rows(db, GAP)[5]["lost_what"] or "[]") == ["scan"], "a real death now: the open scan is lost")
    db.cx.close()
    db = SystemDB(path)
    db.ingest_journal_event(dict(LOGIN[0], timestamp=iso(now + 1)))
    check(db.lost_taken_back == 0 and rows(db, GAP)[5]["lost_what"], "... it stays after a start")
    ST.db = db
    res = db.import_journals(d)
    check(res["false_losses"] == 0 and rows(db, GAP)[5]["lost_what"], "... and after a replay")
    db.cx.close()

print("false losses: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
