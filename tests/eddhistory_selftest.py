# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of eddhistory.py (5.0): older journal lines from EDDiscovery's
archive - read only, never the EDSM key, only what is older than the
journals on disk, from a commander's first login on - and the fuel model
and the tonnes per rock fed with them.

    python tests/eddhistory_selftest.py      (from the plugin folder)
"""
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH import eddhistory  # noqa: E402
from SHBOXSEARCH.journalscan import read_events, replay_fuel_events  # noqa: E402
from SHBOXSEARCH.deepspace import FuelState  # noqa: E402
from SHBOXSEARCH.miningstat import RockYield  # noqa: E402
from SHBOXSEARCH.sysdb import SystemDB  # noqa: E402

LOAD = {"event": "Loadout", "Ship": "explorer_nx", "ShipID": 5, "UnladenMass": 400.0, "FuelCapacity":
        {"Main": 32.0, "Reserve": 0.5}, "MaxJumpRange": 60.0, "CargoCapacity": 0,
        "Modules": [{"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_overcharge_size5_class5"}]}


def ev(ts, name, **kw):
    return dict({"timestamp": ts, "event": name}, **kw)


def rows():
    out = [(1, ev("2021-01-01T09:00:00Z", "FSDJump", JumpDist=1.0, FuelUsed=0.1, FuelLevel=30))]  # before login
    out.append((1, ev("2021-01-01T10:00:00Z", "LoadGame", Commander="ONE", FID="F1", FuelLevel=32,
                      FuelCapacity=32)))
    out.append((1, dict(LOAD, timestamp="2021-01-01T10:00:01Z")))
    lvl = 32.0
    for i in range(6):
        used = 0.5 + 0.1 * i
        lvl -= used
        out.append((1, ev("2021-01-01T10:%02d:00Z" % (10 + i), "FSDJump", JumpDist=20.0 + 5 * i, FuelUsed=used,
                          FuelLevel=lvl, StarPos=[i, 0, 0])))
    out.append((1, ev("2021-01-02T10:00:00Z", "ProspectedAsteroid", Content="$AsteroidMaterialContent_High;",
                      Materials=[{"Name": "Tritium", "Proportion": 30.0}], Remaining=100)))
    for k in range(12):
        out.append((1, ev("2021-01-02T10:01:%02dZ" % k, "MiningRefined", Type="$tritium_name;")))
    out.append((1, ev("2021-01-02T11:00:00Z", "Docked", StationName="X")))
    # the same moment the journal on disk has: newer than its first line, not taken
    out.append((1, ev("2026-11-10T08:00:00Z", "FSDJump", JumpDist=9.0, FuelUsed=0.2, FuelLevel=10)))
    out.append((2, ev("2022-01-01T10:00:00Z", "RefuelAll", Cost=5)))   # a name not asked for
    return out


def make(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Commanders (Id INTEGER PRIMARY KEY, Name TEXT, EdsmApiKey TEXT NOT NULL)")
    con.execute("CREATE TABLE JournalEntries (Id INTEGER PRIMARY KEY AUTOINCREMENT, CommanderId INTEGER, "
                "EventType TEXT, EventTime DATETIME, EventData TEXT)")
    con.executemany("INSERT INTO Commanders VALUES (?, ?, ?)", [(1, "ONE", "secret-1"), (2, "TWO", "secret-2")])
    con.executemany("INSERT INTO JournalEntries (CommanderId, EventType, EventTime, EventData) VALUES (?, ?, ?, ?)",
                    [(c, e["event"], e["timestamp"].replace("T", " "), json.dumps(e)) for c, e in rows()])
    con.commit()
    con.close()


def main() -> int:
    fails = 0

    def check(ok, what):
        nonlocal fails
        print(("ok   " if ok else "FAIL ") + what)
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "EDDUser.sqlite")
        make(db)
        journal = os.path.join(tmp, "Journal.2026-11-10T080000.01.log")
        with open(journal, "w", encoding="utf-8") as f:
            f.write(json.dumps(ev("2026-11-10T07:59:00Z", "LoadGame", Commander="ONE", FID="F1")) + "\n")
            f.write(json.dumps(dict(LOAD, timestamp="2026-11-10T07:59:01Z")) + "\n")
        with open(db, "rb") as f:
            before = f.read()

        real = eddhistory.connect

        def guarded(path):
            con = real(path)
            con.set_authorizer(lambda a, t, c, *_: sqlite3.SQLITE_DENY
                               if a == sqlite3.SQLITE_READ and t == "Commanders" and c == "EdsmApiKey"
                               else sqlite3.SQLITE_OK)
            return con
        eddhistory.connect = guarded
        try:
            cut = eddhistory.first_time([journal])
            got = list(eddhistory.lines(db, ("Loadout", "Cargo", "FSDJump", "ProspectedAsteroid",
                                             "MiningRefined", "Docked"), cut))
        finally:
            eddhistory.connect = real
        everything = list(eddhistory.lines(db, ("FSDJump",)))
        check(len([e for e in everything if e["event"] == "FSDJump"]) == 7,
              "without a time limit every line from the login on (%d jumps)" % len(everything))
        check(cut == 1794297540.0, "first_time: the first line of the oldest journal (%s)" % cut)
        jumps = [e for e in got if e["event"] == "FSDJump"]
        check(len(jumps) == 6, "six older jumps: none before the login, none the journal has (%d)" % len(jumps))
        check(not [e for e in got if e["event"] == "RefuelAll"], "only the asked events")
        check("secret" not in json.dumps(got), "the EDSM key is never read (SQLite refuses the column)")
        with open(db, "rb") as f:
            check(f.read() == before, "the file is unchanged")
        con = eddhistory.connect(db)
        try:
            con.execute("DELETE FROM JournalEntries")
            check(False, "read only")
        except sqlite3.OperationalError:
            check(True, "read only: writing is refused")
        con.close()
        check(eddhistory.find(os.path.join(tmp, "EDDSystem.sqlite")) == db, "found beside EDDSystem.sqlite")

        fuel = replay_fuel_events(got + list(read_events([journal])), FuelState())
        lm = fuel.learned()
        check(lm["n"] >= 6, "the fuel model learns from the archive's jumps (n %s, %s)" % (lm["n"], lm["source"]))
        y = RockYield()
        for e in got:
            y.feed(e)
        n = sum(len(v) for v in y.bins.values())
        check(n == 1, "tonnes per rock: the archived rock counts (%d)" % n)

        # body rows stored without physics get it from archived Scan lines -
        # only empty columns, a stored value stays
        sdb = SystemDB(os.path.join(tmp, "sys.sqlite"))
        try:
            sdb._body_upsert(7, 5, kind="Planet", sma=1.0e9)                  # orbit only
            sdb._body_upsert(7, 6, kind="Planet", radius=2.0e6, axial_tilt=0.5)
            check(sdb.bodies_without_physics() == [(7, 5)], "a planet without radius and tilt is found")
            scan = {"event": "Scan", "SystemAddress": 7, "BodyID": 5, "Radius": 3.0e6, "AxialTilt": -0.2,
                    "RotationPeriod": 9.0e4, "PlanetClass": "Icy body"}
            other = dict(scan, BodyID=6, Radius=9.9e6, AxialTilt=1.5)
            filled = sdb.fill_missing_physics([scan, other])
            r5 = sdb.cx.execute("SELECT radius, axial_tilt, rotation FROM bodies WHERE body_id=5").fetchone()
            r6 = sdb.cx.execute("SELECT radius, axial_tilt FROM bodies WHERE body_id=6").fetchone()
            check(tuple(r5) == (3.0e6, -0.2, 9.0e4), "missing radius, tilt and rotation filled (%s)" % (tuple(r5),))
            check(tuple(r6) == (2.0e6, 0.5) and filled == 2, "a stored value is never overwritten (%s)" % (tuple(r6),))
            check(sdb.bodies_without_physics() == [], "nothing left without physics")
        finally:
            sdb.cx.close()
    print("eddhistory selftest: %s" % ("OK" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
