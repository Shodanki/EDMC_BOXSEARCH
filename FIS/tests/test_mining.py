"""MINING: sessions from the journal; tritium in carrier jumps."""

import unittest

from fis import fleet as fl, mining
from fis.live import parse_ts


def ev(ts, name, **kw):
    return dict({"timestamp": "2026-05-30T%s:00Z" % ts, "event": name}, **kw)


ROCK = {"Materials": [{"Name": "Tritium", "Proportion": 31.5}, {"Name": "Water", "Proportion": 8.0}],
        "Content": "$AsteroidMaterialContent_High;", "Remaining": 100.0}

EVENTS = [
    ev("05:00", "LaunchDrone", Type="Prospector"),            # an older session
    ev("05:01", "MiningRefined", Type="$water_name;", Type_Localised="Water"),
    ev("07:00", "LaunchDrone", Type="Prospector"),
    ev("07:01", "ProspectedAsteroid", **dict(ROCK, Materials=[{"Name": "Tritium", "Proportion": 12.0}],
                                              Content="$AsteroidMaterialContent_Low;")),
    ev("07:02", "LaunchDrone", Type="Prospector"),
    ev("07:03", "ProspectedAsteroid", **ROCK),
    ev("07:04", "LaunchDrone", Type="Collection"),
    ev("07:05", "MiningRefined", Type="$tritium_name;", Type_Localised="Tritium"),
    ev("07:06", "MiningRefined", Type="$tritium_name;", Type_Localised="Tritium"),
    ev("07:07", "MiningRefined", Type="$tritium_name;", Type_Localised="Tritium"),
    ev("07:30", "LaunchDrone", Type="Repair"),                # no mining
]


class MiningTest(unittest.TestCase):
    def test_last_session(self):
        now = parse_ts("2026-05-30T07:20:00Z")
        s = mining.session(EVENTS, now)
        self.assertEqual(s["start"], parse_ts("2026-05-30T07:00:00Z"))   # 05:01 is two hours earlier
        self.assertTrue(s["active"])
        self.assertEqual(s["tritium"], 3)
        self.assertEqual(s["main"], "tritium")
        self.assertEqual(s["drones"], {"prospector": 2, "collection": 1})
        self.assertEqual(s["asteroids"], 2)
        self.assertEqual(s["best"]["share"], 31.5)
        self.assertEqual(s["best"]["content"], "high")
        self.assertEqual(s["last"]["materials"][0]["key"], "tritium")
        self.assertEqual(s["per_hour"], 9.0)            # 3 t in 20 minutes

    def test_ended_and_none(self):
        s = mining.session(EVENTS, parse_ts("2026-05-30T12:00:00Z"))
        self.assertFalse(s["active"])
        self.assertIsNone(mining.session([ev("07:30", "LaunchDrone", Type="Repair")]))

    def test_type_key(self):
        self.assertEqual(mining.type_key("$tritium_name;"), "tritium")
        self.assertEqual(mining.type_key("LowTemperatureDiamond"), "lowtemperaturediamond")
        self.assertEqual(mining.content_level("$AsteroidMaterialContent_Medium;"), "medium")

    def test_carrier_trip(self):
        trip = fl.carrier_trip(1200, 5000, 1000)
        self.assertEqual(trip["jumps"], 3)
        self.assertTrue(trip["enough"])
        short = fl.carrier_trip(4000, 5000, 100)
        self.assertFalse(short["enough"])
        self.assertEqual(short["short"], short["need"] - 100)
        # the need is worked out for a carrier that carries it: starting with it, it is enough
        self.assertLessEqual(abs(fl.carrier_trip(4000, 5000, short["need"])["need"] - short["need"]), 1)


if __name__ == "__main__":
    unittest.main()
