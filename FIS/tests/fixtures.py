# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Synthetic test database with the plugin's schema (columns the FIS reads).

Independent of the real data, so the tests also run without the copy in
tests/data/. Tests that need real systems (HIP 31189 ...) skip without it.
"""

import json
import os
import sqlite3
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_DB = os.path.join(HERE, "data", "shboxsearch.sqlite")
_FIS = os.path.dirname(HERE)
_UP = os.path.dirname(_FIS)
# FIS lives in the plugin (SHBOXSEARCH/FIS) - its maths comes from the parent
PLUGIN_DIR = _UP if os.path.exists(os.path.join(_UP, "load.py")) else os.path.join(_UP, "SHBOXSEARCH")

SCHEMA = """
CREATE TABLE systems (name TEXT PRIMARY KEY, id64 INTEGER, x REAL, y REAL, z REAL,
  quality INTEGER DEFAULT 0, source TEXT, star_class TEXT, visited INTEGER DEFAULT 0,
  visited_ts TEXT, body_count INTEGER, nonbody_count INTEGER, fss_complete INTEGER DEFAULT 0,
  first_seen TEXT, updated TEXT, sources TEXT);
CREATE TABLE bodies (sys_id64 INTEGER, body_id INTEGER, name TEXT, kind TEXT,
  planet_class TEXT, terraform TEXT, landable INTEGER, was_discovered INTEGER,
  was_mapped INTEGER, scanned INTEGER DEFAULT 0, mapped INTEGER DEFAULT 0,
  sig_bio INTEGER DEFAULT 0, sig_geo INTEGER DEFAULT 0, organics INTEGER DEFAULT 0,
  genuses TEXT, updated TEXT, arrival_ls REAL, parent_id INTEGER, sma REAL, ecc REAL,
  inc REAL, peri REAL, node REAL, mean_anom REAL, period REAL, ring_classes TEXT,
  ring_mass REAL, star_type TEXT, scan_ts REAL, route_done INTEGER DEFAULT 0,
  route_done_ts TEXT, radius REAL, mass_em REAL, gravity REAL, temp_k REAL,
  pressure REAL, atmosphere TEXT, atmo_type TEXT, atmo_comp TEXT, volcanism TEXT,
  composition TEXT, materials TEXT, tidal_lock INTEGER, axial_tilt REAL, rotation REAL,
  was_footfalled INTEGER, rings_json TEXT, reserve TEXT, stellar_mass REAL,
  abs_mag REAL, age_my REAL, luminosity TEXT, subclass INTEGER, bio_species TEXT,
  PRIMARY KEY (sys_id64, body_id));
CREATE TABLE absent (name TEXT PRIMARY KEY, boxel TEXT, n2 INTEGER, ts TEXT);
CREATE TABLE boxels (key TEXT PRIMARY KEY, sector TEXT, mc INTEGER, n2_max INTEGER,
  n2_end INTEGER, complete INTEGER DEFAULT 0, updated TEXT);
CREATE TABLE survey (id INTEGER PRIMARY KEY, active INTEGER DEFAULT 0, start_system TEXT,
  cx REAL, cy REAL, cz REAL, radius REAL, masscodes TEXT, started TEXT, updated TEXT);
CREATE TABLE spheres (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, cx REAL, cy REAL,
  cz REAL, radius REAL, origin TEXT, started TEXT, closed TEXT);
CREATE TABLE hotspots (sys_id64 INTEGER, body_id INTEGER, body_name TEXT, material TEXT,
  label TEXT, count INTEGER, ring_class TEXT, found TEXT,
  PRIMARY KEY (sys_id64, body_id, material));
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE fetched_shells (id INTEGER PRIMARY KEY, service TEXT NOT NULL, cx REAL NOT NULL,
  cy REAL NOT NULL, cz REAL NOT NULL, r_min REAL NOT NULL, r_max REAL NOT NULL,
  fetched_at REAL NOT NULL, expires_at REAL NOT NULL, systems INTEGER NOT NULL DEFAULT 0);
"""

SYS = "Testia AB-C d1-5"
SYS_ID = 1000001
NEXT = "Testia AB-C d1-6"
NEXT_ID = 1000002
LS = 299792458.0


def _body(cx, **kw):
    cols = ", ".join(kw)
    cx.execute("INSERT INTO bodies (%s) VALUES (%s)" % (cols, ",".join("?" * len(kw))),
               tuple(kw.values()))


def make_db(path=None):
    """Create the synthetic database, return its path."""
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".sqlite", prefix="fis-test-")
        os.close(fd)
        os.unlink(path)
    cx = sqlite3.connect(path)
    cx.executescript(SCHEMA)
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("INSERT INTO systems (name,id64,x,y,z,quality,star_class,visited,visited_ts,body_count,"
               "fss_complete,sources) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (SYS, SYS_ID, 100.0, -20.0, 50.0, 40, "K", 1, "2026-11-04T20:00:00Z", 4, 1,
                "journal,fss,scan"))
    cx.execute("INSERT INTO systems (name,id64,x,y,z,quality,star_class,visited,body_count,sources) "
               "VALUES (?,?,?,?,?,?,?,?,?,?)",
               (NEXT, NEXT_ID, 103.0, -20.0, 54.0, 30, "M", 0, 12, "EDSM,navroute"))
    # I1: EDSM delivered 0-50 ly around the test system (valid for a long time)
    cx.execute("INSERT INTO fetched_shells (service,cx,cy,cz,r_min,r_max,fetched_at,expires_at,"
               "systems) VALUES ('edsm',100.0,-20.0,50.0,0.0,50.0,0,4102444800,2)")
    # star at the origin
    _body(cx, sys_id64=SYS_ID, body_id=0, name=SYS + " A", kind="Star", star_type="K",
          arrival_ls=0.0, radius=6.0e8, stellar_mass=0.8, subclass=3, luminosity="Va",
          was_discovered=0, scanned=1, temp_k=4800.0, rotation=200000.0)
    # planet 1: landable, bio, undiscovered, orbit 500 LS
    _body(cx, sys_id64=SYS_ID, body_id=1, name=SYS + " 1", kind="Planet",
          planet_class="Rocky body", landable=1, was_discovered=0, was_mapped=0,
          was_footfalled=0, scanned=1, sig_bio=2, arrival_ls=500.0, parent_id=0,
          sma=500.0 * LS, ecc=0.01, inc=1.0, peri=10.0, node=20.0, mean_anom=30.0,
          period=8.0e7, radius=2.0e6, gravity=2.5, temp_k=180.0, pressure=1500.0,
          atmosphere="thin carbon dioxide atmosphere", atmo_type="CarbonDioxide",
          atmo_comp=json.dumps({"CarbonDioxide": 99.0, "SulphurDioxide": 1.0}),
          volcanism="", composition=json.dumps({"Rock": 0.9, "Metal": 0.1}),
          materials=json.dumps({"iron": 20.0, "nickel": 15.0}), tidal_lock=1,
          axial_tilt=0.5, rotation=86400.0 * 3, mass_em=0.2)
    # moon 1 a of planet 1
    _body(cx, sys_id64=SYS_ID, body_id=2, name=SYS + " 1 a", kind="Planet",
          planet_class="Icy body", landable=1, was_discovered=1, was_mapped=1,
          scanned=1, arrival_ls=501.0, parent_id=1, sma=1.0 * LS, ecc=0.0, inc=0.0,
          peri=0.0, node=0.0, mean_anom=0.0, period=1.0e6, radius=5.0e5, gravity=0.5)
    # planet 2: ringed gas giant far out, nothing to do
    _body(cx, sys_id64=SYS_ID, body_id=3, name=SYS + " 2", kind="Planet",
          planet_class="Sudarsky class I gas giant", landable=0, was_discovered=1,
          was_mapped=1, scanned=1, arrival_ls=3000.0, parent_id=0, sma=3000.0 * LS,
          ecc=0.0, inc=0.0, peri=0.0, node=0.0, mean_anom=180.0, period=3.0e8,
          radius=7.0e7, ring_classes="eRingClass_Icy",
          rings_json=json.dumps([{"name": SYS + " 2 A Ring", "cls": "Icy", "mass": 1e10,
                                  "inner": 9.0e7, "outer": 1.4e8}]))
    # training row for biopredict (another system)
    _body(cx, sys_id64=999, body_id=5, name="Other 5", kind="Planet",
          planet_class="Rocky body", landable=1, sig_bio=1, organics=1, gravity=2.4,
          temp_k=175.0, atmo_type="CarbonDioxide", genuses="Bacterium",
          bio_species=json.dumps([{"species": "Bacterium Aurasus", "genus": "Bacterium",
                                   "variant": "Bacterium Aurasus - Teal"}]))
    cx.execute("INSERT INTO boxels VALUES (?,?,?,?,?,?,?)",
               ("Testia AB-C d1", "Testia", 3, 9, 9, 0, "2026-11-04T20:00:00Z"))
    cx.execute("INSERT INTO absent VALUES (?,?,?,?)", ("Testia AB-C d1-7", "Testia AB-C d1", 7, "x"))
    cx.execute("INSERT INTO survey VALUES (1,1,?,?,?,?,?,?,?,?)",
               (SYS, 100.0, -20.0, 50.0, 30.0, "0,1,2,3", "2026-11-01T00:00:00Z", "2026-11-04T00:00:00Z"))
    cx.execute("INSERT INTO spheres (label,cx,cy,cz,radius,origin,started) VALUES (?,?,?,?,?,?,?)",
               (SYS, 100.0, -20.0, 50.0, 30.0, "free", "2026-11-01T00:00:00Z"))
    cx.execute("INSERT INTO meta VALUES ('schema','3')")
    cx.commit()
    cx.close()
    return path


def journal_lines():
    """A short journal: load, loadout, jump into SYS, target NEXT."""
    return [
        {"timestamp": "2026-11-04T20:00:00Z", "event": "LoadGame", "Commander": "Test",
         "Ship": "explorer_nx", "ShipName": "TESTHAWK", "ShipIdent": "TT-001",
         "FuelLevel": 150.0, "FuelCapacity": 176.0},
        {"timestamp": "2026-11-04T20:00:01Z", "event": "Loadout", "Ship": "explorer_nx",
         "ShipName": "TESTHAWK", "ShipIdent": "TT-001", "MaxJumpRange": 68.3,
         "HullHealth": 1.0, "FuelCapacity": {"Main": 176.0, "Reserve": 1.14}},
    ] + [
        {"timestamp": "2026-11-04T20:%02d:00Z" % (i + 1), "event": "FSDJump",
         "StarSystem": "Hop %d" % i, "SystemAddress": 500 + i,
         "StarPos": [90.0 + i, -20.0, 50.0], "JumpDist": d, "FuelUsed": u,
         "FuelLevel": 150.0 - i}
        for i, (d, u) in enumerate([(10.0, 0.4), (20.0, 2.6), (30.0, 7.9),
                                    (40.0, 17.0), (50.0, 31.0)])
    ] + [
        {"timestamp": "2026-11-04T20:10:00Z", "event": "StartJump", "JumpType": "Hyperspace",
         "StarSystem": SYS, "SystemAddress": SYS_ID, "StarClass": "K"},
        {"timestamp": "2026-11-04T20:10:20Z", "event": "FSDJump", "StarSystem": SYS,
         "SystemAddress": SYS_ID, "StarPos": [100.0, -20.0, 50.0], "JumpDist": 10.0,
         "FuelUsed": 0.4, "FuelLevel": 140.0, "Body": SYS + " A", "BodyID": 0,
         "BodyType": "Star"},
        {"timestamp": "2026-11-04T20:11:00Z", "event": "FSDTarget", "Name": NEXT,
         "SystemAddress": NEXT_ID, "StarClass": "M", "RemainingJumpsInRoute": 1},
    ]
