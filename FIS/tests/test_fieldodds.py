# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""MP4 (5.1.0): the chance of a good field before mining, learnt from the rated fields."""

import json
import os
import unittest

from tests.test_fieldrating import field  # puts the plugin folder on sys.path
from fis import fieldodds as fo
from fis import mining, realitycheck

import miningfields as mf  # noqa: E402


class FakeDB:
    """bodies (reserve + rings) and hotspots, as the plugin database holds them."""

    def __init__(self, bodies, hotspots):
        self.bodies, self.hotspots = bodies, hotspots

    def query(self, sql, args=()):
        if "FROM bodies" in sql:
            return [{"reserve": r, "rings_json": json.dumps([{"name": n, "cls": c}])} for n, c, r in self.bodies]
        if "WHERE sys_id64" in sql:
            return [{"body_name": h["body_name"]} for h in self.hotspots
                    if (h.get("sys"), h.get("body")) == tuple(args)][:1]
        return [dict(h) for h in self.hotspots]

    def hotspots_of(self, id64, body_id=None):
        return [{"label": None, "material": h["material"]} for h in self.hotspots
                if (h.get("sys"), h.get("body")) == (id64, body_id)]


def spot(ring, mat, n=1, sys=None, body=None):
    return {"body_name": ring, "material": mat, "count": n, "ring_class": None, "sys": sys, "body": body}


DB = FakeDB([("Good 1 A Ring", "eRingClass_Icy", "PristineResources"),
             ("Good 2 A Ring", "eRingClass_Icy", "PristineResources"),
             ("Good 3 A Ring", "eRingClass_Icy", "PristineResources"),
             ("Bare 1 A Ring", "eRingClass_Icy", "PristineResources"),
             ("Bare 2 A Ring", "eRingClass_Icy", "PristineResources"),
             ("New 1 A Ring", "eRingClass_Icy", "PristineResources"),
             ("New 2 A Ring", "eRingClass_Icy", "PristineResources")],
            [spot("Good 1 A Ring", "Tritium"), spot("Good 2 A Ring", "Tritium"), spot("Good 3 A Ring", "Tritium"),
             spot("Bare 1 A Ring", "Bromellite"), spot("Bare 2 A Ring", "Bromellite"),
             spot("New 1 A Ring", "Tritium", 2, sys=7, body=12), spot("New 2 A Ring", "Bromellite")])


def journal():
    """Three good tritium fields on a hotspot, two poor ones without."""
    evs = []
    for day, ring in enumerate(("Good 1 A Ring", "Good 2 A Ring", "Good 3 A Ring"), 1):
        evs += field(ring, day, [30, 25, 20], 3, [("Tritium", 30)])
    for day, ring in enumerate(("Bare 1 A Ring", "Bare 2 A Ring"), 4):
        evs += field(ring, day, [10, 0, 0, 0, 0, 0, 12], 20, [("Tritium", 10)])
    return evs


class FieldOddsTest(unittest.TestCase):
    def setUp(self):
        fo._cache.clear()

    def test_ring_features_from_the_database(self):
        rf = fo.ring_features(DB)
        self.assertEqual(rf["New 1 A Ring"], {"cls": "Icy", "reserve": "Pristine", "spots": {"tritium": 2}})
        x = fo.features("New 1 A Ring", "tritium", rf)
        self.assertEqual((x["spot"], x["overlap"]), ("yes", "yes"), "two hotspots: overlapping")
        x = fo.features("Bare 1 A Ring", "tritium", rf)
        self.assertEqual((x["spot"], x["overlap"]), ("no", None), "a mapped ring without the material's hotspot")
        self.assertIsNone(fo.features("Unknown Ring", "tritium", rf)["spot"], "an unmapped ring: unknown")

    def test_learns_hotspot_rings_are_better(self):
        m, rf, smp = fo.model(journal(), DB)
        self.assertEqual((m.fields, m.n[1]), (5, 3), "three good or fair, two poor")
        on = fo.odds_for(m, rf, "New 1 A Ring", "tritium")
        off = fo.odds_for(m, rf, "New 2 A Ring", "tritium")
        self.assertGreater(on["p"], 0.65)
        self.assertLess(off["p"], 0.35)
        self.assertEqual((on["verdict"], off["verdict"]), ("good", "poor"))
        self.assertEqual((on["n"], on["n_mat"], on["thin"]), (5, 5, True))
        self.assertTrue(fo.odds_for(m, rf, "New 1 A Ring", "platinum")["thin"], "a material never mined: dim")

    def test_no_number_below_the_minimum(self):
        m = mf.Odds.learn([({"mat": "tritium"}, 1), ({"mat": "tritium"}, 0)])
        self.assertIsNone(m.chance({"mat": "tritium"}))
        self.assertIsNone(fo.verdict(None))

    def test_unknown_and_unseen_do_not_pull_towards_poor(self):
        # 25.11. on the real journals: good fields without ring data and a value
        # never seen ("overlapping") gave a tritium hotspot ring 20 %
        hot = {"mat": "tritium", "spot": "yes", "overlap": "no", "cls": "Icy"}
        smp = [(hot, 1)] * 3 + [({"mat": "silver"}, 1)] * 8 + [({"mat": "tritium", "cls": "Icy"}, 0),
                                                              ({"mat": "monazite"}, 0)]
        m = mf.Odds.learn(smp)
        x = dict(hot, overlap="yes")
        self.assertGreater(m.chance(x), 0.65)
        self.assertEqual(m.uses(x), ["cls", "spot", "mat"], "overlap never seen yet: left out")

    def test_self_learning_each_new_field_counts(self):
        evs = journal()
        n0 = fo.model(evs, DB)[0].fields
        evs += field("New 1 A Ring", 9, [30, 30], 2, [("Tritium", 20)])
        self.assertEqual(fo.model(evs, DB)[0].fields, n0 + 1, "the cache follows the journals")

    def test_reality_leave_one_out(self):
        smp = fo.model(journal(), DB)[2]
        r = fo.reality(smp)
        self.assertEqual(r["n"], 5)
        self.assertEqual(r["hits"], 5, "each field's side predicted from the other four")
        row = [x for x in realitycheck.build({"fields": r}) if x["key"] == "fields"][0]
        self.assertEqual((row["value"], row["n"], row["good"]), ("5 of 5 right · Brier %.2f" % r["brier"], 5, None))
        self.assertIsNone(fo.reality([]))

    def test_mining_places_and_live(self):
        evs = journal()
        hs = [{"ring": "New 1 A Ring", "key": "tritium"}, {"ring": "New 2 A Ring", "key": "tritium"}]
        F = mining._field_odds(evs, DB, hs)
        self.assertEqual((F["fields"], F["good"]), (5, 3))
        self.assertEqual(hs[0]["odds"]["verdict"], "good")
        live = {"status": {"destination": {"system": 7, "body": 12, "name": "Tritium Hotspot"}}}
        o = mining._live_odds(evs, DB, live, "tritium")
        self.assertEqual((o["ring"], o["verdict"]), ("New 1 A Ring", "good"), "the hotspot ahead")
        at = {"status": {"body_name": "New 2 A Ring"}}
        self.assertEqual(mining._live_odds(evs, DB, at, "tritium")["verdict"], "poor", "in the ring")
        self.assertIsNone(mining._live_odds(evs, DB, {"status": {"body_name": "New 2 A"}}, "tritium"))

    def test_planet_info_rings(self):
        # SP1: under each ring of PLANET INFO, per hotspot material and per
        # material mined there - the chance and the record, all commanders
        from fis import model

        class Archive:
            def events(self, fid=None):
                return journal()
        rings = [{"name": "New 1 A Ring", "hotspots": [{"material": "Tritium", "key": "Tritium", "count": 2}]},
                 {"name": "Bare 1 A Ring", "hotspots": [{"material": "Bromellite", "key": "Bromellite", "count": 1}]}]
        model._ring_spots(DB, rings, Archive())
        new = {s["mat"]: s for s in rings[0]["spots"]}
        self.assertEqual(set(new), {"tritium"})
        self.assertEqual((new["tritium"]["odds"]["verdict"], new["tritium"]["field"]), ("good", None),
                         "a hotspot ring never mined: its chance, no record")
        bare = {s["mat"]: s for s in rings[1]["spots"]}
        self.assertEqual(set(bare), {"bromellite", "tritium"}, "the hotspot and the material mined there")
        self.assertEqual(bare["tritium"]["field"]["rating"], "poor")
        me = model._self_ring_spots(DB, {"name": "New 1 A Ring", "rings": [], "id64": 7, "body_id": 12}, Archive())
        self.assertEqual([(x["mat"], x["odds"]["verdict"]) for x in me], [("tritium", "good")],
                         "the ring opened itself: its own spots")
        self.assertIsNone(model._self_ring_spots(DB, {"name": "New 1 A", "rings": [], "id64": 7, "body_id": 1},
                                                 Archive()), "a planet: none")

    def test_shown_in_places_live_and_learning(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views")
        with open(os.path.join(base, "mining.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertEqual(js.count("oddsSpan(h.odds)"), 2, "RING HOTSPOTS and BEST HOTSPOTS")
        self.assertIn("const O = L.odds;", js)
        with open(os.path.join(base, "planet.js"), encoding="utf-8") as fh:
            pj = fh.read()
        self.assertIn("for (const s of r.spots || []) rr.push(spotLine(s));", pj)
        self.assertIn("rr.push(spotNote(b.rings))", pj)
        with open(os.path.join(base, "statistics.js"), encoding="utf-8") as fh:
            self.assertIn('fields: N_("Field odds before mining (good / poor)")', fh.read())


if __name__ == "__main__":
    unittest.main()
