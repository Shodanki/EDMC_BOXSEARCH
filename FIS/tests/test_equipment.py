# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""EQ1 (5.1.0): the equipment in storage, where it lies, what it fits."""

import base64
import gzip
import json
import os
import shutil
import tempfile
import unittest
import urllib.parse

from fis import equipment as eq
from fis.fleet import Archive

CARRIER = 3712967680
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views")


def _read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        return fh.read()


JM = 128666762


def _item(name, slot_no, market=CARRIER, system="Synuefe TH-J b42-5", **kw):
    return dict({"Name": "$%s_name;" % name, "Name_Localised": kw.pop("loc", name), "StorageSlot": slot_no,
                 "StarSystem": system, "MarketID": market, "TransferCost": 0, "TransferTime": 0,
                 "BuyPrice": kw.pop("price", 1000), "Hot": False}, **kw)


LOADOUT = {"timestamp": "2026-11-10T10:00:00Z", "event": "Loadout", "Ship": "lakonminer", "ShipID": 52,
           "ShipName": "MINER", "ShipIdent": "SH-01", "CargoCapacity": 322,
           "Modules": [{"Slot": "PowerPlant", "Item": "int_powerplant_size6_class3"},
                       {"Slot": "LifeSupport", "Item": "int_lifesupport_size4_class2"},
                       {"Slot": "FuelTank", "Item": "int_fueltank_size5_class3"},
                       {"Slot": "Armour", "Item": "lakonminer_armour_grade1"},
                       {"Slot": "MediumHardpoint1", "Item": "hpt_mininglaser_fixed_medium"},
                       {"Slot": "TinyHardpoint1", "Item": "hpt_mrascanner_size0_class3"},
                       {"Slot": "Slot01_Size6", "Item": "int_refinery_size4_class2"},
                       {"Slot": "Military01", "Item": "int_hullreinforcement_size4_class2",
                        "Engineering": {"BlueprintName": "HullReinforcement_HeavyDuty", "Level": 3}},
                       {"Slot": "CargoHatch", "Item": "modularcargobaydoor"}]}


class EquipmentTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        eq._cache.update(key=None, snap=None)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _journal(self, name, events):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e) + "\n")

    def _snapshot(self, ts, items, fid="F1"):
        return [{"timestamp": ts, "event": "Commander", "FID": fid, "Name": "CMDR"},
                {"timestamp": ts, "event": "StoredModules", "MarketID": CARRIER, "StationName": "V2L-07J",
                 "StarSystem": "Synuefe TH-J b42-5", "Items": items}]

    def test_classify(self):
        self.assertEqual(eq.classify("hpt_mininglaser_fixed_medium")["group"], "hardpoint")
        self.assertEqual(eq.classify("hpt_mininglaser_fixed_medium")["size"], 2)
        self.assertEqual(eq.classify("hpt_shieldbooster_size0_class5")["group"], "utility")
        c = eq.classify("int_powerplant_size6_class5")
        self.assertEqual((c["group"], c["core"], c["size"], c["cls"]), ("core", "PowerPlant", 6, 5))
        self.assertEqual(eq.classify("int_hyperdrive_overcharge_size5_class5")["core"], "FrameShiftDrive")
        self.assertEqual(eq.classify("type7_armour_grade3")["hull"], "type7")
        self.assertEqual(eq.classify("int_cargorack_size6_class1")["group"], "optional")
        self.assertEqual(eq.item_key("$int_engine_size5_class5_name;"), "int_engine_size5_class5")

    def test_fits_by_slot_and_size(self):
        slots = {s["slot"]: s for s in eq.ship_slots(LOADOUT)}
        self.assertNotIn("CargoHatch", slots)
        fits = lambda item, slot: eq.fits_slot(item, eq.classify(item), slots[slot])   # noqa: E731
        self.assertTrue(fits("int_powerplant_size5_class5", "PowerPlant"))      # smaller core fits
        self.assertFalse(fits("int_powerplant_size7_class5", "PowerPlant"))
        self.assertFalse(fits("int_engine_size5_class5", "PowerPlant"))
        self.assertTrue(fits("int_fueltank_size4_class3", "FuelTank"))
        self.assertTrue(fits("int_cargorack_size6_class1", "Slot01_Size6"))
        self.assertFalse(fits("int_cargorack_size6_class1", "Military01"), "military slots: reinforcement only")
        self.assertTrue(fits("int_modulereinforcement_size4_class2", "Military01"))
        self.assertTrue(fits("hpt_pulselaser_gimbal_small", "MediumHardpoint1"))
        self.assertFalse(fits("hpt_pulselaser_gimbal_large", "MediumHardpoint1"))
        self.assertTrue(fits("hpt_shieldbooster_size0_class5", "TinyHardpoint1"))
        self.assertFalse(fits("hpt_shieldbooster_size0_class5", "MediumHardpoint1"))

    def test_better_than_fitted(self):
        c = eq.classify
        self.assertTrue(eq.better("int_powerplant_size6_class5", c("int_powerplant_size6_class5"), False,
                                  "int_powerplant_size6_class3", False))
        self.assertFalse(eq.better("int_powerplant_size6_class2", c("int_powerplant_size6_class2"), False,
                                   "int_powerplant_size6_class3", False))
        self.assertTrue(eq.better("int_lifesupport_size4_class2", c("int_lifesupport_size4_class2"), True,
                                  "int_lifesupport_size4_class2", False), "engineered where the fitted is not")
        self.assertFalse(eq.better("int_hullreinforcement_size4_class2", c("int_hullreinforcement_size4_class2"),
                                   False, "int_hullreinforcement_size4_class2", True), "never trade engineering away")
        self.assertFalse(eq.better("int_shieldgenerator_size4_class5", c("int_shieldgenerator_size4_class5"), False,
                                   "int_refinery_size4_class2", False), "another kind of module")

    def test_newest_list_of_the_commander(self):
        self._journal("Journal.2026-11-01T100000.01.log", self._snapshot("2026-11-01T10:00:00Z", [_item("old", 1)]))
        self._journal("Journal.2026-11-02T100000.01.log",
                      self._snapshot("2026-11-02T10:00:00Z", [_item("mine", 2)])
                      + self._snapshot("2026-11-02T11:00:00Z", [_item("alt", 3)], fid="F2"))
        snap = eq.latest_snapshot(self.dir, "F1")
        self.assertEqual(snap["Items"][0]["Name"], "$mine_name;")
        self.assertEqual(eq.latest_snapshot(self.dir, "F2")["Items"][0]["Name"], "$alt_name;")
        self.assertIsNone(eq.latest_snapshot(None, "F1"))

    def test_changes_since_the_list(self):
        snap = self._snapshot("2026-11-02T10:00:00Z", [
            _item("int_powerplant_size6_class5", 10), _item("int_powerplant_size6_class5", 11),
            _item("hpt_railgun_fixed_medium", 12, market=JM, system="Shinrarta Dezhra",
                  EngineerModifications="Weapon_HighCapacity", Level=5, Quality=1.0),
            _item("int_cargorack_size6_class1", 13), _item("int_shieldgenerator_size8_class3_fast", 14)])[1]
        evs = [
            {"timestamp": "2026-11-01T09:00:00Z", "event": "ModuleStore", "MarketID": CARRIER,
             "StoredItem": "$int_engine_size3_class1_name;"},                            # before the list: ignored
            {"timestamp": "2026-11-02T12:00:00Z", "event": "Docked", "StarSystem": "Synuefe TH-J b42-5",
             "MarketID": CARRIER, "StationName": "V2L-07J"},
            {"timestamp": "2026-11-02T12:01:00Z", "event": "ModuleStore", "MarketID": CARRIER,
             "StoredItem": "$int_fueltank_size5_class3_name;", "StoredItem_Localised": "Fuel Tank"},
            {"timestamp": "2026-11-02T12:02:00Z", "event": "ModuleRetrieve", "MarketID": CARRIER,
             "RetrievedItem": "$int_powerplant_size6_class5_name;"},
            {"timestamp": "2026-11-02T12:03:00Z", "event": "ModuleSellRemote", "StorageSlot": 14,
             "SellItem": "$int_shieldgenerator_size8_class3_fast_name;"},
            {"timestamp": "2026-11-02T12:04:00Z", "event": "FetchRemoteModule", "StorageSlot": 12,
             "StoredItem": "$hpt_railgun_fixed_medium_name;", "TransferTime": 600},
            {"timestamp": "2026-11-02T12:05:00Z", "event": "ModuleBuy", "MarketID": CARRIER,
             "BuyItem": "$int_engine_size5_class5_name;", "StoredItem": "$int_engine_size5_class2_name;"},
        ]
        items = eq.stored_now(snap, evs)
        names = sorted(x["item"] for x in items)
        self.assertEqual(names, ["hpt_railgun_fixed_medium", "int_cargorack_size6_class1", "int_engine_size5_class2",
                                 "int_fueltank_size5_class3", "int_powerplant_size6_class5"])
        rail = next(x for x in items if x["item"] == "hpt_railgun_fixed_medium")
        self.assertEqual(rail["market"], CARRIER, "sent to where you are docked")
        self.assertEqual(rail["eng"], "Weapon_HighCapacity", "the engineering travels with it")
        self.assertTrue(rail["transit_until"])
        self.assertEqual(eq.stored_now(None, evs), [])

    def test_planner_links(self):
        links = eq.planner_links(dict(LOADOUT, _fid="F1"))
        self.assertTrue(links["edsy"].startswith("https://edsy.org/#/I="))
        self.assertTrue(links["coriolis"].startswith("https://coriolis.io/import?data="))
        raw = urllib.parse.unquote(links["edsy"].split("=", 1)[1])
        back = json.loads(gzip.decompress(base64.urlsafe_b64decode(raw)))
        self.assertEqual(back["Ship"], "lakonminer")
        self.assertNotIn("_fid", back, "nothing of the FIS's own")

    def test_view_with_carrier_and_station(self):
        evs = self._snapshot("2026-11-02T10:00:00Z", [
            _item("int_powerplant_size6_class5", 10, price=2000), _item("int_powerplant_size6_class5", 11, price=2000),
            _item("lakonminer_armour_grade3", 12, loc="Military Grade Composite"),
            _item("int_lifesupport_size4_class2", 13, market=JM, system="Shinrarta Dezhra",
                  EngineerModifications="Misc_LightWeight", Level=2, Quality=0.5)])
        evs = evs[:1] + [LOADOUT,
                         {"timestamp": "2026-11-02T09:00:00Z", "event": "CarrierStats", "CarrierID": CARRIER,
                          "Callsign": "V2L-07J", "Name": "EAS AGAMEMNON"},
                         {"timestamp": "2026-11-02T09:30:00Z", "event": "Docked", "StarSystem": "Shinrarta Dezhra",
                          "MarketID": JM, "StationName": "Jameson Memorial"}] + evs[1:]
        self._journal("Journal.2026-11-02T090000.01.log", evs)
        a = Archive(self.dir)
        a.refresh(force=True)
        d = eq.build_equipment(a, self.dir, 1.8e9)
        self.assertEqual(d["count"], 4)
        self.assertEqual(d["carrier"], "EAS AGAMEMNON V2L-07J")
        pp = next(r for r in d["rows"] if r["item"] == "int_powerplant_size6_class5")
        self.assertEqual((pp["count"], pp["value"], pp["place"], pp["cls"]), (2, 4000, "carrier", "A"))
        self.assertEqual((pp["fits"], pp["better"]), (["MINER"], ["MINER"]))
        ls = next(r for r in d["rows"] if r["item"] == "int_lifesupport_size4_class2")
        self.assertEqual((ls["where"], ls["eng"]), ("Jameson Memorial", "G2 Misc · Light Weight"))
        self.assertEqual(ls["better"], ["MINER"], "engineered, the fitted one is not")
        arm = next(r for r in d["rows"] if r["group"] == "armour")
        self.assertEqual(arm["fits"], ["MINER"])
        self.assertEqual(dict(d["places"]), {"EAS AGAMEMNON V2L-07J": 3, "Jameson Memorial": 1})
        s = d["ships"][0]
        self.assertEqual((s["name"], s["fits_n"], s["better_n"]), ("MINER", 3, 2))
        self.assertNotIn("slots", s)
        self.assertTrue(eq.build_equipment(Archive(tempfile.mkdtemp()), None, 0)["empty"])

    def test_tab_in_carrier_view(self):
        car = _read("carrier.js")
        self.assertEqual(car.count('tb("equip", t("EQUIPMENT"))'), 2, "with and without a carrier")
        js = _read("equipment.js")
        self.assertIn('getJSON("/api/equipment")', js)
        self.assertEqual(js.count('rel: "noopener noreferrer"'), 2)


if __name__ == "__main__":
    unittest.main()
