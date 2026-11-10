# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""E5: the selected target - Status.json destination, FSD target, locked ship."""

import unittest

from fis import shipview
from fis.live import LiveTracker

TS = "2026-11-10T12:00:00Z"


def ev(name, **kw):
    return dict({"timestamp": TS, "event": name}, **kw)


class TestShipTargeted(unittest.TestCase):
    def setUp(self):
        self.lt = LiveTracker(".")
        self.lt.feed(ev("FSDJump", StarSystem="Sol", SystemAddress=10477373803, StarPos=[0, 0, 0]))

    def test_stages_add_up_and_clear(self):
        self.lt.feed(ev("ShipTargeted", TargetLocked=True, Ship="anaconda", Ship_Localised="Anaconda", ScanStage=0))
        self.lt.feed(ev("ShipTargeted", TargetLocked=True, Ship="anaconda", ScanStage=1,
                        PilotName="$npc_name_decorate:#name=Ray;", PilotName_Localised="Ray", PilotRank="Elite"))
        self.lt.feed(ev("ShipTargeted", TargetLocked=True, Ship="anaconda", ScanStage=3,
                        PilotName="$npc_name_decorate:#name=Ray;", PilotName_Localised="Ray", PilotRank="Elite",
                        ShieldHealth=80.0, HullHealth=55.5, Faction="Pirates", LegalStatus="Wanted",
                        Bounty=120000, Subsystem="$int_powerplant_size8_class5_name;",
                        Subsystem_Localised="Power Plant", SubsystemHealth=97.0))
        t = self.lt.snapshot()["ship_target"]
        self.assertEqual((t["ship"], t["pilot"], t["rank"], t["stage"]), ("Anaconda", "Ray", "Elite", 3))
        self.assertAlmostEqual(t["shield"], 0.80)
        self.assertAlmostEqual(t["hull"], 0.555)
        self.assertEqual((t["legal"], t["bounty"], t["subsystem"]), ("Wanted", 120000, "Power Plant"))
        self.assertAlmostEqual(t["subsystem_health"], 0.97)
        # lock lost
        self.lt.feed(ev("ShipTargeted", TargetLocked=False))
        self.assertIsNone(self.lt.snapshot()["ship_target"])

    def test_other_ship_starts_fresh(self):
        self.lt.feed(ev("ShipTargeted", TargetLocked=True, Ship="anaconda", ScanStage=1,
                        PilotName="A", PilotRank="Elite"))
        self.lt.feed(ev("ShipTargeted", TargetLocked=True, Ship="python", ScanStage=0))
        t = self.lt.snapshot()["ship_target"]
        self.assertEqual(t["ship"], "Python")
        self.assertNotIn("pilot", t)

    def test_jump_and_supercruise_clear_the_lock(self):
        for clear in (ev("SupercruiseEntry", StarSystem="Sol"),
                      ev("FSDJump", StarSystem="Alpha Centauri", SystemAddress=1, StarPos=[1, 0, 0])):
            self.lt.feed(ev("ShipTargeted", TargetLocked=True, Ship="sidewinder", ScanStage=0))
            self.assertIsNotNone(self.lt.snapshot()["ship_target"])
            self.lt.feed(clear)
            self.assertIsNone(self.lt.snapshot()["ship_target"], clear["event"])


class TestVehicle(unittest.TestCase):
    """M2: which surface vehicle is out (LaunchSRV / LaunchVessel)."""
    def test_launch_and_dock(self):
        lt = LiveTracker(".")
        lt.feed(ev("LaunchSRV", SRVType="mev_rhino", SRVType_Localised="SRV Rhino"))
        self.assertEqual(lt.snapshot()["vehicle"], "SRV Rhino")
        lt.feed(ev("DockSRV", SRVType="mev_rhino"))
        self.assertIsNone(lt.snapshot()["vehicle"])
        lt.feed(ev("LaunchVessel", VesselType="lander01", VesselType_Localised="Nomad"))
        self.assertEqual(lt.snapshot()["vehicle"], "Nomad")
        lt.feed(ev("SRVDestroyed"))
        self.assertIsNone(lt.snapshot()["vehicle"])


class TestSuit(unittest.TestCase):
    """M5: suit and weapons from SuitLoadout, backpack from Backpack.json."""
    def test_suit_names_mods_weapons(self):
        lt = LiveTracker(".")
        # the journal sometimes leaves the localised name as a "$...;" key
        lt.feed(ev("SuitLoadout", SuitName="explorationsuit_class5", SuitName_Localised="$ExplorationSuit_Class1_Name;",
                   SuitMods=["suit_nightvision", "suit_somethingnew"], LoadoutName="Genetics A5",
                   Modules=[{"SlotName": "PrimaryWeapon1", "ModuleName": "wpn_m_assaultrifle_plasma_fauto",
                             "ModuleName_Localised": "Manticore Oppressor", "Class": 2, "WeaponMods": ["x"]}]))
        s = lt.snapshot()["suit"]
        self.assertEqual((s["name"], s["class"], s["loadout"]), ("Artemis Suit", 5, "Genetics A5"))
        self.assertEqual(s["mods"], ["Night Vision", "somethingnew"])
        self.assertEqual(s["weapons"], [{"slot": "PrimaryWeapon1", "name": "Manticore Oppressor", "class": 2, "mods": 1}])

    def test_backpack(self):
        import json
        import os
        import tempfile
        from fis.config import Config
        from tests import fixtures as fx
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        from fis import model
        d = tempfile.mkdtemp(prefix="fis-bp-")
        with open(os.path.join(d, "Backpack.json"), "w", encoding="utf-8") as fh:
            json.dump({"timestamp": TS, "event": "Backpack", "Items": [{"Name": "x", "Count": 2}],
                       "Components": [], "Data": [{"Name": "y", "Count": 1}],
                       "Consumables": [{"Name": "healthpack", "Name_Localised": "Medkit", "Count": 1},
                                       {"Name": "energycell", "Name_Localised": "Energy Cell", "Count": 3}]}, fh)
        b = model.backpack(d)
        self.assertEqual(b["consumables"], [{"name": "Medkit", "count": 1}, {"name": "Energy Cell", "count": 3}])
        self.assertEqual((b["items"], b["components"], b["data"]), (2, 0, 1))
        self.assertIsNone(model.backpack(os.path.join(d, "missing")))


class FakeDb:
    def body(self, id64, body_id):
        return {"name": "Sol 3", "arrival_ls": 499.0} if (id64, body_id) == (10477373803, 3) else None


class TestBuildTarget(unittest.TestCase):
    def test_destination_in_this_system_named_from_db(self):
        live = {"system": {"name": "Sol", "id64": 10477373803},
                "status": {"destination": {"system": 10477373803, "body": 3, "name": "Earth"}}}
        d = shipview.build_target(live, FakeDb())["destination"]
        self.assertTrue(d["here"])
        self.assertEqual((d["name"], d["body"], d["arrival_ls"]), ("Earth", "Sol 3", 499.0))

    def test_destination_elsewhere_takes_the_fsd_name(self):
        live = {"system": {"name": "Sol", "id64": 10477373803},
                "target": {"name": "Alpha Centauri", "id64": 1, "star_class": "G"},
                "status": {"destination": {"system": 1, "body": 0, "name": "Alpha Centauri"}}}
        T = shipview.build_target(live, FakeDb())
        self.assertFalse(T["destination"]["here"])
        self.assertEqual(T["destination"]["system"], "Alpha Centauri")
        self.assertEqual(T["fsd"]["name"], "Alpha Centauri")

    def test_nothing_selected(self):
        T = shipview.build_target({"system": {"name": "Sol", "id64": 5}, "status": {}})
        self.assertEqual((T["destination"], T["fsd"], T["ship"]), (None, None, None))


if __name__ == "__main__":
    unittest.main()
