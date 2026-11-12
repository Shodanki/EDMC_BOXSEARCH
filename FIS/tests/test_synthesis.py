# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""V1c: vehicle synthesis learnt from your own Synthesis events - shaped
after the Scarab recording of 12.11.2026 ("Fuel Basic", "Ammo Basic",
"Repair Standard", no "SRV" in the name)."""

import unittest

from fis import materials, synthesis


def ev(ts, name, **kw):
    return dict({"timestamp": "2026-11-12T%s:00Z" % ts, "event": name}, **kw)


def mats(**kw):
    return [{"Name": k, "Count": v} for k, v in kw.items()]


RAW = [{"Name": "sulphur", "Count": 20}, {"Name": "phosphorus", "Count": 9},
       {"Name": "nickel", "Count": 10}, {"Name": "manganese", "Count": 4},
       {"Name": "vanadium", "Count": 5}, {"Name": "molybdenum", "Count": 0},
       {"Name": "iron", "Count": 7}, {"Name": "carbon", "Count": 30},
       {"Name": "germanium", "Count": 30}]
MAN = [{"Name": "mechanicalequipment", "Name_Localised": "Mechanical Equipment", "Count": 2}]

EVENTS = [
    ev("17:00", "Materials", Raw=RAW, Manufactured=MAN, Encoded=[]),
    ev("17:30", "LaunchSRV", SRVType="testbuggy", SRVType_Localised="SRV Scarab", Loadout="starter"),
    ev("17:40", "Synthesis", Name="Fuel Basic", Materials=mats(sulphur=1, phosphorus=1)),
    ev("17:41", "Synthesis", Name="Ammo Basic", Materials=mats(sulphur=2, phosphorus=1)),
    ev("17:42", "Synthesis", Name="Repair Standard",
       Materials=mats(nickel=3, manganese=1, vanadium=2, molybdenum=1)),
    ev("17:50", "DockSRV", SRVType="testbuggy"),
    # a ship recipe - not the vehicle's
    ev("18:00", "Synthesis", Name="FSD Basic", Materials=mats(carbon=1, vanadium=1, germanium=1)),
    # the Rhino: anything made while it is out is learnt under its own name
    ev("18:10", "LaunchSRV", SRVType="mev_rhino", SRVType_Localised="SRV Rhino", Loadout="starter"),
    ev("18:11", "Synthesis", Name="Rig Test", Materials=mats(iron=3, nickel=2, mechanicalequipment=1)),
    ev("18:12", "Synthesis", Name="Fuel Basic", Materials=mats(sulphur=1, phosphorus=1)),
    ev("18:20", "DockSRV", SRVType="mev_rhino"),
]


class SynthesisTest(unittest.TestCase):
    def test_parse_name(self):
        self.assertEqual(synthesis.parse_name("Fuel Basic"), ("fuel", "basic"))
        self.assertEqual(synthesis.parse_name("repair  PREMIUM"), ("repair", "premium"))
        self.assertEqual(synthesis.parse_name("FSD Basic"), (None, None))
        self.assertEqual(synthesis.parse_name("AFM Refill Basic"), (None, None))
        self.assertEqual(synthesis.parse_name(None), (None, None))

    def test_learn(self):
        r = synthesis.learn(EVENTS)
        self.assertEqual(sorted(r), ["ammo basic", "fuel basic", "repair standard", "rig test"])
        self.assertEqual(r["fuel basic"]["made"], 2)
        self.assertEqual(r["fuel basic"]["vehicles"], ["SRV Scarab", "SRV Rhino"])
        self.assertEqual(r["repair standard"]["materials"],
                         [("nickel", 3), ("manganese", 1), ("vanadium", 2), ("molybdenum", 1)])
        self.assertIsNone(r["rig test"]["kind"])
        self.assertEqual(r["rig test"]["vehicles"], ["SRV Rhino"])

    def test_outside_a_vehicle_only_the_named_kinds(self):
        evs = [ev("10:00", "Synthesis", Name="Limpet Basic", Materials=mats(iron=10, nickel=10)),
               ev("10:01", "Synthesis", Name="Ammo Basic", Materials=mats(sulphur=2, phosphorus=1))]
        self.assertEqual(sorted(synthesis.learn(evs)), ["ammo basic"])

    def test_stock_counts_manufactured(self):
        st = materials.stock(EVENTS)
        # 20 - 1 - 2 - 1 (fuel twice, ammo once)
        self.assertEqual(st["have"]["sulphur"], 16)
        self.assertEqual(st["have"]["phosphorus"], 6)
        self.assertEqual(st["have"]["mechanicalequipment"], 1)
        self.assertEqual(st["have"]["iron"], 4)

    def test_plan(self):
        st = materials.stock(EVENTS)
        p = synthesis.plan(synthesis.learn(EVENTS), st["have"], synthesis.names(EVENTS))
        rows = {r["name"]: r for r in p["recipes"]}
        self.assertEqual([r["name"] for r in p["recipes"]],
                         ["Fuel Basic", "Ammo Basic", "Repair Standard", "Rig Test"])
        self.assertEqual(rows["Fuel Basic"]["can"], 6)            # phosphorus 6
        self.assertEqual(rows["Fuel Basic"]["limit"], "phosphorus")
        self.assertEqual(rows["Ammo Basic"]["can"], 6)            # sulphur 16 // 2 = 8, phosphorus 6
        self.assertEqual(rows["Repair Standard"]["can"], 0)       # no molybdenum left
        self.assertEqual(rows["Repair Standard"]["missing"], ["molybdenum"])
        self.assertEqual(rows["Rig Test"]["can"], 1)              # mechanical equipment 1
        me = [m for m in rows["Rig Test"]["materials"] if m["key"] == "mechanicalequipment"][0]
        self.assertEqual(me["name"], "Mechanical Equipment")
        self.assertEqual((me["need"], me["have"]), (1, 1))
        kinds = {k["kind"]: k for k in p["kinds"]}
        self.assertEqual(kinds["fuel"]["not_seen"], ["standard", "premium"])
        self.assertEqual(kinds["repair"]["seen"], ["standard"])
        self.assertEqual(kinds["repair"]["not_seen"], ["basic", "premium"])

    def test_nothing_learnt(self):
        p = synthesis.plan({}, {})
        self.assertEqual(p["recipes"], [])
        self.assertEqual([k["not_seen"] for k in p["kinds"]], [list(synthesis.TIERS)] * 3)

    def test_build_once_per_journal_change(self):
        class Ar:
            rev = 1
            calls = 0

            def refresh(self):
                pass

            def commander(self):
                return ("F1", "Test")

            def events(self):
                Ar.calls += 1
                return EVENTS

        a = Ar()
        one = synthesis.build_synthesis(a)
        two = synthesis.build_synthesis(a)
        self.assertIs(one, two)
        self.assertEqual(Ar.calls, 1)
        self.assertEqual(one["base_ts"], "2026-11-12T17:00:00Z")
        Ar.rev = 2
        synthesis.build_synthesis(a)
        self.assertEqual(Ar.calls, 2)


if __name__ == "__main__":
    unittest.main()
