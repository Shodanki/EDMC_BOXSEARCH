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


if __name__ == "__main__":
    unittest.main()
