# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M7: docked at someone else's fleet carrier - its market as a hint."""

import json
import os
import tempfile
import unittest

from fis.shipview import visiting_carrier


class Ar:
    def __init__(self, events):
        self._ev = events

    def events(self):
        return self._ev


def _market(market_id, items, station_type="FleetCarrier"):
    return {"timestamp": "2026-11-10T20:15:00Z", "event": "Market", "MarketID": market_id,
            "StationName": "K7Q-12Z", "StationType": station_type, "CarrierDockingAccess": "all",
            "StarSystem": "Test System", "Items": items}


TRIT = {"Name": "$tritium_name;", "Name_Localised": "Tritium", "SellPrice": 52000, "BuyPrice": 0,
        "Demand": 1200, "Stock": 0}
GOLD = {"Name": "$gold_name;", "Name_Localised": "Gold", "SellPrice": 0, "BuyPrice": 48000,
        "Demand": 0, "Stock": 30}
BAUX = {"Name": "$bauxite_name;", "Name_Localised": "Bauxite", "SellPrice": 4000, "BuyPrice": 0,
        "Demand": 5000, "Stock": 0}


class TestVisiting(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.docked = {"status": {"flags": 1}}
        self.ar = Ar([{"event": "Docked", "MarketID": 555, "StationType": "FleetCarrier"}])

    def _write(self, name, obj):
        with open(os.path.join(self.d, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def test_buys_and_sells(self):
        self._write("Market.json", _market(555, [BAUX, TRIT, GOLD]))
        self._write("Cargo.json", {"Vessel": "Ship", "Inventory": [{"Name": "tritium", "Count": 20}]})
        v = visiting_carrier(self.ar, self.docked, self.d, own_id=999)
        self.assertEqual(v["callsign"], "K7Q-12Z")
        # what you carry first, then tritium, then by demand
        self.assertEqual([b["key"] for b in v["buys"]], ["tritium", "bauxite"])
        self.assertEqual((v["buys"][0]["carry"], v["buys"][0]["price"]), (20, 52000))
        self.assertEqual([(s["key"], s["stock"]) for s in v["sells"]], [("gold", 30)])

    def test_only_when_it_applies(self):
        self._write("Market.json", _market(555, [TRIT]))
        self.assertIsNone(visiting_carrier(self.ar, {"status": {"flags": 0}}, self.d))      # not docked
        self.assertIsNone(visiting_carrier(self.ar, self.docked, self.d, own_id=555))       # own carrier
        self.assertIsNone(visiting_carrier(Ar([{"event": "Docked", "MarketID": 777}]),
                                           self.docked, self.d))                            # old market file
        self._write("Market.json", _market(555, [TRIT], station_type="Coriolis"))
        self.assertIsNone(visiting_carrier(self.ar, self.docked, self.d))                   # a station
        self.assertIsNone(visiting_carrier(self.ar, self.docked, None))


if __name__ == "__main__":
    unittest.main()
