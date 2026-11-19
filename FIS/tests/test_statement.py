# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.0 GV1: GAIN / LOSS as an annual statement - the lines of the income
statement add up to the ledger, periods with the carrier's upkeep (~),
segments with their time, the balance sheet balances, the outlook counts
empty weeks and names no refund without a source."""

import os
import re
import unittest
from datetime import datetime, timezone

from fis import ledger, statement

DAY = 86400.0


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def ev(when, name, **kw):
    return dict({"timestamp": when, "event": name}, **kw)


JOURNAL = [
    ev("2026-11-02T08:00:00Z", "LoadGame", ShipID=1, Ship="mandalay", Credits=10_000_000),
    ev("2026-11-02T08:05:00Z", "FSDJump"),
    ev("2026-11-02T08:15:00Z", "ScanOrganic"),                          # 10 min exploration
    ev("2026-11-02T08:25:00Z", "SellOrganicData", BioData=[{"Value": 20_000_000, "Bonus": 0}]),   # 10 min bio
    ev("2026-11-02T08:30:00Z", "ProspectedAsteroid"),                   # 5 min bio
    ev("2026-11-02T08:40:00Z", "MarketSell", Type="painite", Count=10, TotalSale=5_000_000, AvgPricePaid=0),
    ev("2026-11-02T08:45:00Z", "BuyDrones", TotalCost=10_000),
    ev("2026-11-02T08:50:00Z", "MarketBuy", Type="tritium", Count=100, TotalCost=5_000_000),   # 20 min mining
    ev("2026-11-02T13:00:00Z", "RepairAll", Cost=200_000),              # after a 4 h pause: not counted
    ev("2026-11-02T13:05:00Z", "NpcCrewPaidWage", Amount=300_000),      # ... nor what follows it
    ev("2026-11-03T09:00:00Z", "Resurrect", Option="rebuy", Cost=1_000_000),
    ev("2026-11-10T09:00:00Z", "ModuleBuy", BuyPrice=2_000_000, SellPrice=0, ShipID=1),
    ev("2026-11-10T09:30:00Z", "MultiSellExplorationData", TotalEarnings=3_000_000),
]
NOW = ts("2026-11-18T12:00:00Z")
CARRIER = {"stats": {"CarrierID": 7, "Finance": {"CarrierBalance": 1_000_000_000, "AvailableBalance": 270_000_000}},
           "balances": [(ts("2026-11-02T00:00:00Z"), 1_100_000_000), (ts("2026-11-06T00:00:00Z"), 1_080_000_000),
                        (ts("2026-11-09T00:00:00Z"), 1_000_000_000)],
           "transfers": [], "upkeep": {"per_week": 25_000_000}}
FRONTIER = {"per_week": 27_000_000, "core": 5_000_000, "services": 22_000_000, "week_to_date": 20_000_000,
            "cargo_value": 300_000_000, "orders_reserved": 10_000_000, "market_profit": 585_390, "bar_profit": 0,
            "black_profit": 0, "balance": 1_000_000_000}


class StatementTest(unittest.TestCase):
    def setUp(self):
        self.led = ledger.build_ledger(JOURNAL, now=NOW)

    def test_bounds(self):
        a, b = statement.bounds("week", "2026-W46")
        self.assertEqual(datetime.fromtimestamp(a, timezone.utc).strftime("%a %d.%m."), "Mon 09.11.")
        self.assertEqual(b - a, 7 * DAY)
        a, b = statement.bounds("month", "2026-12")
        self.assertEqual(datetime.fromtimestamp(b, timezone.utc).year, 2027)
        self.assertEqual(statement.bounds("year", "2026")[1] - statement.bounds("year", "2026")[0], 365 * DAY)

    def test_lines_add_up_to_the_ledger(self):
        st = statement.statement(statement._merge(self.led["periods"]["year"], "all"))
        L = st["lines"]
        T = self.led["totals"]
        self.assertEqual(L["revenue"]["cr"] + L["other_income"]["cr"], T["income"])
        self.assertEqual(sum(L[k]["cr"] for k in ("material", "personnel", "write_downs", "other_costs")), T["costs"])
        self.assertEqual(st["result"], T["net"])
        self.assertEqual({r["key"]: r["cr"] for r in L["material"]["rows"]}, {"limpets": 10_000, "tritium": 5_000_000})
        self.assertEqual(L["personnel"]["cr"], 300_000)
        self.assertEqual(L["write_downs"]["cr"], 1_000_000)
        self.assertEqual(st["invest"], 2_000_000)
        self.assertFalse(st["est"])

    def test_tritium_bought_is_material_not_goods(self):
        self.assertEqual({r["key"]: r["cr"] for r in self.led["totals"]["cost_rows"]}["tritium"], 5_000_000)

    def test_trade_gross_cost_of_sales(self):
        """GV2: trade revenue is the full sale, its goods' cost a line of its
        own under material - the operating result is the same as with the
        profit alone; buying goods is no cost, mined goods have none."""
        trip = JOURNAL + [ev("2026-11-10T10:00:00Z", "MarketBuy", Type="gold", Count=10, TotalCost=400_000),
                          ev("2026-11-10T10:30:00Z", "MarketSell", Type="gold", Count=10, TotalSale=500_000,
                             AvgPricePaid=40_000)]
        st = statement.statement(statement._merge(ledger.build_ledger(trip, now=NOW)["periods"]["year"], "all"))
        L = st["lines"]
        self.assertEqual({r["key"]: r["cr"] for r in L["revenue"]["rows"]}["trade"], 500_000)
        self.assertEqual(L["material"]["rows"][0], {"key": "cogs", "cr": 400_000})
        base = statement.statement(statement._merge(self.led["periods"]["year"], "all"))
        self.assertEqual(st["result"], base["result"] + 100_000)      # exactly the profit, as before GV2
        self.assertNotIn("cogs", [r["key"] for r in base["lines"]["material"]["rows"]])   # painite: mined
        seg = {r["seg"]: r for r in statement.segments(statement._merge(
            ledger.build_ledger(trip, now=NOW)["periods"]["year"], "all"), None, {})}
        self.assertEqual((seg["trade"]["revenue"], seg["trade"]["net"]), (500_000, 100_000))

    def test_periods_with_carrier_upkeep(self):
        sts = statement.statements(self.led["periods"], CARRIER, 22 / 27, NOW)
        weeks = {s["label"]: s for s in sts["week"]}
        self.assertEqual(sts["week"][0]["label"], "2026-W47")          # newest first, the running week too
        self.assertTrue(sts["week"][0]["running"])
        w45 = weeks["2026-W45"]                                        # 02.-08.11.: readings 02. and 06.
        self.assertEqual(w45["lines"]["personnel"]["cr"], 300_000 + round(20_000_000 * 22 / 27))
        self.assertEqual(w45["lines"]["other_costs"]["rows"][-1]["key"], "carrier_core")
        self.assertTrue(w45["est"])
        self.assertEqual(weeks["2026-W46"]["result"], 3_000_000)       # one reading only: no upkeep
        # all time: 100 M over 7 days of readings, crew share under personnel
        self.assertEqual(sts["all"]["lines"]["personnel"]["cr"], 300_000 + round(100_000_000 * 22 / 27))
        # without Frontier's split all upkeep is one line of other costs
        w = {s["label"]: s for s in statement.statements(self.led["periods"], CARRIER, None, NOW)["week"]}["2026-W45"]
        self.assertEqual(w["lines"]["other_costs"]["rows"][-1], {"key": "carrier_upkeep", "cr": 20_000_000, "est": True})

    def test_activity_time(self):
        sec = statement.activity_time(JOURNAL)
        self.assertEqual(round(sec["exploration"] / 60), 10)
        self.assertEqual(round(sec["exobiology"] / 60), 15)
        self.assertEqual(round(sec["mining"] / 60), 20)                # rock - sale - drones - tritium buy
        self.assertEqual(set(sec), {"exploration", "exobiology", "mining"})   # the 4 h pause and after: none
        late = statement.activity_time(JOURNAL, since=ts("2026-11-02T08:28:00Z"))
        self.assertEqual((late.get("exploration"), round(late["mining"] / 60)), (None, 20))

    def test_segments(self):
        every = statement._merge(self.led["periods"]["year"], "all")
        rows = {r["seg"]: r for r in statement.segments(every, {"cost": 7_000_000}, {"mining": 7200.0},
                                                       {"mining": {"limpets": 10_000}})}
        self.assertEqual(rows["mining"]["net"], 5_000_000 - 10_000)   # GV2: limpets as allocated ship costs
        self.assertEqual((rows["mining"]["ship_costs"], rows["mining"]["est"]), (10_000, True))
        self.assertEqual(rows["mining"]["per_hour"], round((5_000_000 - 10_000) / 2))
        self.assertEqual((rows["carrier"]["costs"], rows["carrier"]["est"]), (5_000_000 + 7_000_000, True))
        self.assertIsNone(rows["exobiology"]["per_hour"])             # no time: no rate

    def test_ship_costs_to_the_main_segment(self):
        """GV2: a ship's running costs go to the segment the commander mainly
        ran with it in that session (more than half its activity time);
        the 02.11. session is split (10/15/20 min): unallocated. The sums
        stay those of the statement."""
        trip = JOURNAL + [
            ev("2026-11-11T08:00:00Z", "LoadGame", ShipID=2, Ship="anaconda", Credits=1),
            ev("2026-11-11T08:05:00Z", "FSDJump"),
            ev("2026-11-11T08:15:00Z", "FSDJump"),
            ev("2026-11-11T08:20:00Z", "RefuelAll", Cost=5_000),                 # still exploring
            ev("2026-11-11T08:25:00Z", "ScanOrganic"),                          # 20 min explo, 5 bio
            ev("2026-11-11T08:30:00Z", "RepairAll", Cost=20_000),
            ev("2026-11-11T08:35:00Z", "ShipyardSwap", ShipID=3, ShipType="python"),
            ev("2026-11-11T09:00:00Z", "BuyAmmo", Cost=7_000),                   # ship 3, after a pause: no activity
        ]
        led = ledger.build_ledger(trip, now=NOW)
        mains = statement.main_segments(trip)
        self.assertEqual(mains[(ts("2026-11-11T08:00:00Z"), 2)], "exploration")
        self.assertNotIn((ts("2026-11-02T08:00:00Z"), 1), mains)              # 20 of 45 min mining: not more than half
        al = statement.allocate(led["ship_costs"], mains)
        self.assertEqual(al["exploration"], {"fuel": 5_000, "repairs": 20_000})
        self.assertEqual(al["unallocated"], {"limpets": 10_000, "repairs": 200_000, "ship_loss": 1_000_000,
                                             "ammo": 7_000})
        every = statement._merge(led["periods"]["year"], "all")
        ship_keys = ("fuel", "repairs", "ammo", "limpets", "ship_loss")
        self.assertEqual(sum(sum(v.values()) for v in al.values()), sum(every["costs"].get(k, 0) for k in ship_keys))
        rows = statement.segments(every, None, statement.activity_time(trip), al)
        self.assertEqual(rows[-1]["seg"], "unallocated")                     # last, not ranked
        ex = next(r for r in rows if r["seg"] == "exploration")
        self.assertEqual((ex["ship_costs"], ex["net"], ex["est"]), (25_000, 3_000_000 - 25_000, True))
        # one week only: the allocation follows the period
        self.assertEqual(statement.allocate(led["ship_costs"], mains, {"2026-W46"}), {
            "exploration": {"fuel": 5_000, "repairs": 20_000}, "unallocated": {"ammo": 7_000}})
        # the statement keeps its totals
        self.assertEqual(statement.statement(every)["result"], led["totals"]["net"])

    def test_balance_sheet_balances(self):
        ships = [{"value": 100_000_000}, {"value": None}]
        bs = statement.balance_sheet(ships, CARRIER, FRONTIER, 5_000_000, {"bio": 1_000_000, "explo": {"mid": 2_000_000}}, None)
        self.assertEqual(bs["assets"], 100_000_000 + 300_000_000 + 3_000_000 + 5_000_000 + 1_000_000_000)
        self.assertEqual(bs["equity"], bs["assets"] - 7_000_000 - 10_000_000)
        self.assertEqual(bs["liabilities"], bs["assets"])
        self.assertEqual(bs["unknown"], ["carrier"])                   # no CarrierBuy in the journals: no price
        self.assertEqual(bs["fixed"][0]["missing"], 1)

    def test_outlook(self):
        o = statement.outlook(self.led["periods"], CARRIER, FRONTIER, 5_000_000, JOURNAL, NOW)
        self.assertEqual(o["carrier_source"], "frontier")
        self.assertEqual(o["carrier_weeks"], 10.0)                     # 270 M / 27 M
        self.assertAlmostEqual(o["carrier_until"], NOW + 70 * DAY)
        R = o["run"]
        self.assertEqual((R["from"], R["to"], R["weeks"], R["played"]), ("2026-W43", "2026-W46", 4, 2))
        self.assertEqual(R["income"], round((25_000_000 + 3_000_000) / 4))     # empty weeks count as nothing
        self.assertEqual(o["burn"], R["costs"] + 27_000_000)
        self.assertIsNone(o["decommission"])                           # never asked: unknown, no guess

    def test_decommission_only_from_the_journal(self):
        evs = [ev("2026-11-01T10:00:00Z", "CarrierDecommission", CarrierID=7, ScrapRefund=4_850_000_000, ScrapTime=1),
               ev("2026-11-02T10:00:00Z", "CarrierCancelDecommission", CarrierID=7)]
        d = statement.decommission(evs, 7)
        self.assertEqual((d["refund"], d["cancelled"]), (4_850_000_000, True))
        self.assertFalse(statement.decommission(evs[:1], 7)["cancelled"])
        self.assertIsNone(statement.decommission(evs, 8))

    def test_build_and_views(self):
        out = statement.build(self.led, CARRIER, FRONTIER, [{"value": 1}], JOURNAL, 5_000_000, None, NOW)
        self.assertEqual(out["carrier_memo"]["market_profit"], 585_390)
        self.assertEqual(len(out["course"]["cash"]), 1)
        self.assertEqual(len(out["course"]["carrier"]), 3)
        web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
        with open(os.path.join(web, "js", "ledgerbook.js"), encoding="utf-8") as fh:
            js = fh.read()
        with open(os.path.join(web, "css", "fis.css"), encoding="utf-8") as fh:
            css = fh.read()
        gv = "\n".join(line for line in css.splitlines() if line.startswith(".gv-"))
        self.assertNotIn("animation", gv)                              # nothing moves, nothing blinks
        self.assertFalse(re.search(r"#[0-9a-fA-F]{3,6}\b", gv))        # theme colours only
        for pane in ("statementPane", "balancePane", "segmentsPane", "outlookPane"):
            self.assertIn("export function " + pane, js)
        # own-6 (user 19.11.): the five GuV tabs stood 76-137 px out of the
        # narrow overview frame in every theme - the tab bar must wrap
        rule = re.search(r"^\.kc-tabs \{([^}]*)\}", css, re.M)
        self.assertTrue(rule and "flex-wrap: wrap" in rule.group(1))


if __name__ == "__main__":
    unittest.main()
