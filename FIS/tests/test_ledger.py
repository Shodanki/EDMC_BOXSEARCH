# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.0 GAIN / LOSS: income, running costs and investment per ship and for
the commander, and the rest the credit balance shows."""

import unittest

from fis import fleet, ledger


def ev(day, hm, name, **kw):
    return dict({"timestamp": "2026-11-%02dT%s:00Z" % (day, hm), "event": name}, **kw)


def rows(acc):
    return {r["key"]: r["cr"] for r in acc}


TRIP = [
    ev(10, "08:00", "LoadGame", ShipID=1, Ship="explorer_nx", ShipName="SCOUT", Credits=1_000_000),
    ev(10, "08:10", "RefuelAll", Cost=500),
    ev(10, "09:00", "SellOrganicData", BioData=[{"Value": 2_000_000, "Bonus": 0}, {"Value": 1_000_000, "Bonus": 4_000_000}]),
    ev(10, "09:05", "MultiSellExplorationData", TotalEarnings=300_000),
    ev(10, "09:10", "RepairAll", Cost=1_500),
    # a new ship: its price belongs to the ship the shipyard names next
    ev(10, "10:00", "ShipyardBuy", ShipType="mandalay", ShipPrice=15_000_000, StoreOldShip="explorer_nx", StoreShipID=1),
    ev(10, "10:00", "ShipyardNew", ShipType="mandalay", NewShipID=2),
    ev(10, "10:05", "ModuleBuy", BuyPrice=1_200_000, SellPrice=200_000, Ship="mandalay", ShipID=2),
    ev(10, "10:30", "MarketBuy", Type="gold", Count=10, BuyPrice=40_000, TotalCost=400_000),
    ev(10, "11:00", "MarketSell", Type="gold", Count=10, SellPrice=50_000, TotalSale=500_000, AvgPricePaid=40_000),
    ev(10, "11:10", "MarketSell", Type="tritium", Count=100, SellPrice=50_000, TotalSale=5_000_000, AvgPricePaid=0),
    ev(10, "11:20", "CommunityGoalReward", Reward=10_000_000),
    ev(10, "11:30", "CarrierBankTransfer", Deposit=1_000_000, PlayerBalance=0),
    ev(10, "12:00", "Resurrect", Option="rebuy", Cost=750_000, Bankrupt=False),
]


class TestLedger(unittest.TestCase):
    def test_income_costs_and_investment_apart(self):
        r = ledger.build_ledger(TRIP, now=1e10)
        T = r["totals"]
        inc = rows(T["income_rows"])
        self.assertEqual(inc["exobiology"], 7_000_000)               # value + first-footfall bonus
        self.assertEqual(inc["exploration"], 300_000)
        self.assertEqual(inc["trade"], 100_000)                       # the profit over the price paid
        self.assertEqual(inc["mining"], 5_000_000)                    # AvgPricePaid 0: mined
        self.assertEqual(inc["community_goals"], 10_000_000)
        costs = rows(T["cost_rows"])
        costs.pop("from_balance")                                     # see the balance test
        self.assertEqual(costs, {"fuel": 500, "repairs": 1_500, "ship_loss": 750_000})
        self.assertEqual(rows(T["invest_rows"]), {"ships": 15_000_000, "modules": 1_000_000})
        self.assertEqual(T["net"], T["income"] - T["costs"])
        self.assertEqual(r["carrier"], {"deposit": 1_000_000, "withdraw": 0})   # a transfer, no gain or loss
        self.assertEqual(r["deaths"][0]["cost"], 750_000)
        self.assertEqual(r["deaths"][0]["type"], "mandalay")

    def test_per_ship_and_the_commander(self):
        r = ledger.build_ledger(TRIP, now=1e10)
        by = {s["id"]: s for s in r["ships"]}
        self.assertEqual(by[1]["income"], 7_300_000)                  # bio and data sold in the explorer
        self.assertEqual(by[1]["costs"], 2_000)
        self.assertEqual((by[2]["invest"], by[2]["costs"]), (16_000_000, 750_000))
        self.assertTrue(by[2]["current"])
        self.assertEqual(r["cmdr"]["income"], 10_000_000 + r["rest"]["plus"])   # the CG and the balance rest

    def test_the_balance_shows_what_was_not_booked(self):
        # 1 M at login; booked: -500 +7 M +0.3 M -1500 -15 M -1 M -0.4 M +0.5 M +5 M +10 M -1 M transfer
        booked = -500 + 7_000_000 + 300_000 - 1_500 - 15_000_000 - 1_000_000 - 400_000 + 500_000 + 5_000_000 \
            + 10_000_000 - 1_000_000
        r = ledger.build_ledger(TRIP, now=1e10)
        # the transfer says the commander kept 0: a mission reward or the like is missing
        self.assertEqual(r["rest"]["minus"], 1_000_000 + booked)
        self.assertEqual(r["rest"]["gaps"], 1)
        missions = TRIP[:-2] + [ev(10, "11:25", "MissionCompleted", Reward=-(1_000_000 + booked))] + TRIP[-2:]
        self.assertEqual(ledger.build_ledger(missions, now=1e10)["rest"]["gaps"], 0)

    def test_period(self):
        late = TRIP + [ev(20, "08:00", "RepairAll", Cost=99)]
        now = 1795161600 + 3600                                      # 2026-11-20 09:00 UTC
        r = ledger.build_ledger(late, days=1, now=now)
        self.assertEqual(rows(r["totals"]["cost_rows"]), {"repairs": 99})
        self.assertFalse(r["totals"]["income_rows"])

    def test_the_archive_keeps_every_money_event(self):
        self.assertEqual([e for e in ledger.EVENTS if e not in fleet.EVENTS], [])

    def test_the_archive_keeps_the_login_balance(self):
        """AU1 (18.11.): the archive slimmed LoadGame to its time, so the
        ledger never saw the balance or the ship at login - the balance
        check only had the carrier transfers. Through the archive the books
        must come out as from the raw journal."""
        out, fid = [], None
        for e in TRIP:
            fid = fleet.Archive._take(e, fid, out)
        lg = next(e for e in out if e["event"] == "LoadGame")
        self.assertEqual((lg["Credits"], lg["ShipID"], lg["ShipName"]), (1_000_000, 1, "SCOUT"))
        raw, archived = ledger.build_ledger(TRIP), ledger.build_ledger(out)
        self.assertEqual(archived["totals"], raw["totals"])
        self.assertEqual(archived["rest"], raw["rest"])
        self.assertEqual([s["id"] for s in archived["ships"]], [s["id"] for s in raw["ships"]])


if __name__ == "__main__":
    unittest.main()
