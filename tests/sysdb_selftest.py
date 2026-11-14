# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of sysdb.py (moved from the module in 4.12, N7 - verbatim).

    python tests/sysdb_selftest.py      (from the plugin folder)
"""
import glob
import json
import logging
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.sysdb import (BACKUP_KEEP, CALL_LOG_DAYS, CMDR_READY, CURRENT, INHABITED,  # noqa: E402
                               Q_JOURNAL, REPAIRS, SCHEMA_VERSION, SystemDB, backup_database,
                               stored_state)


def _selftest() -> int:
    """Backup before migration: new file no backup, current file no backup,
    old schema or missing repair -> one backup, only the newest kept."""
    import tempfile
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "shboxsearch.sqlite")
        baks = lambda: glob.glob(glob.escape(path) + ".*.bak")   # noqa: E731
        db = SystemDB(path)
        check(db.backup_path is None, "new database: no backup")
        db.close()
        db = SystemDB(path)
        check(db.backup_path is None and not baks(), "current database: no backup")
        db.cx.execute("UPDATE meta SET v='2' WHERE k='schema'")
        db.cx.commit()
        db.close()
        db = SystemDB(path)
        check(db.backup_path is not None and len(baks()) == 1,
              "older schema: one backup")
        old = sqlite3.connect(db.backup_path)
        check(old.execute("SELECT v FROM meta WHERE k='schema'").fetchone()[0] == "2",
              "backup holds the state before the migration")
        old.close()
        check(stored_state(path) == (SCHEMA_VERSION, set(REPAIRS)),
              "migrated database is current")
        db.cx.execute("DELETE FROM meta WHERE k='fix_n1zero'")
        db.cx.commit()
        db.close()
        db = SystemDB(path)
        check(db.backup_path is not None and "fix_n1zero" in stored_state(path)[1],
              "pending repair: backup, then repair runs")
        db.close()
        for _ in range(4):
            backup_database(path, "test")
        check(len(baks()) == BACKUP_KEEP, "only the newest %d backups kept" % BACKUP_KEEP)
        db = SystemDB(path)
        now = time.time()
        db.log_external_calls([(now - 40 * 86400, "edsm", "sphere", 200, True, 50),
                               (now, "edsm", "sphere", 429, False, 30),
                               (now, "spansh", "search", 200, True, 900)])
        check(db.external_calls_since(now - 60) == 2
              and db.external_calls_since(now - 60, "edsm") == 1,
              "call log counts per service")
        check(db.prune_external_calls() == 1 and db.external_calls_since(0) == 2,
              "call log keeps %d days" % CALL_LOG_DAYS)
        db.record_shell("edsm", (1, 2, 3), 0, 25, 40, 5 * 86400, now=now)
        db.record_shell("edsm", (1, 2, 3), 25, 50, 90, 10, now=now - 86400)
        db.record_shell("spansh", (1, 2, 3), 0, 25, 41, 9 * 86400, now=now)
        check(db.valid_shells("edsm", now) == [(1.0, 2.0, 3.0, 0.0, 25.0)]
              and len(db.valid_shells("spansh", now)) == 1,
              "fetched shells: valid ones per service, expired ones not")
        db.close()
        legacy = os.path.join(d, "legacy.sqlite")
        cx = sqlite3.connect(legacy)
        cx.execute("CREATE TABLE systems (name TEXT)")
        cx.commit()
        cx.close()
        check(stored_state(legacy) == (0, set()), "database without meta = schema 0")
        db = SystemDB(os.path.join(d, "carrier.sqlite"))
        db.ingest_journal_event({"event": "Docked", "StationType": "FleetCarrier",
                                 "StationName": "ZZZ-001", "MarketID": 1001,
                                 "StarSystem": "Test Alpha", "SystemAddress": 11})
        check(db.get_carrier() is None, "docking at a stranger's carrier: no own carrier")
        db.ingest_journal_event({"event": "CarrierLocation", "CarrierType": "FleetCarrier",
                                 "CarrierID": 2002, "StarSystem": "Test Home",
                                 "SystemAddress": 22})
        db.ingest_journal_event({"event": "CarrierStats", "CarrierID": 2002,
                                 "Callsign": "OWN-002", "Name": "TEST OWN"})
        db.ingest_journal_event({"event": "Docked", "StationType": "FleetCarrier",
                                 "StationName": "ZZZ-001", "MarketID": 1001,
                                 "StarSystem": "Test Alpha", "SystemAddress": 11})
        db.ingest_journal_event({"event": "Disembark", "OnStation": True})
        db.ingest_journal_event({"event": "CarrierJump", "OnFoot": True, "Docked": False,
                                 "StarSystem": "Test Beta", "SystemAddress": 33,
                                 "StarPos": [1.0, 2.0, 3.0]})
        c = db.get_carrier()
        check(c and c["system"] == "Test Home" and c["callsign"] == "OWN-002",
              "stranger's carrier (docked, jump on foot) leaves the own carrier alone")
        db.ingest_journal_event({"event": "Undocked"})
        db.ingest_journal_event({"event": "Docked", "StationType": "FleetCarrier",
                                 "StationName": "OWN-002", "MarketID": 2002,
                                 "StarSystem": "Test Home", "SystemAddress": 22})
        db.ingest_journal_event({"event": "CarrierJump", "OnFoot": True, "Docked": False,
                                 "StarSystem": "Test Gamma", "SystemAddress": 44,
                                 "StarPos": [4.0, 5.0, 6.0]})
        check(db.get_carrier()["system"] == "Test Gamma", "own carrier jump while aboard counts")
        db.ingest_journal_event({"event": "FSDJump", "StarSystem": "Test Town",
                                 "SystemAddress": 55, "StarPos": [7.0, 8.0, 9.0],
                                 "Population": 4200, "Factions": [{"Name": "F"}]})
        db.ingest_journal_event({"event": "FSDJump", "StarSystem": "Test Void",
                                 "SystemAddress": 66, "StarPos": [9.0, 8.0, 7.0],
                                 "Population": 0})
        db.ingest_journal_event({"event": "Docked", "StationType": "Coriolis",
                                 "StationName": "Port", "MarketID": 77,
                                 "StarSystem": "Test Port", "SystemAddress": 77})
        src = lambda nm: set(((db.system(nm) or {"sources": ""})["sources"] or "").split(","))  # noqa: E731
        check(INHABITED in src("Test Town") and INHABITED not in src("Test Void")
              and INHABITED in src("Test Port") and INHABITED not in src("Test Alpha"),
              "I1: population/factions/station marks 'inhabited', empty system and carrier not")
        check(db.system("Test Town")["quality"] == Q_JOURNAL and db.system("Test Town")["x"] == 7.0,
              "I1: marking keeps the journal position")
        nb = {"event": "Scan", "ScanType": "NavBeaconDetail", "StarSystem": "Test Town",
              "SystemAddress": 55, "BodyName": "Test Town 1", "BodyID": 1,
              "PlanetClass": "Rocky body", "DistanceFromArrivalLS": 10.0,
              "WasDiscovered": True, "WasMapped": False}
        db.ingest_journal_event(nb)
        own = dict(nb, ScanType="Detailed", BodyName="Test Town 2", BodyID=2)
        db.ingest_journal_event(own)
        db.ingest_journal_event(dict(own, ScanType="NavBeaconDetail"))
        b = {r["body_id"]: r for r in db.bodies_of(55)}
        check(b[1]["planet_class"] == "Rocky body" and b[1]["was_discovered"] == 1
              and not b[1]["scanned"] and b[2]["scanned"] == 1,
              "NavBeaconDetail: body data stored, not counted as your scan (an own scan stays)")
        ev = db.ingest_journal_event
        ev({"event": "FSDJump", "StarSystem": "Cm Belt", "SystemAddress": 590,
            "StarPos": [2.0, 0.0, 0.0], "timestamp": "2026-01-05T11:00:00Z"})
        ev({"event": "FSSDiscoveryScan", "SystemName": "Cm Belt", "SystemAddress": 590,
            "BodyCount": 3, "NonBodyCount": 0, "Progress": 0.3})
        ev({"event": "Scan", "ScanType": "AutoScan", "StarSystem": "Cm Belt", "SystemAddress": 590,
            "BodyName": "Cm Belt A", "BodyID": 0, "StarType": "K", "DistanceFromArrivalLS": 0.0})
        for i in range(3):
            ev({"event": "Scan", "ScanType": "Detailed", "StarSystem": "Cm Belt", "SystemAddress": 590,
                "BodyName": "Cm Belt A A Belt Cluster %d" % (i + 1), "BodyID": 10 + i,
                "DistanceFromArrivalLS": 5.0})
        ev({"event": "Scan", "ScanType": "Detailed", "StarSystem": "Cm Belt", "SystemAddress": 590,
            "BodyName": "Cm Belt A 1", "BodyID": 2, "PlanetClass": "Icy body", "DistanceFromArrivalLS": 90.0})
        pb = db.system_progress(590, None)
        check(pb["scanned"] == 2 and pb["body_count"] == 3,
              "belt clusters are not in BodyCount: 2 of 3 scanned, not 5 (%s/%s)" % (pb["scanned"], pb["body_count"]))
        check(any(u["name"] == "Cm Belt" for u in db.unfinished_systems((2.0, 0.0, 0.0), 1.0)),
              "a system with a planet left is still open, whatever the belts")
        db.close()
        n_cmdr = _selftest_cmdr(d, check)
        fails += n_cmdr
    print("failures: %d" % fails)
    return fails


def _selftest_cmdr(d: str, check) -> int:
    """C1: exploration per commander, knowledge shared, main commander,
    and an upgraded database falls back to the shared view until replayed."""
    db = SystemDB(os.path.join(d, "cmdr.sqlite"))
    check(db.cmdr_ready(), "C1: a new database is per-commander from the start")
    ev = db.ingest_journal_event
    ev({"event": "Commander", "FID": "F1", "Name": "Main", "timestamp": "2026-01-01T10:00:00Z"})
    ev({"event": "LoadGame", "FID": "F1", "Commander": "Main", "timestamp": "2026-01-01T10:00:01Z"})
    ev({"event": "CarrierStats", "CarrierID": 9, "Callsign": "OWN-009", "Name": "C"})
    ev({"event": "FSDJump", "StarSystem": "Cm Alpha", "SystemAddress": 501,
        "StarPos": [1.0, 0.0, 0.0], "timestamp": "2026-01-01T10:01:00Z"})
    scan = {"event": "Scan", "ScanType": "Detailed", "StarSystem": "Cm Alpha",
            "SystemAddress": 501, "BodyName": "Cm Alpha 1", "BodyID": 1,
            "PlanetClass": "Water world", "DistanceFromArrivalLS": 10.0,
            "WasDiscovered": False, "WasMapped": False}
    ev(scan)
    ev({"event": "SAAScanComplete", "SystemAddress": 501, "BodyID": 1, "BodyName": "Cm Alpha 1"})
    ev({"event": "FSSBodySignals", "SystemAddress": 501, "BodyID": 1, "BodyName": "Cm Alpha 1",
        "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 2}]})
    ev({"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 501, "Body": 1,
        "Species_Localised": "Bacterium Aurasus", "Genus_Localised": "Bacterium",
        "timestamp": "2026-01-01T10:20:00Z"})
    ev({"event": "FSSAllBodiesFound", "SystemName": "Cm Alpha", "SystemAddress": 501, "Count": 1})
    for i in range(3):
        ev({"event": "LoadGame", "FID": "F2", "Commander": "Second",
            "timestamp": "2026-01-0%dT10:00:00Z" % (i + 2)})
    ev({"event": "Location", "StarSystem": "Cm Alpha", "SystemAddress": 501,
        "StarPos": [1.0, 0.0, 0.0], "timestamp": "2026-01-05T10:00:00Z"})
    check(db.fid == "F2" and db.commander_name("F1") == "Main", "C1: FID follows LoadGame")
    p2 = db.system_progress(501, CURRENT)
    p1 = db.system_progress(501, "F1")
    check(p1["mapped"] == 1 and p1["fss_complete"] and p1["bio_signals_open"] == 1
          and p1["new_discoveries"] == 1, "C1: the first commander's own state")
    check(p2["scanned"] == 0 and p2["mapped"] == 0 and not p2["fss_complete"]
          and p2["dss_open"] == ["Cm Alpha 1"] and p2["bio_open"] == ["Cm Alpha 1"]
          and p2["bio_signals_open"] == 2,
          "C1: the second commander still has the work (FSS, DSS, both bio signals)")
    rows = {r["body_id"]: r for r in db.bodies_for(501, "F2")}
    check(rows[1]["planet_class"] == "Water world" and rows[1]["sig_bio"] == 2,
          "C1: knowledge (class, signals) is shared")
    check(len(db.bio_training_rows()) == 1, "C1: the bio model learns from every commander")
    check(db.suggest_main() == "F1", "C1: suggestion = the commander with a carrier (not most logins)")
    db.cx.execute("UPDATE commanders SET carrier=0")
    check(db.suggest_main() == "F2", "C1: without a carrier the one with most sessions")
    check(db.set_main_commander("F1") == "F1" and db.get_meta("main_fid") == "F1",
          "C1: the main commander is stored for the FIS")
    sp = db.sphere((0.0, 0.0, 0.0), 5.0)
    check(len(sp) == 1 and sp[0]["visited"] == 1 and sp[0]["fss_complete"] == 1,
          "C1: the survey sphere plans for the main commander")
    lt = db.lifetime()
    check(lt["commander"] == "Main" and lt["first_discoveries"] == 1 and lt["bio_sampled"] == 1
          and lt["also"] == [("Second", 1)], "C1: statistics of the main commander, 'also by'")
    check(db.explorers(501, but="F1") == ["Second"], "C1: also explored by")
    jd = os.path.join(d, "journals")
    os.makedirs(jd)
    for i, (fid, nm, sa) in enumerate((("F7", "Seven", 701), ("F8", "Eight", 702))):
        with open(os.path.join(jd, "Journal.2026-01-0%dT100000.01.log" % (i + 1)), "w",
                  encoding="utf-8") as fh:
            for e in ({"event": "Fileheader"},
                      {"event": "Commander", "FID": fid, "Name": nm,
                       "timestamp": "2026-01-0%dT10:00:00Z" % (i + 1)},
                      {"event": "FSDJump", "StarSystem": "Cm R%d" % i, "SystemAddress": sa,
                       "StarPos": [5.0, 5.0, float(i)], "timestamp": "2026-01-0%dT10:05:00Z" % (i + 1)}):
                fh.write(json.dumps(e) + "\n")
    db.set_commander("F9", "Live")
    db.import_journals(jd)
    check(db.fid == "F9" and db.explorers(701) == ["Seven"] and db.explorers(702) == ["Eight"],
          "C1: a replay files each journal under its own commander, the live one stays")
    # R3: Second rides along on a carrier into Cm Beta (never explored)
    db.set_commander("F2", "Second")
    ev({"event": "CarrierJump", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Beta", "SystemAddress": 502, "StarPos": [2.0, 0.0, 0.0],
        "Body": "Cm Beta 3", "BodyID": 7, "BodyType": "Planet",
        "timestamp": "2026-01-06T10:00:00Z"})
    check(db.route_start("F2", 502) == (7, "Cm Beta 3"), "R3: carrier jump into an unexplored system")
    ev(dict(scan, StarSystem="Cm Beta", SystemAddress=502, BodyName="Cm Beta 3", BodyID=7,
            timestamp="2026-01-06T10:05:00Z"))
    ev({"event": "CarrierJump", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Beta", "SystemAddress": 502, "StarPos": [2.0, 0.0, 0.0],
        "Body": "Cm Beta 3", "BodyID": 7, "BodyType": "Planet",
        "timestamp": "2026-01-06T10:00:00Z"})
    check(db.route_start("F2", 502) == (7, "Cm Beta 3"), "R3: a replay keeps the decision")
    ev({"event": "Location", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Beta", "SystemAddress": 502, "StarPos": [2.0, 0.0, 0.0],
        "Body": "Cm Beta 3", "BodyID": 7, "timestamp": "2026-01-07T10:00:00Z"})
    check(db.route_start("F2", 502) is None, "R3: explored meanwhile -> later routes at the main star")
    ev({"event": "Location", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Gamma", "SystemAddress": 503, "StarPos": [3.0, 0.0, 0.0],
        "Body": "Cm Gamma 1", "BodyID": 4, "timestamp": "2026-01-08T10:00:00Z"})
    check(db.route_start("F2", 503) == (4, "Cm Gamma 1"), "R3: loading docked at a carrier, unexplored")
    ev({"event": "FSDJump", "StarSystem": "Cm Gamma", "SystemAddress": 503,
        "StarPos": [3.0, 0.0, 0.0], "timestamp": "2026-01-09T10:00:00Z"})
    check(db.route_start("F2", 503) is None, "R3: arriving by FSD -> main star")
    check(db.route_start("F1", 502) is None, "R3: per commander")
    db.cx.execute("DELETE FROM meta WHERE k=?", (CMDR_READY,))
    check(db.system_progress(501, CURRENT)["mapped"] == 1,
          "C1: not replayed yet -> shared view (anyone)")
    # crash: F1 scans Cm Delta 1 (sold), Cm Delta 2 and a species (not sold) - then dies
    db.set_commander("F1", "Main")
    ev({"event": "FSDJump", "StarSystem": "Cm Delta", "SystemAddress": 504,
        "StarPos": [4.0, 0.0, 0.0], "timestamp": "2026-02-01T10:00:00Z"})
    for bid in (1, 2):
        ev(dict(scan, StarSystem="Cm Delta", SystemAddress=504, BodyName="Cm Delta %d" % bid,
                BodyID=bid, timestamp="2026-02-01T10:0%d:00Z" % bid))
    ev({"event": "MultiSellExplorationData", "Discovered": [{"SystemName": "Cm Delta"}],
        "timestamp": "2026-02-01T10:05:00Z"})
    ev({"event": "SAAScanComplete", "SystemAddress": 504, "BodyID": 2, "BodyName": "Cm Delta 2"})
    ev({"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 504, "Body": 2,
        "Species_Localised": "Stratum Tectonicas", "timestamp": "2026-02-01T10:20:00Z"})
    ev({"event": "Scan", "ScanType": "Detailed", "StarSystem": "Cm Delta", "SystemAddress": 504,
        "BodyName": "Cm Delta 3", "BodyID": 3, "PlanetClass": "Icy body",
        "timestamp": "2026-02-01T10:21:00Z"})
    db.set_route_done(504, 2, True)
    db.cx.execute("UPDATE bodies SET route_done_ts='2026-02-01T10:25:00Z' WHERE sys_id64=504")
    ev({"event": "Died", "timestamp": "2026-02-01T10:30:00Z"})
    check(db.route_done_of(504) == set(), "crash: route ticks of the lost work are cleared")
    b = {r["body_id"]: r for r in db.bodies_for(504, "F1")}
    check(b[1]["scanned"] == 1 and not b[1]["lost_what"], "crash: sold data stays")
    check(b[2]["scanned"] == 1 and b[2]["mapped"] == 0 and b[2]["organics"] == 0
          and json.loads(b[2]["lost_what"]) == ["bio:Stratum Tectonicas", "map"],
          "crash: unsold map and species undone and marked lost (sold scan stays)")
    check(b[3]["scanned"] == 0 and json.loads(b[3]["lost_what"]) == ["scan"],
          "crash: unsold scan undone and marked lost")
    lost = {d["name"]: d for d in db.lost_summary("F1")}
    check(lost["Cm Delta"]["bio"] == ["Stratum Tectonicas"] and lost["Cm Delta"]["scan"] == 1
          and "Cm Alpha" in lost,              # scanned there earlier, never sold
          "crash: lost summary per system")
    check(db.lost_of_body("F1", 504, 2) == ["bio:Stratum Tectonicas", "map"]
          and db.lost_of_body("F1", 504, 1) == [] and db.lost_of_body(None, 504, 2) == []
          and db.lost_of_body("F2", 504, 2) == [],
          "crash: lost marks of one body, for that commander only")
    check(db.bio_training_rows() and any("Tectonicas" in (r["bio_species"] or "")
                                         for r in db.bio_training_rows()),
          "crash: the shared knowledge (bio model) keeps what was found")
    ev({"event": "SAAScanComplete", "SystemAddress": 504, "BodyID": 2, "BodyName": "Cm Delta 2"})
    ev({"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 504, "Body": 2,
        "Species_Localised": "Stratum Tectonicas", "timestamp": "2026-02-02T10:20:00Z"})
    b = {r["body_id"]: r for r in db.bodies_for(504, "F1")}
    check(not b[2]["lost_what"] and b[2]["mapped"] == 1, "crash: redone -> no longer marked")
    db.cx.execute("UPDATE meta SET v='4' WHERE k='schema'")
    db.cx.commit()
    db.close()
    db = SystemDB(os.path.join(d, "cmdr.sqlite"))
    check(db.backup_path is not None and not db.cmdr_ready()
          and db.cx.execute("SELECT COUNT(*) FROM cmdr_bodies").fetchone()[0] >= 1,
          "C1: schema 4 -> 5 makes a backup, keeps the data, waits for the replay")
    db.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(1 if _selftest() else 0)
