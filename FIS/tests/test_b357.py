"""Jumponium stock (B3), life support on foot (B5), hazard log (B7)."""

import json
import os
import tempfile
import unittest

from fis import fleet as fl, hazards, materials, model
from fis.live import parse_ts


def ev(ts, name, **kw):
    return dict({"timestamp": "2026-04-01T%s:00Z" % ts, "event": name}, **kw)


class JumponiumTest(unittest.TestCase):
    def test_stock_and_readiness(self):
        evs = [
            ev("09:00", "Materials", Raw=[{"Name": "carbon", "Count": 10}, {"Name": "vanadium", "Count": 5},
                                          {"Name": "germanium", "Count": 7}, {"Name": "niobium", "Count": 1}]),
            ev("09:10", "MaterialCollected", Category="Raw", Name="niobium", Count=3),
            ev("09:20", "Synthesis", Name="FSD Basic", Materials=[{"Name": "carbon", "Count": 1},
                                                                  {"Name": "vanadium", "Count": 1},
                                                                  {"Name": "germanium", "Count": 1}]),
            ev("09:30", "MaterialTrade", Paid={"Material": "germanium", "Quantity": 2},
               Received={"Material": "cadmium", "Quantity": 2}),
        ]
        st = materials.stock(evs)
        self.assertEqual(st["have"]["carbon"], 9)
        self.assertEqual(st["have"]["niobium"], 4)
        self.assertEqual(st["have"]["germanium"], 4)
        self.assertEqual(st["have"]["cadmium"], 2)
        self.assertEqual(st["synthesised"][0]["grade"], "basic")
        r = {x["grade"]: x for x in materials.readiness(st["have"])}
        self.assertEqual(r["basic"]["can"], 4)                  # germanium 4 limits
        self.assertEqual(r["standard"]["can"], 2)               # cadmium 2
        self.assertEqual(r["premium"]["can"], 0)
        self.assertIn("arsenic", r["premium"]["missing"])

    def test_sources_nearest_first(self):
        class Db:
            def query(self, sql, args=()):
                row = lambda name, x, mats: {"name": name, "sys_id64": 1, "materials": json.dumps(mats),
                                             "system": name.split()[0], "x": x, "y": 0, "z": 0}
                return [row("Far 1", 100, {"Niobium": 2.0}), row("Near 1", 5, {"Niobium": 0.8, "Iron": 20}),
                        row("Mid 1", 50, {"Iron": 20})]
        src = materials.sources(Db(), ["niobium"], (0, 0, 0))
        self.assertEqual([s["body"] for s in src["niobium"]], ["Near 1", "Far 1"])


class LifeSupportTest(unittest.TestCase):
    def test_on_foot_only(self):
        self.assertIsNone(model.life_support({"flags2": 0}))
        st = {"flags2": 1 | (1 << 6) | (1 << 10), "oxygen": 0.2, "health": 0.9, "temp_k": 150.0, "gravity": 0.3}
        life = model.life_support(st)
        self.assertTrue(life["low_oxygen"])
        self.assertTrue(life["very_cold"])
        self.assertFalse(life["breathable"])
        self.assertEqual(life["temp_k"], 150.0)


class ApproachTest(unittest.TestCase):
    def test_nothing_without_a_body(self):
        self.assertIsNone(model.approach_info(None, {"status": {}}))
        self.assertIsNone(model.approach_info(None, {"status": {"body_name": "X 1"}}))   # no system yet


class HazardTest(unittest.TestCase):
    def test_log(self):
        with tempfile.TemporaryDirectory() as d:
            lines = [
                ev("08:00", "Commander", FID="F1", Name="X"),
                ev("08:00", "LoadGame", Commander="X"),
                ev("08:01", "FSDJump", StarSystem="Alpha"),
                ev("08:02", "ApproachBody", Body="Alpha 1"),
                ev("08:03", "HeatWarning"), ev("08:04", "HeatWarning"),          # folded into one
                ev("08:10", "HullDamage", Health=0.7, PlayerPilot=True),
                ev("08:11", "ShieldState", ShieldsUp=True),                        # back up: no line
                ev("08:12", "Interdicted", Submitted=False, Interdictor="Pirate", IsPlayer=False),
            ]
            # an older session before: not in "this session"
            lines = [ev("07:00", "Commander", FID="F1", Name="X"), ev("07:00", "LoadGame", Commander="X"),
                     ev("07:05", "HeatDamage")] + lines
            with open(os.path.join(d, "Journal.2026-04-01T080000.01.log"), "w", encoding="utf-8") as fh:
                for e in lines:
                    fh.write(json.dumps(e) + "\n")
            h = hazards.build_hazards(fl.Archive(d), now=parse_ts("2026-04-01T09:00:00Z"))
        kinds = [i["kind"] for i in h["items"]]
        self.assertEqual(kinds, ["Interdicted", "HullDamage", "HeatWarning"])   # newest first
        heat = h["items"][2]
        self.assertEqual(heat["n"], 2)
        self.assertEqual(heat["system"], "Alpha")
        self.assertEqual(heat["body"], "Alpha 1")
        self.assertEqual(h["items"][1]["v"]["pct"], 70)
        self.assertEqual(h["counts"]["danger"], 2)


if __name__ == "__main__":
    unittest.main()
