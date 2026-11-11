# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""K1: other commanders' carriers known from the journal (invented names)."""

import json
import os
import tempfile
import unittest

from fis import carriers as ca
from fis import fleet as fl


def _e(ts, ev, **kw):
    return dict({"timestamp": "2026-11-%sZ" % ts, "event": ev}, **kw)


JUMP_A = _e("01T10:00:00", "FSDJump", StarSystem="Test Alpha", SystemAddress=1, StarPos=[0, 0, 0])
EVS = [
    _e("01T09:59:00", "CarrierStats", CarrierID=900, CarrierType="FleetCarrier",
       Callsign="OWN-001", Name="MY OWN"),
    JUMP_A,
    _e("01T10:00:05", "FSSSignalDiscovered", SystemAddress=1, SignalType="FleetCarrier",
       SignalName="BLUE HERON Q2W-3ER", IsStation=True),
    _e("01T10:00:06", "FSSSignalDiscovered", SystemAddress=1, SignalType="FleetCarrier",
       SignalName="MY OWN OWN-001", IsStation=True),
    _e("01T10:00:07", "FSSSignalDiscovered", SystemAddress=1, SignalType="SquadronCarrier",
       SignalName="WING HOME | ABCD", IsStation=True),
    _e("01T10:05:00", "Docked", StationName="Q2W-3ER", StationType="FleetCarrier",
       MarketID=4711, StarSystem="Test Alpha", SystemAddress=1),
    _e("01T10:06:00", "MissionAccepted", Name="Mission_Delivery", LocalisedName="Deliver 40 units of Gold",
       Commodity="$Gold_Name;", Commodity_Localised="Gold", Count=40, DestinationSystem="Test Beta"),
    _e("01T10:07:00", "CommunityGoalJoin", CGID=7, Name="Build a test", System="Test Gamma"),
    _e("01T10:30:00", "CarrierJump", Docked=False, OnFoot=True, StarSystem="Test Beta",
       SystemAddress=2, StarPos=[10, 0, 0]),
    _e("01T10:40:00", "Undocked", StationName="Q2W-3ER"),
    # a mission from a station later is not from the carrier
    _e("01T10:50:00", "Docked", StationName="Some Port", StationType="Coriolis", MarketID=12,
       StarSystem="Test Beta", SystemAddress=2),
    _e("01T10:51:00", "MissionAccepted", Name="Mission_Courier", LocalisedName="Courier"),
    # docked at the own carrier: not a "known carrier"
    _e("01T11:00:00", "Docked", StationName="OWN-001", StationType="FleetCarrier", MarketID=900,
       StarSystem="Test Beta", SystemAddress=2),
]


class TestKnown(unittest.TestCase):
    def test_parse_signal(self):
        self.assertEqual(ca.parse_signal("BLUE HERON Q2W-3ER"), {"name": "BLUE HERON", "callsign": "Q2W-3ER"})
        self.assertEqual(ca.parse_signal("Q2W-3ER"), {"name": "", "callsign": "Q2W-3ER"})
        self.assertIsNone(ca.parse_signal("WING HOME | ABCD"))
        self.assertIsNone(ca.parse_signal(None))

    def test_known(self):
        k = ca.known_carriers(EVS)
        self.assertEqual(sorted(k), ["Q2W-3ER"])                # own and squadron left out
        c = k["Q2W-3ER"]
        self.assertEqual((c["name"], c["market_id"], c["docked_n"], c["sightings"]), ("BLUE HERON", 4711, 1, 1))
        # rode along: the jump is the last known position
        self.assertEqual((c["system"], c["id64"], c["pos"], c["how"]), ("Test Beta", 2, [10, 0, 0], "jump"))
        self.assertEqual([(s["kind"], s["name"]) for s in c["started"]],
                         [("mission", "Deliver 40 units of Gold"), ("cg", "Build a test")])
        self.assertEqual((c["started"][0]["commodity"], c["started"][0]["count"]), ("Gold", 40))

    def test_sighting_resolves_system_name(self):
        k = ca.known_carriers(EVS[:3])
        self.assertEqual((k["Q2W-3ER"]["system"], k["Q2W-3ER"]["pos"], k["Q2W-3ER"]["how"]),
                         ("Test Alpha", [0, 0, 0], "sighted"))

    def test_login_on_the_pad(self):
        evs = [_e("02T08:00:00", "Location", Docked=True, StationName="Z9Z-9ZZ", StationType="FleetCarrier",
                  MarketID=55, StarSystem="Test Delta", SystemAddress=4, StarPos=[1, 1, 1])]
        c = ca.known_carriers(evs)["Z9Z-9ZZ"]
        self.assertEqual((c["system"], c["how"], c["docked_n"], c["last_docked"]),
                         ("Test Delta", "docked", 0, "2026-11-02T08:00:00Z"))

    def test_foreign_jump_flags(self):
        flags = ca.own_jump_flags(EVS + [
            _e("01T12:00:00", "CarrierJump", StarSystem="Test Gamma", SystemAddress=3, StarPos=[5, 5, 5])])
        jumps = [f for e, f in zip(EVS + [{"event": "CarrierJump"}], flags) if e["event"] == "CarrierJump"]
        self.assertEqual(jumps, [True, False])                   # stranger's, then own

    def test_through_the_real_archive(self):
        d = tempfile.mkdtemp()
        lines = [_e("01T09:00:00", "Commander", FID="F7", Name="Tester")] + EVS
        with open(os.path.join(d, "Journal.2026-11-01T090000.01.log"), "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(x) + "\n" for x in lines))
        k = ca.known_carriers(fl.Archive(d).events())
        self.assertEqual(len(k["Q2W-3ER"]["started"]), 2)
        self.assertEqual(k["Q2W-3ER"]["how"], "jump")

    def test_favourite_pois(self):
        poi = [{"kind": "station", "name": "Test Port"},
               {"kind": "carrier", "name": "NEW ONE A1B-2C3"},
               {"kind": "carrier", "name": "BLUE HERON Q2W-3ER"},
               {"kind": "carrier", "name": "Z9Z-9ZZ"},
               {"kind": "beacon", "name": "Nav Beacon"}]
        out = ca.mark_favourite_pois(poi, {"Q2W-3ER": {}, "Z9Z-9ZZ": {}})
        self.assertEqual([p["name"] for p in out],
                         ["Test Port", "BLUE HERON Q2W-3ER", "Z9Z-9ZZ", "NEW ONE A1B-2C3", "Nav Beacon"])
        self.assertEqual([bool(p.get("favourite")) for p in out], [False, True, True, False, False])
        self.assertNotIn("favourite", poi[2])                     # the cached list is untouched
        self.assertIs(ca.mark_favourite_pois(poi, {}), poi)


class TestCarriersHere(unittest.TestCase):
    """B1: own and favourite carriers known in the current system."""
    NOW = 1794404800.0           # 2026-11-11 13:46:40 UTC

    def test_own_and_favourites(self):
        own = {"system": "Test Beta", "id": 2, "since": self.NOW - 7200, "expected": False,
               "name": "MY OWN", "callsign": "OWN-001"}
        favs = [
            # journal: docked here 3 h ago
            {"callsign": "Q2W-3ER", "name": "BLUE HERON", "system": "Test Beta", "id64": 2,
             "ts": "2026-11-11T10:46:40Z", "how": "docked", "note": "trade"},
            # journal says here, but a NEWER Spansh answer puts it elsewhere -> not listed
            {"callsign": "A1B-2C3", "system": "Test Beta", "id64": 2, "ts": "2026-11-01T10:00:00Z",
             "how": "sighted", "online": {"found": True, "system": "Far Away", "id64": 9,
                                          "updated": "2026-11-10 08:00:00+00", "checked": "2026-11-11T12:00:00Z"}},
            # journal elsewhere, newer Spansh answer: here
            {"callsign": "Z9Z-9ZZ", "system": "Test Alpha", "id64": 1, "ts": "2026-11-01T10:00:00Z",
             "how": "sighted", "online": {"found": True, "system": "Test Beta", "id64": 2,
                                          "updated": "2026-11-11 12:46:40+00", "checked": "2026-11-11T13:00:00Z"}},
            # nothing known about its place
            {"callsign": "N0N-000"},
            # the own carrier as favourite is not listed twice
            {"callsign": "OWN-001", "system": "Test Beta", "id64": 2, "ts": "2026-11-11T13:00:00Z"},
        ]
        out = ca.carriers_here(2, "Test Beta", own, favs, now=self.NOW)
        self.assertEqual([c["callsign"] for c in out], ["OWN-001", "Q2W-3ER", "Z9Z-9ZZ"])
        self.assertEqual((out[0]["kind"], out[0]["source"], out[0]["age_s"]), ("own", "journal", 7200))
        self.assertEqual((out[1]["source"], out[1]["how"], out[1]["age_s"], out[1]["note"]),
                         ("journal", "docked", 3 * 3600, "trade"))
        self.assertEqual((out[2]["source"], out[2]["how"], out[2]["age_s"]), ("Spansh", "spansh", 3600))
        self.assertEqual(out[2]["checked"], "2026-11-11T13:00:00Z")

    def test_elsewhere_and_by_name(self):
        own = {"system": "Test Alpha", "id": 1, "since": self.NOW - 60, "expected": True}
        self.assertEqual(ca.carriers_here(2, "Test Beta", own, []), [])
        fav = [{"callsign": "Q2W-3ER", "system": "test beta", "ts": "2026-11-11T10:00:00Z",
                "how": "sighted", "from_store": True}]
        out = ca.carriers_here(None, "Test Beta", None, fav, now=self.NOW)
        self.assertEqual((out[0]["callsign"], out[0]["source"]), ("Q2W-3ER", "stored"))
        self.assertEqual(ca.carriers_here(None, None, own, fav), [])


class TestDockingAccess(unittest.TestCase):
    """A1: may we dock - local sources only, the newest decides."""

    def test_sources_and_states(self):
        evs = [
            _e("02T10:00:00", "Market", MarketID=1, StationName="AAA-111", StationType="FleetCarrier",
               CarrierDockingAccess="all", StarSystem="S"),
            _e("02T10:00:00", "Market", MarketID=2, StationName="BBB-222", StationType="FleetCarrier",
               CarrierDockingAccess="squadronfriends", StarSystem="S"),
            _e("02T10:00:00", "Market", MarketID=3, StationName="CCC-333", StationType="FleetCarrier",
               CarrierDockingAccess="friends", StarSystem="S"),
            _e("01T09:00:00", "DockingGranted", MarketID=3, StationName="CCC-333",
               StationType="FleetCarrier", LandingPad=5),
            _e("02T11:00:00", "DockingDenied", MarketID=4, StationName="DDD-444",
               StationType="FleetCarrier", Reason="RestrictedAccess"),
            _e("02T11:00:00", "DockingDenied", MarketID=5, StationName="EEE-555",
               StationType="FleetCarrier", Reason="NoSpace"),
            _e("02T11:00:00", "DockingGranted", MarketID=6, StationName="Some Port",
               StationType="Coriolis", LandingPad=5),
            # all at first, then the owner closed it
            _e("01T08:00:00", "Market", MarketID=7, StationName="GGG-777", StationType="FleetCarrier",
               CarrierDockingAccess="all"),
        ]
        markets = {"GGG-777": {"ts": "2026-11-03T08:00:00Z", "access": "none"},
                   "HHH-888": {"ts": "2026-11-03T08:00:00Z"}}
        favs = {"FFF-666": {"online": {"found": True, "docking_access": "all",
                                       "updated": "2026-11-04 10:00:00+00"}},
                "III-999": {"online": {"found": True, "docking_access": "", "updated": "2026-11-04 10:00:00+00"}}}
        acc = ca.docking_access(evs, markets, favs)
        st = {cs: a["state"] for cs, a in acc.items()}
        self.assertEqual(st, {"AAA-111": "dock", "BBB-222": "maybe", "CCC-333": "dock",
                              "DDD-444": "none", "FFF-666": "dock", "GGG-777": "none"})
        self.assertEqual((acc["CCC-333"]["access"], acc["CCC-333"]["granted"]), ("friends", True))
        self.assertEqual((acc["FFF-666"]["source"], acc["FFF-666"]["ts"]), ("Spansh", "2026-11-04T10:00:00Z"))
        self.assertEqual(acc["AAA-111"]["source"], "market")

    def test_mark_pois(self):
        poi = [{"kind": "station", "name": "Port"},
               {"kind": "carrier", "name": "OPEN ONE AAA-111"},
               {"kind": "carrier", "name": "DDD-444"},
               {"kind": "carrier", "name": "UNKNOWN ZZZ-000"}]
        acc = {"AAA-111": {"state": "dock", "access": "all", "source": "market", "ts": "x"},
               "DDD-444": {"state": "none", "access": None, "source": "journal", "ts": "y"}}
        out, hidden = ca.mark_docking_pois(poi, acc)
        self.assertEqual(hidden, 1)
        self.assertEqual([p["name"] for p in out], ["Port", "OPEN ONE AAA-111", "UNKNOWN ZZZ-000"])
        self.assertEqual((out[1]["access"], out[1]["access_word"]), ("dock", "all"))
        self.assertNotIn("access", out[2])
        self.assertNotIn("access", poi[1])                        # the cached list is untouched
        self.assertEqual(ca.mark_docking_pois(poi, {}), (poi, 0))

    def test_archive_keeps_the_events(self):
        d = tempfile.mkdtemp()
        lines = [_e("01T09:00:00", "Commander", FID="F7", Name="Tester"),
                 _e("02T10:00:00", "Market", MarketID=1, StationName="AAA-111",
                    StationType="FleetCarrier", CarrierDockingAccess="all"),
                 _e("02T10:01:00", "MarketSell", MarketID=1, Type="gold", Count=1)]
        with open(os.path.join(d, "Journal.2026-11-02T090000.01.log"), "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(x) + chr(10) for x in lines))
        evs = fl.Archive(d).events()
        self.assertEqual([e["event"] for e in evs], ["Market", "MarketSell"])
        self.assertEqual(ca.docking_access(evs)["AAA-111"]["state"], "dock")


if __name__ == "__main__":
    unittest.main()
