# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M1: open / done bio signals over all bodies (ATLAS BIOLOGY).

4.11.1: Brain Trees are sampled like any species (the journals show it and
Vista Genomics pays for them), and one Brain Trees signal can be several
species - the ones the codex saw count until each is analysed."""

import json
import os
import sqlite3
import tempfile
import unittest

from fis.data import Database

from . import fixtures as fx
from .test_api import make_cfg


class TestBioAtlas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fis-bio-")
        path = fx.make_db(os.path.join(cls.tmp, "db.sqlite"))
        cx = sqlite3.connect(path)
        cx.execute("DELETE FROM bodies WHERE sig_bio > 0")

        def sp(*names):
            return json.dumps([{"species": n, "genus": "Brain Trees" if n.endswith("Brain Tree")
                                else n.split()[0]} for n in names])
        rows = [  # body_id, name, signals, analysed, genera (DSS), analysed species
            (40, "Open 1", 3, 1, "Bacterium,Stratum,Tussock", sp("Bacterium Vesicula")),
            (41, "Done 1", 2, 2, "Bacterium,Fonticulua", sp("Bacterium Acies", "Fonticulua Lapida")),
            # Brain Trees not sampled yet: open (up to 4.11.0 wrongly "codex only, done")
            (42, "Brain 1", 2, 1, "Brain Trees,Osseus", sp("Osseus Spiralis")),
            # one signal, two species in the codex, one analysed: still open
            (44, "Brain 2", 1, 1, "Brain Trees", sp("Lividum Brain Tree")),
            # the other Horizons organics stay "codex only" until shown otherwise
            (45, "Anemone 1", 2, 1, "Anemone,Osseus", sp("Osseus Spiralis")),
            (43, "FSS only", 1, 0, "", "[]")]
        for bid, nm, sig, org, gen, spc in rows:
            cx.execute("INSERT INTO bodies (sys_id64, body_id, name, kind, sig_bio, organics, genuses,"
                       " bio_species) VALUES (?,?,?,'Planet',?,?,?,?)",
                       (fx.SYS_ID, bid, fx.SYS + " " + nm, sig, org, gen, spc))
        cx.execute("CREATE TABLE IF NOT EXISTS signals (sys_id64 INTEGER NOT NULL, body_id INTEGER NOT NULL, "
                   "body_name TEXT, kind TEXT NOT NULL, label TEXT, count INTEGER NOT NULL DEFAULT 1, "
                   "found TEXT, PRIMARY KEY (sys_id64, body_id, kind))")     # the plugin's (sysdb)
        for label in ("Lividum Brain Tree", "Roseum Brain Tree"):
            cx.execute("INSERT INTO signals (sys_id64, body_id, body_name, kind, label, count, found) "
                       "VALUES (?,?,?,?,?,1,'2026-11-13')",
                       (fx.SYS_ID, 44, None, "codex:" + label, label))
        cx.commit()
        cx.close()
        make_cfg(path, cls.tmp)
        cls.db = Database(path)
        from fis import model
        cls.model = model

    def test_kinds_and_totals(self):
        kinds = {k["key"]: k["count"] for k in self.model.build_atlas_kinds(self.db, "bio")}
        self.assertEqual(kinds, {"open": 4, "done": 2})
        a = self.model.build_atlas(self.db, "bio", None, None)
        self.assertEqual(a["totals"], {"bodies": 6, "bodies_open": 4, "signals": 11,
                                       "analysed": 6, "open": 5})

    def test_open_body_details(self):
        a = self.model.build_atlas(self.db, "bio", "open", None)
        by = {it["body_short"]: it for it in a["items"]}
        self.assertEqual(sorted(by), ["Brain 1", "Brain 2", "FSS only", "Open 1"])
        o = by["Open 1"]
        self.assertEqual((o["open"], o["signals"], o["analysed"]), (2, 3, 1))
        self.assertEqual(o["missing"], ["Stratum", "Tussock"])
        self.assertEqual(o["species"], ["Bacterium Vesicula"])
        self.assertEqual(o["body_id"], 40)

    def test_brain_trees_are_sampled(self):
        a = self.model.build_atlas(self.db, "bio", "open", None)
        by = {it["body_short"]: it for it in a["items"]}
        b1 = by["Brain 1"]
        self.assertEqual((b1["open"], b1["missing"], b1["codex_only"]), (1, ["Brain Trees"], []))
        b2 = by["Brain 2"]
        self.assertEqual((b2["open"], b2["open_species"], b2["multi"]), (1, ["Roseum Brain Tree"], ["Brain Trees"]))

    def test_planet_info_and_system_name_the_open_species(self):
        from fis import science
        b = self.model.build_body(self.db, fx.SYS_ID, 44)
        self.assertEqual(sorted(b["bio"]["seen"]), ["Lividum Brain Tree", "Roseum Brain Tree"])
        self.assertEqual((b["bio"]["open_species"], b["bio"]["multi"]), (["Roseum Brain Tree"], ["Brain Trees"]))
        found = {f["id"]: f for f in science.body_report(b)}
        self.assertEqual(found["bio_multi"]["v"]["g"], "Brain Trees")
        self.assertEqual(found["bio_multi"]["level"], "warn")
        self.assertIn("Roseum Brain Tree", found["bio_open"]["v"]["g"])
        # the advice agrees: one more species to sample, biology not complete
        self.assertEqual(found["sample"]["v"]["n"], 1)
        self.assertNotIn("bio_complete", found)
        bio = {x["body_id"]: x for x in self.model.bio_list(self.db, fx.SYS_ID, self.db.bodies_of(fx.SYS_ID), [])}
        sp = {s["species"]: s["state"] for s in bio[44]["species"]}
        self.assertEqual(sp, {"Lividum Brain Tree": "done", "Roseum Brain Tree": "open"})
        self.assertEqual(bio[44]["multi"], ["Brain Trees"])
        self.assertEqual(bio[40]["multi"], [])

    def test_other_horizons_organics_stay_codex_only(self):
        a = self.model.build_atlas(self.db, "bio", "done", None)
        by = {it["body_short"]: it for it in a["items"]}
        self.assertEqual(sorted(by), ["Anemone 1", "Done 1"])
        self.assertEqual((by["Anemone 1"]["codex_only"], by["Anemone 1"]["open"]), (["Anemone"], 0))


if __name__ == "__main__":
    unittest.main()
