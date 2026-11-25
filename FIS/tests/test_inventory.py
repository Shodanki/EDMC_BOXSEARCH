# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SHIP > MATERIALS (5.1.0, user 24.11.): everything collected, with the count."""

import json
import os
import shutil
import tempfile
import unittest

from fis import inventory as inv

VIEWS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views")


def _read(name):
    with open(os.path.join(VIEWS, name), encoding="utf-8") as fh:
        return fh.read()


EVENTS = [
    {"timestamp": "2026-11-01T10:00:00Z", "event": "MaterialCollected", "Category": "Encoded",
     "Name": "wakesolutions", "Name_Localised": "Strange Wake Solutions", "Count": 1},
    {"timestamp": "2026-11-23T14:33:39Z", "event": "Materials",
     "Raw": [{"Name": "carbon", "Count": 300}, {"Name": "polonium", "Count": 4}],
     "Manufactured": [{"Name": "wornshieldemitters", "Name_Localised": "Worn Shield Emitters", "Count": 178}],
     "Encoded": [{"Name": "wakesolutions", "Name_Localised": "Strange Wake Solutions", "Count": 2}]},
    {"timestamp": "2026-11-23T15:00:00Z", "event": "MaterialCollected", "Category": "Raw", "Name": "nickel", "Count": 3},
    {"timestamp": "2026-11-23T15:10:00Z", "event": "Synthesis", "Name": "FSD Basic",
     "Materials": [{"Name": "carbon", "Count": 60}, {"Name": "polonium", "Count": 4}]},
    {"timestamp": "2026-11-23T15:20:00Z", "event": "MaterialTrade", "TraderType": "encoded",
     "Paid": {"Material": "wakesolutions", "Category": "Encoded", "Quantity": 2},
     "Received": {"Material": "fsdtelemetry", "Material_Localised": "Anomalous FSD Telemetry",
                  "Category": "Encoded", "Quantity": 6}},
    {"timestamp": "2026-11-23T15:30:00Z", "event": "Cargo", "Inventory": []},
]


class InventoryTest(unittest.TestCase):
    def test_ship_materials_with_changes_since_login(self):
        d = inv.ship_materials(EVENTS)
        self.assertEqual(d["base_ts"], "2026-11-23T14:33:39Z")
        rows = {r["key"]: r for r in d["rows"]}
        self.assertEqual((rows["carbon"]["count"], rows["carbon"]["since"], rows["carbon"]["cat"]), (240, -60, "Raw"))
        self.assertEqual((rows["nickel"]["count"], rows["nickel"]["since"], rows["nickel"]["name"]), (3, 3, "Nickel"))
        self.assertEqual(rows["fsdtelemetry"]["name"], "Anomalous FSD Telemetry")
        self.assertEqual(rows["fsdtelemetry"]["cat"], "Encoded", "category from the trade")
        self.assertEqual(rows["wornshieldemitters"]["count"], 178)
        self.assertEqual((rows["polonium"]["count"], rows["polonium"]["since"]), (0, -4), "used up: shown with 0")
        self.assertEqual(rows["wakesolutions"]["count"], 0)
        self.assertEqual([r["cat"] for r in d["rows"]], sorted(r["cat"] for r in d["rows"]))
        self.assertEqual(inv.ship_materials([])["rows"], [])

    def test_raw_stops_at_its_maximum(self):
        """User's journal 24.11.: carbon 299 + 3 was counted as 302 - the game
        writes MaterialCollected also when a material is full."""
        from fis import materials
        self.assertEqual(len(inv.RAW_GRADE), 28)
        for k, g in materials.GRADE.items():
            self.assertEqual(inv.RAW_GRADE[k], g, k)
        evs = [{"timestamp": "2026-11-23T14:00:00Z", "event": "Materials", "Raw": [{"Name": "carbon", "Count": 299}],
                "Manufactured": [{"Name": "crystalshards", "Count": 85}], "Encoded": []},
               {"timestamp": "2026-11-23T15:00:00Z", "event": "MaterialCollected", "Category": "Raw",
                "Name": "carbon", "Count": 3},
               {"timestamp": "2026-11-23T15:01:00Z", "event": "MaterialCollected", "Category": "Manufactured",
                "Name": "crystalshards", "Count": 3}]
        rows = {r["key"]: r for r in inv.ship_materials(evs)["rows"]}
        self.assertEqual((rows["carbon"]["count"], rows["carbon"]["cap"], rows["carbon"]["grade"]), (300, 300, 1))
        self.assertEqual((rows["crystalshards"]["count"], rows["crystalshards"]["cap"]), (88, None))

    def test_ship_locker(self):
        tmp = tempfile.mkdtemp()
        try:
            self.assertIsNone(inv.ship_locker(tmp))
            with open(os.path.join(tmp, "ShipLocker.json"), "w", encoding="utf-8") as fh:
                json.dump({"timestamp": "2026-11-23T17:36:51Z", "event": "ShipLocker",
                           "Items": [{"Name": "largecapacitypowerregulator", "Name_Localised": "Power Regulator",
                                      "OwnerID": 0, "Count": 2}],
                           "Components": [], "Data": [],
                           "Consumables": [{"Name": "healthpack", "Name_Localised": "Medkit", "OwnerID": 0, "Count": 100},
                                           {"Name": "healthpack", "Name_Localised": "Medkit", "OwnerID": 7, "Count": 3},
                                           {"Name": "energycell", "Name_Localised": "Energy Cell", "OwnerID": 0, "Count": 0}]}, fh)
            d = inv.ship_locker(tmp)
            self.assertEqual(d["ts"], "2026-11-23T17:36:51Z")
            self.assertEqual([(r["cat"], r["name"], r["count"]) for r in d["rows"]],
                             [("Items", "Power Regulator", 2), ("Consumables", "Medkit", 103)])
            self.assertIsNone(inv.ship_locker(None))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_tab_after_synthesis(self):
        js = _read("ship.js")
        self.assertIn('tb("synth", t("SYNTHESIS")), tb("mats", t("MATERIALS"))', js)
        self.assertIn('if (tab === "mats") { root.append(inventoryView()); return; }', js)
        self.assertIn('getJSON("/api/inventory")', _read("inventory.js"))


if __name__ == "__main__":
    unittest.main()
