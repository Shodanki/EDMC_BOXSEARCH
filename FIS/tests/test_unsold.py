# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M4: unsold data at risk - exobiology valued from own sales, exploration counted."""

import unittest

from fis import unsold


def ev(ts, name, **kw):
    return dict({"timestamp": "2026-11-10T%s:00Z" % ts, "event": name}, **kw)


def analyse(ts, sp, first=False, addr=1):
    return ev(ts, "ScanOrganic", ScanType="Analyse", Species_Localised=sp, Variant_Localised=sp + " - Teal",
              WasLogged=not first, SystemAddress=addr)


VALUES = {"Bacterium Aurasus": {"value": 1000000, "bonus": 4000000},
          "Stratum Tectonicas": {"value": 19010800, "bonus": 0}}


class TestUnsold(unittest.TestCase):
    def test_bio_pending_value_and_partial_sale(self):
        evs = [ev("08:00", "FSDJump", StarSystem="Alpha", SystemAddress=1),
               # first footfall on body 2: nobody had walked there, then you did
               ev("08:01", "Scan", StarSystem="Alpha", SystemAddress=1, BodyID=2, BodyName="Alpha 2",
                  ScanType="Detailed", DistanceFromArrivalLS=50.0, Landable=True, WasFootfalled=False),
               ev("08:05", "Disembark", OnPlanet=True, SystemAddress=1, Body="Alpha 2", BodyID=2),
               dict(analyse("08:10", "Bacterium Aurasus", first=True), Body=2),
               analyse("08:20", "Stratum Tectonicas"),
               analyse("08:30", "Osseus Spiralis"),               # never sold: no value
               ev("09:00", "SellOrganicData", BioData=[{"Species_Localised": "Stratum Tectonicas"}])]
        u = unsold.build_unsold(evs, VALUES)
        b = u["bio"]
        self.assertEqual((b["count"], b["priced"], b["unknown"], b["first"]), (2, 1, 1, 1))
        self.assertEqual(b["value"], 5000000)                   # 1 M + 4x first-footfall bonus
        self.assertEqual(b["items"][0]["system"], "Alpha")

    def test_exploration_counted_until_sold(self):
        def scan(t, sysname, addr, body, typ="Detailed"):
            return ev(t, "Scan", StarSystem=sysname, SystemAddress=addr, BodyID=body, ScanType=typ)
        evs = [ev("08:00", "FSDJump", StarSystem="A", SystemAddress=1),
               ev("08:01", "FSSDiscoveryScan", SystemName="A", SystemAddress=1, BodyCount=12),
               scan("08:02", "A", 1, 0, "AutoScan"), scan("08:03", "A", 1, 3),
               ev("08:05", "SAAScanComplete", SystemAddress=1, BodyID=3),
               ev("08:10", "FSDJump", StarSystem="B", SystemAddress=2),
               ev("08:11", "FSSDiscoveryScan", SystemName="B", SystemAddress=2, BodyCount=5),
               scan("08:12", "B", 2, 0, "AutoScan"), scan("08:13", "B", 2, 1), scan("08:14", "B", 2, 2),
               ev("09:00", "MultiSellExplorationData", Discovered=[{"SystemName": "A", "NumBodies": 12}])]
        x = unsold.build_unsold(evs)["exploration"]
        self.assertEqual((x["systems"], x["bodies"], x["mapped"]), (1, 3, 0))
        # 11.11.: back in A - the honk and the arrival star's scan are no new data
        more = [ev("10:00", "FSDJump", StarSystem="A", SystemAddress=1),
                ev("10:01", "FSSDiscoveryScan", SystemName="A", SystemAddress=1, BodyCount=12),
                scan("10:02", "A", 1, 0, "AutoScan"),
                # a nav beacon hands over data that is not yours to sell
                ev("10:30", "FSDJump", StarSystem="C", SystemAddress=3),
                scan("10:31", "C", 3, 1, "NavBeaconDetail"), scan("10:31", "C", 3, 2, "NavBeaconDetail")]
        x = unsold.build_unsold(evs + more)["exploration"]
        self.assertEqual((x["systems"], x["bodies"]), (1, 3))
        # a new body in A after the sale is new data again
        x = unsold.build_unsold(evs + more + [scan("10:40", "A", 1, 7)])["exploration"]
        self.assertEqual((x["systems"], x["bodies"]), (2, 4))

    def test_death_loses_everything(self):
        evs = [analyse("08:10", "Bacterium Aurasus"),
               ev("08:11", "FSSDiscoveryScan", SystemName="A", SystemAddress=1, BodyCount=3),
               ev("08:12", "Scan", StarSystem="A", SystemAddress=1, BodyID=0, ScanType="AutoScan"),
               ev("08:30", "Died")]
        u = unsold.build_unsold(evs, VALUES)
        self.assertEqual((u["bio"]["count"], u["exploration"]["systems"]), (0, 0))
        self.assertEqual((u["lost_last"]["bio"], u["lost_last"]["systems"]), (1, 1))

    def test_advice_from_threshold(self):
        evs = [analyse("08:%02d" % i, "Stratum Tectonicas") for i in range(3)]
        self.assertEqual(unsold.build_unsold(evs, VALUES)["advice"], "sell")      # 57 M
        self.assertIsNone(unsold.build_unsold(evs[:1], VALUES)["advice"])        # 19 M

    def test_first_logged_alone_pays_no_bonus(self):
        # 11.11.: landed where others had walked - "first logged", but base value only
        evs = [ev("08:00", "FSDJump", StarSystem="Alpha", SystemAddress=1),
               ev("08:01", "Scan", StarSystem="Alpha", SystemAddress=1, BodyID=2, BodyName="Alpha 2",
                  ScanType="Detailed", DistanceFromArrivalLS=50.0, Landable=True, WasFootfalled=True),
               ev("08:05", "Disembark", OnPlanet=True, SystemAddress=1, Body="Alpha 2", BodyID=2),
               dict(analyse("08:10", "Bacterium Aurasus", first=True), Body=2)]
        b = unsold.build_unsold(evs, VALUES)["bio"]
        self.assertEqual((b["value"], b["first"]), (1000000, 0))

    def test_risk_levels(self):
        st = [analyse("08:%02d" % i, "Stratum Tectonicas") for i in range(6)]
        self.assertEqual(unsold.build_unsold(st[:1], VALUES)["risk"], "low")        # 19 M
        self.assertEqual(unsold.build_unsold(st[:3], VALUES)["risk"], "moderate")   # 57 M
        self.assertEqual(unsold.build_unsold(st, VALUES)["risk"], "high")           # 114 M

    def test_own_limits(self):
        """4.11: each commander sets the limits on the settings page."""
        st = [analyse("08:%02d" % i, "Stratum Tectonicas") for i in range(3)]       # 57 M
        careful = {"moderate_mcr": 10, "high_mcr": 40, "sell_mcr": 20}
        u = unsold.build_unsold(st, VALUES, careful)
        self.assertEqual((u["risk"], u["advice"]), ("high", "sell"))
        self.assertEqual(u["risk_cr"], {"moderate": 10_000_000, "high": 40_000_000})
        self.assertEqual((u["warn_cr"], u["warn_systems"]), (20_000_000, 100))     # missing: default
        bold = {"moderate_mcr": 500, "high_mcr": 1000, "sell_mcr": 800, "sell_systems": 1000}
        u = unsold.build_unsold(st, VALUES, bold)
        self.assertEqual((u["risk"], u["advice"]), ("low", None))
        self.assertEqual(unsold.build_unsold(st, VALUES)["risk"], "moderate")      # no limits: defaults

    def test_sheet_follows_changed_limits(self):
        """The SHIP sheet's cache holds while the journals are unchanged - but
        new limits from the settings page count at once."""
        from fis import shipview
        st = [analyse("08:%02d" % i, "Stratum Tectonicas") for i in range(3)]       # 57 M

        class Archive:
            rev = 7

            def refresh(self):
                pass

            def events(self):
                return st

            def organic_values(self):
                return VALUES
        a = Archive()
        self.assertEqual(shipview._unsold(a)["risk"], "moderate")
        self.assertEqual(shipview._unsold(a, {"moderate_mcr": 10, "high_mcr": 40})["risk"], "high")
        self.assertEqual(shipview._unsold(a)["risk"], "moderate")

    def test_first_discovery_and_first_footfall_are_valuable(self):
        evs = [ev("08:00", "FSDJump", StarSystem="New", SystemAddress=5),
               ev("08:01", "Scan", StarSystem="New", SystemAddress=5, BodyID=0, BodyName="New A",
                  ScanType="AutoScan", DistanceFromArrivalLS=0.0, WasDiscovered=False),
               ev("08:02", "Scan", StarSystem="New", SystemAddress=5, BodyID=3, BodyName="New 1",
                  ScanType="Detailed", DistanceFromArrivalLS=300.0, WasDiscovered=False,
                  Landable=True, WasFootfalled=False),
               ev("08:10", "Disembark", SRV=False, OnPlanet=True, SystemAddress=5, Body="New 1", BodyID=3),
               ev("08:20", "ScanOrganic", ScanType="Analyse", Species_Localised="Osseus Spiralis",
                  SystemAddress=5, Body=3, WasLogged=True)]
        u = unsold.build_unsold(evs, VALUES)
        self.assertEqual((u["first_systems"], u["footfall_bio"]), (1, 1))
        self.assertEqual(u["risk"], "moderate")            # little money, but nothing to get again
        sold = evs + [ev("09:00", "MultiSellExplorationData", Discovered=[{"SystemName": "New"}])]
        self.assertEqual(unsold.build_unsold(sold, VALUES)["first_systems"], 0)


if __name__ == "__main__":
    unittest.main()
