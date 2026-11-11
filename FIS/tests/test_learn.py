# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""L3/L4: rates per ring and hotspot, rigs per planet class, learning status."""

import json
import os
import sqlite3
import tempfile
import unittest

from tests import fixtures as fx

from fis import fleet as fl
from fis import learn
from fis.config import Config
from fis.data import Database


def _ev(t, name, **kw):
    return dict({"timestamp": "2026-11-%sZ" % t, "event": name}, **kw)


def _run(day, ring, mat, tonnes, minutes, other=None):
    """A laser-mining run in `ring`: one prospector report, `tonnes` refined
    over `minutes`, optionally one tonne of `other`."""
    out = [_ev("%sT10:00:00" % day, "SupercruiseExit", Body=ring, BodyType="PlanetaryRing"),
           _ev("%sT10:01:00" % day, "ProspectedAsteroid",
               Materials=[{"Name": mat, "Proportion": 20.0}], Content="$AsteroidMaterialContent_High;")]
    step = minutes * 60 / max(1, tonnes)
    for i in range(tonnes):
        s = 60 + int((i + 1) * step)
        out.append(_ev("%sT%02d:%02d:%02d" % (day, 10 + s // 3600, (s // 60) % 60, s % 60), "MiningRefined",
                       Type="$%s_name;" % mat, Type_Localised=mat.capitalize()))
    if other:
        out.append(_ev("%sT%02d:%02d:30" % (day, 10 + (60 + minutes * 60) // 3600, ((60 + minutes * 60) // 60) % 60),
                       "MiningRefined", Type="$%s_name;" % other, Type_Localised=other.capitalize()))
    out.append(_ev("%sT12:30:00" % day, "SupercruiseEntry"))
    return out


EVENTS = (_run("01", "Alpha 1 A Ring", "tritium", 30, 60)
          + _run("02", "Alpha 1 A Ring", "tritium", 20, 60, other="bromellite")
          + _run("03", "Beta 2 A Ring", "tritium", 10, 60)
          + _run("04", "Beta 2 A Ring", "platinum", 3, 30)            # too few tonnes: no rate
          + [_ev("05T10:00:00", "SupercruiseExit", Body="Gamma 3", BodyType="Planet"),
             _ev("05T10:01:00", "MiningRefined", Type="$gold_name;"),  # not in a ring
             _ev("05T10:40:00", "MiningRefined", Type="$gold_name;")])


class TestRingRates(unittest.TestCase):
    def test_runs_get_their_ring(self):
        runs = learn.ring_runs(EVENTS)
        self.assertEqual([(r["ring"], r["mat"], r["t"]) for r in runs],
                         [("Alpha 1 A Ring", "tritium", 30), ("Alpha 1 A Ring", "tritium", 20),
                          ("Beta 2 A Ring", "tritium", 10)])
        self.assertEqual(runs[1]["all_t"], 21)                  # the main material counts

    def test_rates_and_expectation(self):
        rates = learn.ring_rates(learn.ring_runs(EVENTS), {"Alpha 1 A Ring": "Icy", "Beta 2 A Ring": "Icy"})
        a = rates["ring"][("Alpha 1 A Ring", "tritium")]
        self.assertEqual((a["runs"], a["tonnes"], a["thin"]), (2, 50, True))
        self.assertAlmostEqual(a["t_h"], 50 / (a["hours"]), delta=0.2)
        self.assertLess(a["lo"], a["hi"])
        c = rates["class"][("Icy", "tritium")]
        self.assertEqual((c["runs"], c["rings"], c["thin"]), (3, 2, False))
        # this ring -> its class -> any ring -> nothing
        self.assertEqual(learn.expected_rate(rates, "Alpha 1 A Ring", "Icy", "tritium")["level"], "ring")
        self.assertEqual(learn.expected_rate(rates, "Delta 4 A Ring", "Icy", "tritium")["level"], "class")
        self.assertEqual(learn.expected_rate(rates, "Delta 4 A Ring", "Rocky", "tritium")["level"], "all")
        self.assertIsNone(learn.expected_rate(rates, "Alpha 1 A Ring", "Icy", "painite"))


class TestRigs(unittest.TestCase):
    def setUp(self):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        from fis import model
        self.nav = model.plugin().surfacenav

    def test_rigs_per_class(self):
        marks = [{"ts": "2026-11-05T10:00:00Z", "body_name": "B 1", "kind": "srv_out", "label": "SRV Rhino",
                  "lat": 0.0, "lon": 0.0}]
        # three rigs of 12 t over 20 minutes, far apart in time
        for r in range(3):
            for i in range(12):
                marks.append({"ts": "2026-11-05T10:%02d:%02dZ" % (r * 10, i), "body_name": "B 1",
                              "kind": "refined", "label": "Bauxite#%d" % (r * 12 + i), "lat": 0.0, "lon": 0.0})
        marks.append({"ts": "2026-11-06T10:00:00Z", "body_name": "B 2", "kind": "refined",
                      "label": "Gold#1", "lat": 1.0, "lon": 1.0})
        cls = {"B 1": "Rocky body", "B 2": "Rocky body"}
        out = learn.rig_rates(marks, cls.get, self.nav.body_state)
        r = out["Rocky body"]
        self.assertEqual((r["rigs"], r["tonnes"], r["bodies"], r["thin"]), (4, 37, 2, True))
        self.assertEqual(r["t_per_rig"], 9.2)
        # 3 rigs in the 20-minute outing on B 1 (the single tonne on B 2 is too short)
        self.assertAlmostEqual(r["rigs_h"], 3 / ((20 * 60 + 11) / 3600.0), delta=0.2)


class TestLearningStatus(unittest.TestCase):
    def setUp(self):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(fx.make_db(os.path.join(self.tmp.name, "t.sqlite")))
        cx = sqlite3.connect(self.db.path)
        cx.execute("INSERT INTO hotspots VALUES (1,1,'Alpha 1 A Ring','Tritium','Tritium',2,'eRingClass_Icy',NULL)")
        cx.commit()
        cx.close()
        d = os.path.join(self.tmp.name, "j")
        os.mkdir(d)
        lines = [_ev("01T09:00:00", "Commander", FID="F1", Name="T")] + EVENTS
        with open(os.path.join(d, "Journal.2026-11-01T090000.01.log"), "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(x) + chr(10) for x in lines))
        self.arc = fl.Archive(d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_status(self):
        st = learn.learning_status(self.arc, self.db)
        rocks = {(r["cls"], r["hotspot"]): r for r in st["rocks"]}
        self.assertEqual(rocks[("Icy", "Tritium")]["rocks"], 2)       # Alpha: 2 runs, 1 report each
        self.assertTrue(rocks[("Icy", "Tritium")]["thin"])
        runs = {(r["cls"], r["mat"]): r for r in st["runs"]}
        self.assertEqual(runs[("Icy", "tritium")]["runs"], 2)        # Beta's class is unknown here
        self.assertEqual(runs[("?", "tritium")]["runs"], 1)
        self.assertIn("bio", st)
        self.assertGreaterEqual(st["thin"]["rocks"], 1)


if __name__ == "__main__":
    unittest.main()
