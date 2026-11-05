"""Live tracking of journal, Status.json and NavRoute.json (MVP item 2)."""

import json
import os
import queue
import shutil
import tempfile
import time
import unittest

from fis.live import Hub, LiveTracker, parse_ts

from tests import fixtures as fx

JOURNAL = os.path.join(os.path.expanduser("~"), "Saved Games",
                       "Frontier Developments", "Elite Dangerous")


def drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fis-journal-")
        self.j1 = os.path.join(self.dir, "Journal.2026-11-04T200000.01.log")
        with open(self.j1, "w", encoding="utf-8") as fh:
            for e in fx.journal_lines():
                fh.write(json.dumps(e) + "\n")
        self.hub = Hub()
        self.q = self.hub.subscribe()
        self.lt = LiveTracker(self.dir, self.hub, poll_s=0.05)
        self.lt.prime()

    def tearDown(self):
        self.lt.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def append(self, path, *entries, raw=None):
        with open(path, "a", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
            if raw:
                fh.write(raw)

    def test_prime_is_silent_and_complete(self):
        self.assertEqual(drain(self.q), [])
        s = self.lt.snapshot()
        self.assertEqual(s["system"]["id64"], fx.SYS_ID)
        self.assertEqual(s["target"]["name"], fx.NEXT)
        self.assertEqual(s["ship"]["max_jump"], 68.3)
        self.assertEqual(s["fuel"]["main"], 140.0)
        self.assertEqual(len(s["jumps"]), 6)

    def test_tail_and_partial_line(self):
        e = {"timestamp": "2026-11-04T20:30:00Z", "event": "StartJump", "JumpType": "Hyperspace",
             "StarSystem": fx.NEXT, "SystemAddress": fx.NEXT_ID, "StarClass": "M"}
        line = json.dumps(e)
        self.append(self.j1, raw=line[:20])           # game mid-write
        self.lt.poll_once()
        self.assertIsNone(self.lt.snapshot()["jumping"])
        self.append(self.j1, raw=line[20:] + "\n")
        self.lt.poll_once()
        self.assertEqual(self.lt.snapshot()["jumping"]["name"], fx.NEXT)
        self.assertIn("target", [ev for ev, _ in drain(self.q)])

    def test_jump_event_and_fix(self):
        self.append(self.j1, {"timestamp": "2026-11-04T20:31:00Z", "event": "FSDJump",
                              "StarSystem": fx.NEXT, "SystemAddress": fx.NEXT_ID,
                              "StarPos": [103.0, -20.0, 54.0], "JumpDist": 5.0,
                              "FuelUsed": 0.1, "FuelLevel": 139.9})
        self.lt.poll_once()
        evs = drain(self.q)
        self.assertEqual(evs[0][0], "jump")
        s = self.lt.snapshot()
        self.assertEqual(s["system"]["name"], fx.NEXT)
        self.assertIsNone(s["target"])                 # reached
        self.assertEqual(s["last_fix"]["event"], "FSDJump")
        self.assertIsNone(s["last_fix"]["body_id"])

    def test_new_journal_file(self):
        j2 = os.path.join(self.dir, "Journal.2026-11-05T010000.01.log")
        self.append(j2, {"timestamp": "2026-11-05T01:00:00Z", "event": "FSSDiscoveryScan",
                         "BodyCount": 4, "SystemAddress": fx.SYS_ID})
        future = time.time() + 5
        os.utime(j2, (future, future))
        self.lt.poll_once()
        self.assertEqual(self.lt.snapshot()["journal"], os.path.basename(j2))
        self.assertEqual([ev for ev, _ in drain(self.q)], ["scan"])

    def test_status_json(self):
        st = {"timestamp": "2026-11-04T20:40:00Z", "event": "Status", "Flags": (1 << 21) | (1 << 24),
              "GuiFocus": 9, "Fuel": {"FuelMain": 120.5, "FuelReservoir": 0.9},
              "Latitude": 12.5, "Longitude": -40.0, "Altitude": 3000.0,
              "BodyName": fx.SYS + " 1",
              "Destination": {"System": fx.NEXT_ID, "Body": 0, "Name": fx.NEXT}}
        with open(os.path.join(self.dir, "Status.json"), "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        self.lt.poll_once()
        s = self.lt.snapshot()
        self.assertEqual(s["status"]["gui_focus"], 9)
        self.assertEqual(s["fuel"]["main"], 120.5)
        self.assertEqual(s["last_fix"]["body"], fx.SYS + " 1")
        self.assertEqual(s["last_fix"]["lat"], 12.5)
        evs = [ev for ev, _ in drain(self.q)]
        self.assertEqual(evs, ["status", "target"])
        # unchanged file: no new events
        self.lt.poll_once()
        self.assertEqual(drain(self.q), [])

    def test_half_written_status_is_ignored(self):
        with open(os.path.join(self.dir, "Status.json"), "w", encoding="utf-8") as fh:
            fh.write('{ "timestamp":"2026-11-04T20:40:00Z", "event":"Sta')
        self.lt.poll_once()
        self.assertEqual(drain(self.q), [])

    def test_navroute_json(self):
        nav = {"timestamp": "2026-11-04T20:50:00Z", "event": "NavRoute", "Route": [
            {"StarSystem": fx.SYS, "SystemAddress": fx.SYS_ID, "StarPos": [100, -20, 50], "StarClass": "K"},
            {"StarSystem": fx.NEXT, "SystemAddress": fx.NEXT_ID, "StarPos": [103, -20, 54], "StarClass": "M"},
            {"StarSystem": "Far 1", "SystemAddress": 9, "StarPos": [150, -20, 54], "StarClass": "F"}]}
        with open(os.path.join(self.dir, "NavRoute.json"), "w", encoding="utf-8") as fh:
            json.dump(nav, fh)
        self.append(self.j1, {"timestamp": "2026-11-04T20:50:00Z", "event": "NavRoute"})
        self.lt.poll_once()
        s = self.lt.snapshot()
        self.assertEqual([h["name"] for h in s["navroute"]], [fx.SYS, fx.NEXT, "Far 1"])
        self.assertIn("target", [ev for ev, _ in drain(self.q)])
        self.append(self.j1, {"timestamp": "2026-11-04T20:51:00Z", "event": "NavRouteClear"})
        self.lt.poll_once()
        self.assertEqual(self.lt.snapshot()["navroute"], [])

    def test_thread_runs(self):
        self.lt.start()
        self.append(self.j1, {"timestamp": "2026-11-04T21:00:00Z", "event": "FSDTarget",
                              "Name": "Thread Test", "SystemAddress": 5,
                              "StarClass": "G", "RemainingJumpsInRoute": 1})
        deadline = time.time() + 3
        while time.time() < deadline:
            if (self.lt.snapshot()["target"] or {}).get("name") == "Thread Test":
                break
            time.sleep(0.05)
        self.assertEqual(self.lt.snapshot()["target"]["name"], "Thread Test")


class TestEvents(unittest.TestCase):
    def test_parse_ts(self):
        self.assertEqual(parse_ts("1970-01-01T00:01:00Z"), 60.0)
        self.assertIsNone(parse_ts("nonsense"))

    def test_fix_events(self):
        lt = LiveTracker(".")
        for e in fx.journal_lines():
            lt.feed(e)
        lt.feed({"timestamp": "2026-11-04T21:00:00Z", "event": "Touchdown",
                 "Body": fx.SYS + " 1", "BodyID": 1, "Latitude": 1.0, "Longitude": 2.0,
                 "SystemAddress": fx.SYS_ID})
        self.assertEqual(lt.snapshot()["last_fix"]["body_id"], 1)
        lt.feed({"timestamp": "2026-11-04T21:05:00Z", "event": "ScanOrganic",
                 "Body": 2, "SystemAddress": fx.SYS_ID, "Genus": "x"})
        fxs = lt.snapshot()["last_fix"]
        self.assertEqual((fxs["body_id"], fxs["event"]), (2, "ScanOrganic"))
        lt.feed({"timestamp": "2026-11-04T21:06:00Z", "event": "LeaveBody",
                 "Body": fx.SYS + " 1 a", "BodyID": 2, "SystemAddress": fx.SYS_ID})
        self.assertEqual(lt.snapshot()["last_fix"]["event"], "LeaveBody")

    def test_full_hub_does_not_block(self):
        hub = Hub(maxsize=2)
        q = hub.subscribe()
        for i in range(10):
            hub.publish("status", i)
        self.assertEqual(len(drain(q)), 2)
        hub.unsubscribe(q)
        self.assertEqual(hub.clients, 0)


@unittest.skipUnless(os.path.isdir(JOURNAL), "kein Journal-Ordner")
class TestRealJournal(unittest.TestCase):
    def test_prime_real(self):
        lt = LiveTracker(JOURNAL)
        lt.prime()
        s = lt.snapshot()
        self.assertTrue(s["system"].get("name"))
        self.assertEqual(lt.errors, 0)


if __name__ == "__main__":
    unittest.main()
