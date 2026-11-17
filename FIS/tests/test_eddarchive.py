# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.0: the EDDiscovery archive - older journals read only from EDDUser.sqlite,
tagged per commander, never the EDSM key, only what the journals on disk lack."""

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from fis import config, eddarchive, fleet

FID, OTHER = "F1000001", "F2000002"


def line(ts, name, **kw):
    return dict({"timestamp": ts, "event": name}, **kw)


ROWS = [
    # commander 1: logged in in 2021, a jump, a sale, a signal (live-only)
    (1, line("2021-03-01T10:00:00Z", "LoadGame", FID=FID, Commander="ONE", Credits=5)),
    (1, line("2021-03-01T10:05:00Z", "FSDJump", StarSystem="Old", SystemAddress=7, StarPos=[1, 2, 3],
             JumpDist=20.5, FuelUsed=3.1)),
    (1, line("2021-03-01T10:06:00Z", "FSSSignalDiscovered", SignalName="Beacon")),
    (1, line("2021-03-01T11:00:00Z", "SellOrganicData", BioData=[{"Value": 100, "Bonus": 0}])),
    # the same jump the journal on disk still has: counted once
    (1, line("2026-11-10T08:00:00Z", "FSDJump", StarSystem="Now", SystemAddress=8, StarPos=[0, 0, 0],
             JumpDist=10.0)),
    # commander 2 logged in: its lines are its own
    (2, line("2022-01-01T09:00:00Z", "Commander", FID=OTHER, Name="TWO")),
    (2, line("2022-01-01T09:10:00Z", "RepairAll", Cost=99)),
    # commander 3 never logged in: whose would it be? left out
    (3, line("2023-01-01T09:00:00Z", "RefuelAll", Cost=1)),
]


def make_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Commanders (Id INTEGER PRIMARY KEY, Name TEXT NOT NULL, EdsmApiKey TEXT NOT NULL)")
    con.execute("CREATE TABLE JournalEntries (Id INTEGER PRIMARY KEY AUTOINCREMENT, TravelLogId INTEGER, "
                "CommanderId INTEGER, EventTypeId INTEGER, EventType TEXT, EventTime DATETIME, EventData TEXT)")
    con.executemany("INSERT INTO Commanders VALUES (?, ?, ?)",
                    [(1, "ONE", "secret-key-1"), (2, "TWO", "secret-key-2"), (3, "THREE", "secret-key-3")])
    con.executemany("INSERT INTO JournalEntries (TravelLogId, CommanderId, EventTypeId, EventType, EventTime, "
                    "EventData) VALUES (1, ?, 0, ?, ?, ?)",
                    [(cid, e["event"], e["timestamp"], json.dumps(e)) for cid, e in ROWS])
    con.commit()
    con.close()


def guarded_connect(real):
    """The reader's connection, with SQLite refusing the EDSM key column."""
    def connect(path):
        con = real(path)

        def auth(action, arg1, arg2, _db, _trigger):
            if action == sqlite3.SQLITE_READ and arg1 == "Commanders" and arg2 == "EdsmApiKey":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        con.set_authorizer(auth)
        return con
    return connect


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def wait_for_reader():
    for t in threading.enumerate():
        if t.name == "fis-edd-archive":
            t.join(10)


class TestReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "EDDUser.sqlite")
        make_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_own_lines_per_commander_never_the_edsm_key(self):
        before = digest(self.db)
        with mock.patch.object(eddarchive, "_connect", guarded_connect(eddarchive._connect)):
            got = eddarchive.read(self.db, fleet.EVENTS, fleet.Archive._take)
        self.assertEqual(got["commanders"], {"ONE": FID, "TWO": OTHER})
        evs = [e for e in got["events"] if e["event"] != "Commander"]
        self.assertEqual({e["_fid"] for e in evs}, {FID, OTHER})
        self.assertNotIn("RefuelAll", [e["event"] for e in evs])            # commander 3 never logged in
        self.assertNotIn("FSSSignalDiscovered", [e["event"] for e in evs])  # live-only
        jump = [e for e in evs if e["event"] == "FSDJump"][0]
        self.assertEqual(jump["StarPos"], [1.0, 2.0, 3.0])                  # slimmed like the journals
        self.assertNotIn("FuelUsed", jump)
        self.assertNotIn("secret-key", json.dumps(got))
        # read only: the file is unchanged
        self.assertEqual(digest(self.db), before)

    def test_the_connection_cannot_write(self):
        con = eddarchive._connect(self.db)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("DELETE FROM JournalEntries")
        con.close()

    def test_find_beside_the_plugins_system_file(self):
        self.assertEqual(eddarchive.find(os.path.join(self.tmp.name, "EDDSystem.sqlite")), self.db)
        with mock.patch.object(eddarchive, "CANDIDATES", ()):
            self.assertIsNone(eddarchive.find(os.path.join(self.tmp.name, "nowhere", "EDDSystem.sqlite")))


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "EDDUser.sqlite")
        make_db(self.db)
        self.jdir = os.path.join(self.tmp.name, "journals")
        os.makedirs(self.jdir)
        with open(os.path.join(self.jdir, "Journal.2026-11-10T080000.01.log"), "w", encoding="utf-8") as fh:
            for e in (line("2026-11-10T07:59:00Z", "LoadGame", FID=FID, Commander="ONE", Credits=9),
                      line("2026-11-10T08:00:00Z", "FSDJump", StarSystem="Now", SystemAddress=8,
                           StarPos=[0, 0, 0], JumpDist=10.0)):
                fh.write(json.dumps(e) + "\n")

    def tearDown(self):
        wait_for_reader()
        self.tmp.cleanup()

    def loaded(self, a):
        a.refresh(force=True)
        wait_for_reader()
        a.refresh(force=True)

    def test_older_events_join_the_journals_once(self):
        a = fleet.Archive(self.jdir)
        a.refresh(force=True)
        self.assertEqual([e["event"] for e in a.events()], ["LoadGame", "FSDJump"])
        a.use_edd(self.db)
        self.loaded(a)
        evs = a.events()
        self.assertEqual([e["StarSystem"] for e in evs if e["event"] == "FSDJump"], ["Old", "Now"])
        self.assertIn("SellOrganicData", [e["event"] for e in evs])
        self.assertNotIn("RepairAll", [e["event"] for e in evs])          # commander TWO's
        self.assertEqual(a.commander(), (FID, "ONE"))                       # the journals on disk name it
        self.assertEqual(len(a.events(OTHER)), 1)
        st = a.edd_state
        self.assertEqual((st["state"], st["added"], st["first"]), ("ready", 4, "2021-03-01T10:00:00Z"))
        a.use_edd(None)                                                      # off: dropped at once
        self.assertEqual([e["event"] for e in a.events()], ["LoadGame", "FSDJump"])
        self.assertEqual(a.edd_state, {"state": "off"})

    def test_an_unreadable_file_is_reported(self):
        bad = os.path.join(self.tmp.name, "broken.sqlite")
        with open(bad, "wb") as fh:
            fh.write(b"not a database" * 100)
        a = fleet.Archive(self.jdir)
        a.use_edd(bad)
        self.loaded(a)
        self.assertEqual(a.edd_state["state"], "error")
        self.assertEqual(len(a.events()), 2)


class TestSwitch(unittest.TestCase):
    def test_off_by_default_and_kept_in_fis_ini(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = os.path.join(tmp, "fis.ini")
            c = config.Config().load(ini)
            self.assertFalse(c.edd_archive)
            self.assertIsNone(c.edd_user_db())
            c.edd_archive = True
            c.save()
            self.assertTrue(config.Config().load(ini).edd_archive)


if __name__ == "__main__":
    unittest.main()
