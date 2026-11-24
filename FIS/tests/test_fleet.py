# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SHIP / CARRIER: journal archive, fleet per commander, ratings, tritium, panel."""

import json
import os
import tempfile
import time
import unittest

from fis import fleet as fl
from fis import shipview


def _mod(slot, item, health=1.0, on=True, prio=0, clip=None, hopper=None, eng=None):
    m = {"Slot": slot, "Item": item, "On": on, "Priority": prio, "Health": health}
    if clip is not None:
        m["AmmoInClip"], m["AmmoInHopper"] = clip, hopper
    if eng:
        m["Engineering"] = eng
    return m


EXPLORER = [
    _mod("MediumHardpoint1", "hpt_pulselaser_fixed_small"),
    _mod("TinyHardpoint1", "hpt_heatsinklauncher_turret_tiny", clip=1, hopper=2),
    _mod("PowerPlant", "int_powerplant_size6_class5", eng={"BlueprintName": "PowerPlant_Boosted", "Level": 2,
         "Modifiers": [{"Label": "PowerCapacity", "Value": 30.0, "OriginalValue": 25.0}]}),
    _mod("FrameShiftDrive", "int_hyperdrive_size5_class5"),
    _mod("Armour", "asp_armour_grade1"),
    _mod("Slot01_Size6", "int_fuelscoop_size6_class5", health=0.7),
    _mod("Slot02_Size5", "int_shieldgenerator_size5_class2", on=False),
    _mod("Slot03_Size1", "int_detailedsurfacescanner_tiny"),
    _mod("Decal1", "decal_explorer"),
]
MINER = [
    _mod("MediumHardpoint1", "hpt_mining_abrblstr_fixed_small"),
    _mod("MediumHardpoint2", "hpt_mining_subsurfdispmisle_fixed_medium"),
    _mod("Slot01_Size6", "int_refinery_size4_class5"),
    _mod("Slot02_Size5", "int_dronecontrol_prospector_size3_class3"),
    _mod("Slot03_Size5", "int_dronecontrol_collection_size5_class5"),
    _mod("Slot04_Size6", "int_cargorack_size6_class1"),
]


def _ev(ts, ev, **kw):
    return json.dumps(dict({"timestamp": ts, "event": ev}, **kw))


def _write_journals(d):
    a = [
        _ev("2026-01-01T10:00:00Z", "Commander", FID="F1", Name="Pilot"),
        _ev("2026-01-01T10:01:00Z", "Loadout", Ship="asp", ShipID=2, ShipName="SCOUT", ShipIdent="AA-1",
            HullHealth=1.0, CargoCapacity=8, MaxJumpRange=52.0, Rebuy=1000, Modules=EXPLORER),
        _ev("2026-01-01T11:00:00Z", "Loadout", Ship="type6", ShipID=10, ShipName="DIGGER", ShipIdent="AA-2",
            HullHealth=1.0, CargoCapacity=112, MaxJumpRange=20.0, Modules=MINER),
        # ID 7 once was an eagle - later reused for a cobra in the hangar list
        _ev("2026-01-01T12:00:00Z", "Loadout", Ship="eagle", ShipID=7, ShipName="OLD", Modules=[]),
        _ev("2026-01-02T09:00:00Z", "CarrierStats", Callsign="ABC-123", Name="TESTCARRIER", FuelLevel=1000,
            DockingAccess="all", SpaceUsage={"TotalCapacity": 25000, "Crew": 6000, "Cargo": 5000,
                                             "ShipPacks": 0, "ModulePacks": 0, "FreeSpace": 14000},
            Finance={"CarrierBalance": 1000000000, "ReserveBalance": 100, "AvailableBalance": 900000000}),
        _ev("2026-01-02T09:01:00Z", "Location", StarSystem="Alpha", StarPos=[0, 0, 0]),
        _ev("2026-01-02T09:02:00Z", "CarrierLocation", StarSystem="Alpha"),
        _ev("2026-01-02T09:10:00Z", "CarrierJumpRequest", SystemName="Beta"),
        _ev("2026-01-02T09:20:00Z", "FSDJump", StarSystem="Beta", StarPos=[400, 0, 0]),
        _ev("2026-01-02T09:30:00Z", "CarrierJump", StarSystem="Beta"),
        _ev("2026-01-02T09:31:00Z", "CarrierStats", Callsign="ABC-123", Name="TESTCARRIER", FuelLevel=1000 - 79,
            SpaceUsage={"TotalCapacity": 25000, "Crew": 6000, "Cargo": 5000, "FreeSpace": 14000},
            Finance={"CarrierBalance": 980000000, "ReserveBalance": 100, "AvailableBalance": 880000000}),
        _ev("2026-01-20T09:31:00Z", "CarrierStats", Callsign="ABC-123", Name="TESTCARRIER", FuelLevel=921,
            SpaceUsage={"TotalCapacity": 25000, "Crew": 6000, "Cargo": 5000, "FreeSpace": 14000},
            Finance={"CarrierBalance": 940000000, "ReserveBalance": 100, "AvailableBalance": 840000000}),
        _ev("2026-01-21T08:00:00Z", "StoredShips", StationName="ABC-123", StarSystem="Beta",
            ShipsHere=[{"ShipID": 10, "ShipType": "type6", "ShipType_Localised": "Type-6 Transporter", "Name": "DIGGER"},
                       {"ShipID": 7, "ShipType": "cobramkiii", "ShipType_Localised": "Cobra Mk III"}],
            ShipsRemote=[]),
        _ev("2026-01-21T08:05:00Z", "Loadout", Ship="asp", ShipID=2, ShipName="SCOUT", ShipIdent="AA-1",
            HullHealth=0.9, CargoCapacity=8, MaxJumpRange=52.0, Rebuy=1000, Modules=EXPLORER),
    ]
    # a second commander in the same folder - must not leak in
    b = [
        _ev("2026-01-22T10:00:00Z", "Commander", FID="F2", Name="Alt"),
        _ev("2026-01-22T10:01:00Z", "Loadout", Ship="anaconda", ShipID=99, ShipName="ALTSHIP", Modules=[]),
        _ev("2026-01-22T11:00:00Z", "Commander", FID="F1", Name="Pilot"),
    ]
    with open(os.path.join(d, "Journal.2026-01-01T100000.01.log"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(a) + "\n")
    with open(os.path.join(d, "Journal.2026-01-22T100000.01.log"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(b) + "\n")


class FleetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _write_journals(self.tmp.name)
        self.ar = fl.Archive(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_commander_filter_and_hangar(self):
        self.assertEqual(self.ar.commander(), ("F1", "Pilot"))
        ships = {s["id"]: s for s in self.ar.fleet()["ships"]}
        self.assertNotIn(99, ships)                       # the other commander's ship
        self.assertIn(2, ships)                           # flown after the hangar list
        self.assertTrue(ships[2]["current"])
        self.assertEqual(ships[10]["rating"]["primary"], "mining")
        self.assertEqual(ships[7]["type_name"], "Cobra Mk III")
        self.assertNotIn("rating", ships[7])              # old eagle fitting not used for the cobra

    def test_ratings(self):
        r = fl.rate_loadout({"Modules": EXPLORER, "CargoCapacity": 8, "MaxJumpRange": 52.0})
        self.assertEqual(r["roles"]["exploration"], 4)
        self.assertEqual(r["primary"], "exploration")
        self.assertIn("DSS", r["why"]["exploration"])
        m = fl.rate_loadout({"Modules": MINER, "CargoCapacity": 112, "MaxJumpRange": 20.0})
        self.assertEqual(m["roles"]["mining"], 5)
        self.assertLessEqual(m["roles"]["exploration"], 1)   # no scoop

    def test_vehicle_hangar_and_rhino(self):
        """M3: exobiology (vehicle hangar, Nomad best) and ground mining."""
        base = [{"Slot": "Slot01", "Item": "int_fuelscoop_size5_class5"},
                {"Slot": "Slot02", "Item": "int_detailedsurfacescanner_tiny"}]
        bay = [{"Slot": "Slot03", "Item": "int_buggybay_size2_class2"}]
        nomad = [{"Slot": "Slot03", "Item": "int_mkiilargebuggybay_size4_class3_free"}]
        r = lambda mods, jump, veh=(): fl.rate_loadout({"Modules": mods, "MaxJumpRange": jump}, veh)
        self.assertEqual(r(base, 70.0)["roles"]["exploration"], 4)         # no hangar: max 4
        self.assertEqual(r(base + bay, 70.0)["roles"]["exploration"], 5)
        self.assertEqual(r(base + bay, 50.0)["roles"]["exploration"], 4)
        self.assertEqual(r(base + nomad, 50.0)["roles"]["exploration"], 5)  # Nomad: one step more
        self.assertIn("Nomad hangar", r(base + nomad, 50.0)["why"]["exploration"])
        # ground mining only when the Rhino was launched from that ship
        self.assertEqual(r(base + bay, 50.0)["roles"]["mining"], 0)
        m = r(base + bay, 50.0, ["SRV Rhino"])
        self.assertEqual(m["roles"]["mining"], 2)
        self.assertIn("SRV Rhino", m["why"]["mining"])
        self.assertEqual(r(base, 50.0, ["SRV Rhino"])["roles"]["mining"], 0)   # no hangar now

    def test_module_names(self):
        self.assertEqual(fl.module_name("int_shieldgenerator_size6_class2"), "Shield Generator 6D")
        self.assertEqual(fl.module_name("hpt_pulselaser_fixed_small"), "Pulse Laser (F) S")
        self.assertEqual(fl.module_name("explorer_nx_armour_grade1"), "Lightweight Alloy")
        self.assertEqual(fl.slot_group("TinyHardpoint3"), "utility")
        self.assertEqual(fl.slot_group("Decal1"), "cosmetic")

    def test_tritium(self):
        # the formula reproduces the user's measured jumps (+-1 t)
        for ly, load, trit, used in ((385.1, 5395, 967, 77), (499.3, 4355, 1000, 96),
                                     (500.0, 7304, 1000, 104), (4.8, 8372, 895, 6)):
            self.assertLessEqual(abs(fl.tritium_for_jump(ly, load, trit) - used), 1)
        r = fl.carrier_range(1000, 5000)
        self.assertGreaterEqual(r["jumps"], 9)
        self.assertGreater(r["ly"], 4500)
        self.assertEqual(fl.carrier_range(3, 5000)["jumps"], 0)

    def test_tritium_learnt_from_own_jumps(self):
        # user 19.11.: the range follows the jumps flown. Jumps made with
        # another formula (base 30000, div 200000) teach that formula.
        def flown(ly, load, trit):
            return (ly, load, trit, int(round(5 + ly * (load + trit + 30000) / 200000)))
        legs = ((500, 4000), (480, 6000), (450, 8000), (300, 9000), (500, 9500), (250, 5000), (499, 7000))
        jumps = [flown(ly, load, 1000) for ly, load in legs]
        learnt = fl.learn_tritium(jumps + [(10.0, 5000.0, 900.0, 6.0)])     # a short hop is left out
        self.assertTrue(learnt["learnt"])
        self.assertEqual(learnt["n"], 7)
        self.assertLessEqual(learnt["max_err"], 1)
        self.assertLess(abs(learnt["div"] - 200000) / 200000, 0.05)
        self.assertLess(fl.carrier_range(9869, 400, model=learnt["model"])["per_jump"],
                        fl.carrier_range(9869, 400)["per_jump"])        # this carrier needs less
        # too few jumps, or nonsense, keep the default
        few = fl.learn_tritium(jumps[:4])
        self.assertFalse(few["learnt"])
        self.assertEqual(few["model"], (fl.TRITIUM_BASE, fl.TRITIUM_DIV))
        self.assertFalse(fl.learn_tritium([(500.0, 5000.0, 1000.0, 400.0)] * 6)["learnt"])
        self.assertIsNone(fl.learn_tritium([])["max_err"])

    def test_carrier(self):
        c = self.ar.carrier()
        self.assertEqual(c["stats"]["Callsign"], "ABC-123")
        self.assertEqual(c["jumps"][0]["used"], 79)
        self.assertEqual(c["jumps"][0]["ly"], 400.0)
        self.assertEqual(c["jumps"][0]["predicted"], 79)
        self.assertGreater(c["upkeep"]["per_week"], 0)
        view = shipview.build_carrier(self.ar, {})
        self.assertEqual(view["tritium"]["tank"], 921)
        self.assertEqual(view["ident"]["name"], "TESTCARRIER")
        self.assertGreater(view["finance"]["weeks_left"], 10)

    def test_carrier_arrival_while_offline(self):
        """Arrived while you were away: later logins do not move the arrival."""
        import os
        with open(os.path.join(self.tmp.name, "Journal.2026-02-01T090000.01.log"), "w", encoding="utf-8") as fh:
            for line in ('{"timestamp":"2026-02-01T09:00:00Z","event":"CarrierJumpRequest","SystemName":"Alpha","DepartureTime":"2026-02-01T09:15:00Z"}',
                         '{"timestamp":"2026-02-01T09:15:00Z","event":"CarrierLocation","StarSystem":"Alpha"}',
                         '{"timestamp":"2026-03-01T10:00:00Z","event":"CarrierLocation","StarSystem":"Alpha"}',
                         '{"timestamp":"2026-03-01T10:01:00Z","event":"CarrierStats","Callsign":"ABC-123","FuelLevel":850,"SpaceUsage":{}}'):
                fh.write(line + "\n")
        c = fl.Archive(self.tmp.name).carrier()
        self.assertEqual(c["arrived"], "2026-02-01T09:15:00Z")
        self.assertEqual(c["jumps"][-1]["to"], "Alpha")
        self.assertEqual(c["jumps"][-1]["ts"], "2026-02-01T09:15:00Z")

    def test_readable_module(self):
        self.assertEqual(fl.readable_module("Wake Scanner", "$hpt_cloudscanner_size0_class5_name;"), "Wake Scanner")
        self.assertEqual(fl.readable_module("$Int_FighterBayMk2_Size5_Class1_Name; (Free)",
                                            "$int_fighterbaymk2_size5_class1_free_name;"), "Fighter Hangar 5E")
        # alerts stored before the raw key was kept
        self.assertEqual(fl.readable_module("$Int_FighterBayMk2_Size5_Class1_Name; (Free)"), "Fighter Hangar 5E")

    def test_ship_flown_when_hangar_listed(self):
        """Swapping through the hangar: StoredShips is written while you sit in
        ship 34 and leaves it out; after the next swap it still belongs to the fleet."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Journal.2026-03-01T090000.01.log"), "w", encoding="utf-8") as fh:
                for e in (_ev("2026-03-01T09:00:00Z", "Commander", FID="F1", Name="X"),
                          _ev("2026-03-01T09:00:01Z", "Loadout", Ship="panthermkii", ShipID=34, ShipName="PCC", Modules=[]),
                          _ev("2026-03-01T09:00:05Z", "StoredShips", StationName="V2L-07J", StarSystem="S",
                              MarketID=1, ShipsHere=[{"ShipID": 44, "ShipType": "explorer_nx", "Name": "SILVERHAWK", "Value": 1}],
                              ShipsRemote=[]),
                          _ev("2026-03-01T09:00:09Z", "ShipyardSwap", ShipType="explorer_nx", ShipID=44,
                              StoreOldShip="PantherMkII", StoreShipID=34),
                          _ev("2026-03-01T09:00:10Z", "Loadout", Ship="explorer_nx", ShipID=44, ShipName="SILVERHAWK", Modules=[])):
                    fh.write(e + "\n")
            ids = sorted(s["id"] for s in fl.Archive(d).fleet()["ships"])
            self.assertEqual(ids, [34, 44])

    def test_ship_stored_after_hangar_list(self):
        """SL1 (5.0.1): a ship put away after the last StoredShips had no place
        ("· ?"): 23.11. a Type-11 swapped onto the carrier 10 s after the list.
        Swap, buy and transfer now place it at the station of their MarketID."""
        with tempfile.TemporaryDirectory() as d:
            recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
            with open(os.path.join(d, "Journal.2026-03-01T090000.01.log"), "w", encoding="utf-8") as fh:
                for e in (_ev("2026-03-01T09:00:00Z", "Commander", FID="F1", Name="X"),
                          _ev("2026-03-01T09:00:01Z", "Loadout", Ship="lakonminer", ShipID=37, ShipName="DIGGER",
                              CargoCapacity=322, Modules=[]),
                          _ev("2026-03-01T09:00:02Z", "Docked", StationName="ABC-123", StarSystem="S", MarketID=1,
                              StationType="FleetCarrier"),
                          _ev("2026-03-01T09:00:05Z", "StoredShips", StationName="ABC-123", StarSystem="S",
                              MarketID=1, ShipsHere=[{"ShipID": 44, "ShipType": "explorer_nx", "Name": "SCOUT", "Value": 1}],
                              ShipsRemote=[{"ShipID": 12, "ShipType": "eagle", "StarSystem": "Far", "Value": 1}]),
                          _ev("2026-03-01T09:00:15Z", "ShipyardSwap", ShipType="explorer_nx", ShipID=44,
                              StoreOldShip="LakonMiner", StoreShipID=37, MarketID=1),
                          _ev("2026-03-01T09:00:16Z", "Loadout", Ship="explorer_nx", ShipID=44, ShipName="SCOUT", Modules=[]),
                          _ev("2026-03-01T10:00:00Z", "Docked", StationName="Port Q", StarSystem="Q", MarketID=2,
                              StationType="Coriolis"),
                          _ev("2026-03-01T10:01:00Z", "ShipyardBuy", ShipType="type9", StoreOldShip="Explorer_NX",
                              StoreShipID=44, MarketID=2),
                          _ev("2026-03-01T10:01:05Z", "ShipyardNew", ShipType="type9", NewShipID=60),
                          # asked for a minute ago, an hour on the way
                          _ev(recent, "ShipyardTransfer", ShipType="Eagle", ShipID=12,
                              System="Far", ShipMarketID=9, MarketID=2, TransferTime=3600)):
                    fh.write(e + "\n")
            ar = fl.Archive(d)
            ships = {s["id"]: s for s in ar.fleet()["ships"]}
            self.assertEqual((ships[37]["stored_at"], ships[37]["location"], ships[37]["system"]),
                             ("here", "ABC-123", "S"), "swapped onto the carrier of the hangar list")
            self.assertEqual(ships[37]["cargo"], 322, "its fitting still belongs to it")
            self.assertEqual((ships[44]["stored_at"], ships[44]["location"], ships[44]["system"]),
                             ("remote", "Port Q", "Q"), "stored when buying elsewhere")
            self.assertEqual((ships[12]["location"], ships[12]["in_transit"]), ("Port Q", True),
                             "on its way to the station that asked for it")
            # sold since: gone again
            with open(os.path.join(d, "Journal.2026-03-02T090000.01.log"), "w", encoding="utf-8") as fh:
                fh.write(_ev("2026-03-02T09:00:00Z", "Commander", FID="F1", Name="X") + "\n")
                fh.write(_ev("2026-03-02T09:01:00Z", "ShipyardSell", ShipType="lakonminer", SellShipID=37,
                             MarketID=1) + "\n")
            ar.refresh(force=True)
            self.assertNotIn(37, {s["id"] for s in ar.fleet()["ships"]})

    def test_sar_role(self):
        t7 = {"Ship": "type7", "CargoCapacity": 64, "MaxJumpRange": 48.5, "FuelCapacity": {"Main": 112.0},
              "Modules": [{"Slot": "Slot01_Size5", "Item": "int_dronecontrol_fueltransfer_size5_class5"},
                          {"Slot": "Slot02_Size3", "Item": "int_multidronecontrol_rescue_size3_class3"},
                          {"Slot": "Slot03_Size5", "Item": "int_fuelscoop_size5_class5"}]}
        r = fl.rate_loadout(t7)
        self.assertEqual(r["roles"]["sar"], 5)
        self.assertEqual(r["primary"], "sar")
        self.assertIn("fuel transfer limpets", r["why"]["sar"])
        miner = {"Ship": "type8", "CargoCapacity": 256, "FuelCapacity": {"Main": 32.0},
                 "Modules": [{"Slot": "Slot01_Size5", "Item": "int_dronecontrol_collection_size5_class5"}]}
        self.assertEqual(fl.rate_loadout(miner)["roles"]["sar"], 0)

    def test_ship_panel(self):
        flags = (1 << 24) | (1 << 8) | (1 << 28) | (1 << 4)   # in ship, lights, night vision, SC; shields off
        live = {"status": {"ts": time.time(), "flags": flags, "flags2": 0, "pips": [4, 6, 2]},
                "ship": {"hull": 0.9, "fuel_capacity": 32}, "fuel": {"main": 20},
                "alerts": [{"event": "HeatWarning", "ts": time.time() - 10}]}
        s = shipview.build_shipstatus(live, self.ar, self.tmp.name)
        on = {p["key"] for p in s["panel"] if p["on"]}
        self.assertTrue({"lights", "night_vision", "supercruise", "shields_down", "heat",
                         "module_dmg", "module_off"} <= on)
        self.assertEqual(s["master"], "caution")
        self.assertEqual(s["power"]["capacity"], 30.0)
        self.assertEqual(s["power"]["pips"], [2.0, 3.0, 1.0])
        keys = {r["key"] for r in s["report"]}
        self.assertTrue({"module_damaged", "module_off"} <= keys)
        hs = [m for m in s["modules"]["utility"] if "Heat Sink" in m["name"]][0]
        self.assertEqual(hs["ammo_pct"], 100)
        self.assertNotIn("cosmetic", s["modules"])

    def test_thrusters_on_after_liftoff(self):
        # own-1: the Loadout after DockSRV on the ground has the thrusters
        # off and no new one follows Liftoff - flying, they count as on
        lo = {"Modules": [{"Slot": "MainEngines", "Item": "int_engine_size7_class5", "On": False},
                          {"Slot": "Slot02_Size5", "Item": "int_shieldgenerator_size5_class2", "On": False}]}
        ship = 1 << 24
        for flags, want in ((ship, True), (ship | 1 << 1, False), (ship | 1 << 0, False), (1 << 26, False)):
            st = {"ts": time.time(), "flags": flags}
            g, _ = shipview._ship_modules(lo, {}, self.ar, flying=shipview._flying(st, flags))
            self.assertIs(g["core"][0]["on"], want, flags)
            self.assertIs(g["optional"][0]["on"], False)
        self.assertFalse(shipview._flying({}, ship))

    def test_overheat_is_warning(self):
        live = {"status": {"ts": time.time(), "flags": (1 << 24) | (1 << 20) | (1 << 3), "flags2": 0},
                "ship": {"hull": 1.0}, "alerts": []}
        s = shipview.build_shipstatus(live, self.ar, self.tmp.name)
        self.assertEqual(s["master"], "warning")


class FsdHintTest(unittest.TestCase):
    """EN1: FSD grade per ship against the engineers that worked on your drive."""

    def _lo(self, ts, sid, level=None, eng=None):
        fsd = {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5"}
        if level:
            fsd["Engineering"] = {"Engineer": eng, "BlueprintName": "FSD_LongRange", "Level": level}
        return {"timestamp": ts, "event": "Loadout", "Ship": "asp", "ShipID": sid, "Modules": [fsd]}

    def test_engineers_and_hint(self):
        from fis.fleet import fsd_engineers, fsd_hint, fsd_of
        evs = [{"timestamp": "2026-01-01T10:00:00Z", "event": "EngineerProgress", "Engineers": [
                   {"Engineer": "Felicity Farseer", "Progress": "Unlocked", "Rank": 5},
                   {"Engineer": "Elvira Martuuk", "Progress": "Known"}]},
               self._lo("2026-01-01T11:00:00Z", 1, 5, "Felicity Farseer"),
               {"timestamp": "2026-01-02T10:00:00Z", "event": "EngineerCraft", "Engineer": "Elvira Martuuk",
                "Slot": "FrameShiftDrive", "BlueprintName": "FSD_LongRange", "Level": 3},
               self._lo("2026-01-03T10:00:00Z", 2, 2, "Felicity Farseer"),
               self._lo("2026-01-03T11:00:00Z", 3)]
        eng = fsd_engineers(evs)
        self.assertEqual([(e["engineer"], e["max_grade"], e["unlocked"]) for e in eng],
                         [("Felicity Farseer", 5, True), ("Elvira Martuuk", 3, False)])
        self.assertEqual(fsd_hint(fsd_of(evs[3]), eng), {"to": 5, "blueprint": "FSD_LongRange",
                                                        "engineers": ["Felicity Farseer"]})
        self.assertEqual(fsd_hint(fsd_of(evs[4]), eng)["to"], 5)          # not engineered: Increased Range
        self.assertIsNone(fsd_hint(fsd_of(evs[1]), eng))                 # already G5
        self.assertIsNone(fsd_of({"Modules": []}))


class LedgerCarrierTest(unittest.TestCase):
    """PL2: the carrier's upkeep over a period, readable ship types."""

    def test_upkeep_between(self):
        from fis.fleet import upkeep_between
        day = 86400.0
        bal = [(0.0, 100_000_000), (4 * day, 90_000_000), (8 * day, 95_000_000)]
        tr = [{"ts": 6 * day, "deposit": 10_000_000, "withdraw": 0}]       # you paid in 10 M
        u = upkeep_between(bal, tr, None)
        self.assertEqual((u["cost"], u["days"], u["readings"]), (15_000_000, 8.0, 3))
        self.assertEqual(upkeep_between(bal, tr, 4 * day)["cost"], 5_000_000)
        self.assertIsNone(upkeep_between(bal, tr, 7 * day))                   # one reading left
        up = upkeep_between([(0.0, 1), (5 * day, 50)], [], None)
        self.assertEqual((up["cost"], up["drift"]), (None, 49))                # rose: no cost made up

    def test_type_label(self):
        from fis.fleet import type_label
        self.assertEqual(type_label({"krait_light": "Krait Phantom"}, "Krait_Light"), "Krait Phantom")
        self.assertEqual(type_label({}, "type9_military"), "Type9 Military")
        self.assertEqual(type_label({}, None), "?")


if __name__ == "__main__":
    unittest.main()
