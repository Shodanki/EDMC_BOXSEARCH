# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M1: open / done bio signals over all bodies (ATLAS BIOLOGY)."""

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
        sp = lambda *names: json.dumps([{"species": n, "genus": n.split()[0]} for n in names])
        rows = [  # body_id, name, signals, analysed, genera (DSS), analysed species
            (40, "Open 1", 3, 1, "Bacterium,Stratum,Tussock", sp("Bacterium Vesicula")),
            (41, "Done 1", 2, 2, "Bacterium,Fonticulua", sp("Bacterium Acies", "Fonticulua Lapida")),
            # the open signal is a Brain Tree: codex only, never sampled -> done
            (42, "Brain 1", 2, 1, "Brain Trees,Osseus", sp("Osseus Spiralis")),
            (43, "FSS only", 1, 0, "", "[]")]
        for bid, nm, sig, org, gen, spc in rows:
            cx.execute("INSERT INTO bodies (sys_id64, body_id, name, kind, sig_bio, organics, genuses,"
                       " bio_species) VALUES (?,?,?,'Planet',?,?,?,?)",
                       (fx.SYS_ID, bid, fx.SYS + " " + nm, sig, org, gen, spc))
        cx.commit()
        cx.close()
        make_cfg(path, cls.tmp)
        cls.db = Database(path)
        from fis import model
        cls.model = model

    def test_kinds_and_totals(self):
        kinds = {k["key"]: k["count"] for k in self.model.build_atlas_kinds(self.db, "bio")}
        self.assertEqual(kinds, {"open": 2, "done": 2})
        a = self.model.build_atlas(self.db, "bio", None, None)
        self.assertEqual(a["totals"], {"bodies": 4, "bodies_open": 2, "signals": 8,
                                       "analysed": 4, "open": 3})

    def test_open_body_details(self):
        a = self.model.build_atlas(self.db, "bio", "open", None)
        by = {it["body_short"]: it for it in a["items"]}
        self.assertEqual(sorted(by), ["FSS only", "Open 1"])
        o = by["Open 1"]
        self.assertEqual((o["open"], o["signals"], o["analysed"]), (2, 3, 1))
        self.assertEqual(o["missing"], ["Stratum", "Tussock"])
        self.assertEqual(o["species"], ["Bacterium Vesicula"])
        self.assertEqual(o["body_id"], 40)

    def test_codex_only_counts_as_done(self):
        a = self.model.build_atlas(self.db, "bio", "done", None)
        by = {it["body_short"]: it for it in a["items"]}
        self.assertEqual(sorted(by), ["Brain 1", "Done 1"])
        self.assertEqual(by["Brain 1"]["codex_only"], ["Brain Trees"])
        self.assertEqual(by["Brain 1"]["open"], 0)


if __name__ == "__main__":
    unittest.main()
