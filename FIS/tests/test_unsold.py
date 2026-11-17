# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M4: unsold data at risk - exobiology valued from own sales, exploration
at the bodyvalue estimate calibrated on own sales (B6)."""

import unittest

from fis import unsold
from tests import fixtures as fx


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


class TestWhereToSell(unittest.TestCase):
    """5.0: a station buys only systems 20 ly away or more; a carrier with
    Universal Cartographics buys all of it (the user's own sales, 17.11.)."""

    def _trip(self):
        def scan(t, sysname, addr):
            return ev(t, "Scan", StarSystem=sysname, SystemAddress=addr, BodyID=1, ScanType="Detailed")
        return [ev("08:00", "FSDJump", StarSystem="Far", SystemAddress=1, StarPos=[0.0, 0.0, 0.0]),
                scan("08:01", "Far", 1),
                ev("08:10", "FSDJump", StarSystem="Near", SystemAddress=2, StarPos=[100.0, 0.0, 0.0]),
                scan("08:11", "Near", 2),
                ev("08:20", "FSDJump", StarSystem="Here", SystemAddress=3, StarPos=[110.0, 0.0, 0.0]),
                scan("08:21", "Here", 3)]

    def test_station_only_beyond_20_ly(self):
        s = unsold.build_unsold(self._trip())["sell"]
        self.assertEqual((s["station_now"], s["too_near"], s["no_position"]), (1, 2, 0))
        self.assertEqual(s["min_ly"], 20.0)
        self.assertIsNone(s["carrier"])

    def test_own_carrier_with_cartographics(self):
        evs = [ev("07:00", "CarrierStats", Crew=[{"CrewRole": "Exploration", "Activated": True, "Enabled": True}]),
               ev("07:01", "CarrierLocation", CarrierType="FleetCarrier", StarSystem="Far", SystemAddress=1)]
        c = unsold.build_unsold(evs + self._trip())["sell"]["carrier"]
        self.assertEqual((c["system"], c["uc"], c["ly"]), ("Far", True, 110.0))
        off = [ev("07:00", "CarrierStats", Crew=[{"CrewRole": "Exploration", "Activated": True, "Enabled": False}])]
        self.assertFalse(unsold.build_unsold(off + evs[1:] + self._trip())["sell"]["carrier"]["uc"])

    def test_no_position_is_not_guessed(self):
        evs = [ev("08:00", "FSDJump", StarSystem="Blank", SystemAddress=9),
               ev("08:01", "Scan", StarSystem="Blank", SystemAddress=9, BodyID=1, ScanType="Detailed")]
        s = unsold.build_unsold(self._trip() + evs)["sell"]
        self.assertEqual(s["no_position"], 1)


def _bodyvalue():
    """The plugin's bodyvalue, as the FIS loads it."""
    from fis.config import Config
    cfg = Config()
    cfg.plugin_dir = fx.PLUGIN_DIR
    cfg.use_plugin_path()
    from fis import model
    return model.plugin().bodyvalue


def _hmc(t, sysname, addr, body, first=False):
    """A scanned high-metal-content planet (mass 1 EM)."""
    return ev(t, "Scan", StarSystem=sysname, SystemAddress=addr, BodyID=body, BodyName="%s %d" % (sysname, body),
              ScanType="Detailed", PlanetClass="High metal content body", MassEM=1.0, TerraformState="",
              WasDiscovered=not first, WasMapped=True, DistanceFromArrivalLS=100.0 + body)


def _sale(t, names, earned):
    return ev(t, "MultiSellExplorationData", Discovered=[{"SystemName": n, "NumBodies": 1} for n in names],
              BaseValue=earned, Bonus=0, TotalEarnings=earned)


class TestExplorationValue(unittest.TestCase):
    """B6: the exploration data valued and calibrated on the own sales."""

    @classmethod
    def setUpClass(cls):
        cls.bv = _bodyvalue()
        cls.one = cls.bv.planet_value("High metal content body", "", 1.0)     # one scan, ~15 k
        cls.mapped = cls.bv.planet_value("High metal content body", "", 1.0, mapped=True)

    def test_calibration(self):
        sales = [(1.0, 2e6, 1.8e6), (2.0, 4e6, 4.4e6), (3.0, 1e6, 0.8e6), (4.0, 5e5, 5e6)]    # the last: too small
        c = unsold.calibration(sales)
        self.assertEqual((c["n"], c["sales"], c["factor"], c["lo"], c["hi"]), (3, 4, 0.9, 0.8, 1.1))
        later = unsold.calibration(sales, since=1.5)
        self.assertEqual((later["n"], later["factor"]), (2, None))          # below three: no factor

    def _system(self, t, name, addr, n, first=False):
        evs = [ev(t, "FSDJump", StarSystem=name, SystemAddress=addr)]
        evs += [_hmc(t, name, addr, b, first) for b in range(1, n + 1)]
        return evs

    def test_unsold_valued_with_the_own_factor(self):
        evs = []
        per = 80                                   # bodies per system: 80 x ~15 k = above 1 M estimated
        for i, f in enumerate((0.8, 0.9, 1.2)):
            nm = "Sold%d" % i
            evs += self._system("08:0%d" % i, nm, 10 + i, per)
            evs.append(_sale("08:3%d" % i, [nm], int(per * self.one * f)))
        evs += self._system("09:00", "Pending", 20, 10)
        evs += [ev("09:10", "SAAScanComplete", SystemAddress=20, BodyID=1, BodyName="Pending 1",
                   ProbesUsed=5, EfficiencyTarget=6)]
        u = unsold.build_unsold(evs, {}, body_value=self.bv)
        c = u["exploration"]["calibration"]
        self.assertEqual((c["n"], c["factor"], c["lo"], c["hi"]), (3, 0.9, 0.8, 1.2))
        v = u["exploration"]["value"]
        est = 9 * self.one + self.mapped
        self.assertEqual(v["est"], est)
        self.assertTrue(v["calibrated"])
        self.assertEqual((v["mid"], v["lo"], v["hi"], v["n"]), (round(est * 0.9), round(est * 0.8), round(est * 1.2), 3))
        self.assertEqual(u["total"], v["mid"])                   # no bio: the loss is the exploration data
        # a reset of the value model leaves the older sales out
        u2 = unsold.build_unsold(evs, {}, body_value=self.bv, value_since=10 ** 10)
        self.assertFalse(u2["exploration"]["value"]["calibrated"])
        self.assertEqual(u2["total"], 0)                         # not calibrated: not counted in the risk

    def test_loss_in_a_crash_has_a_value(self):
        evs = self._system("08:00", "Gone", 30, 3) + [analyse("08:10", "Bacterium Aurasus"), ev("08:20", "Died")]
        u = unsold.build_unsold(evs, VALUES, body_value=self.bv)
        L = u["lost_last"]
        self.assertEqual((L["systems"], L["bio"], L["bio_value"]), (1, 1, 1000000))
        self.assertEqual(L["explo"]["est"], 3 * self.one)
        self.assertFalse(L["explo"]["calibrated"])
        self.assertEqual(u["exploration"]["systems"], 0)

    def test_only_counted_without_bodyvalue(self):
        u = unsold.build_unsold(self._system("08:00", "X", 40, 2), {})
        self.assertIsNone(u["exploration"]["value"])
        self.assertEqual(u["exploration"]["bodies"], 2)


if __name__ == "__main__":
    unittest.main()
