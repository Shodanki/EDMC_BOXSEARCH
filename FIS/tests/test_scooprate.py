# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""B-15: fuel scoop rate per star class from FuelScoop events about every 5 t."""
import unittest

from fis import realitycheck, scooprate


def ev(sec, name, **kw):
    return dict({"timestamp": "2026-11-18T19:%02d:%02dZ" % (sec // 60, sec % 60), "event": name}, **kw)


def visit(t0, cls, gaps):
    out = [ev(t0, "StartJump", JumpType="Hyperspace", StarClass=cls), ev(t0 + 5, "FSDJump", StarSystem="X")]
    t = t0 + 20
    out.append(ev(t, "FuelScoop", Scooped=5.0, Total=10.0))      # the first one only starts the clock
    for g in gaps:
        t += g
        out.append(ev(t, "FuelScoop", Scooped=5.0, Total=10.0))
    return out


class ScoopRateTest(unittest.TestCase):
    def test_rates_per_class(self):
        evs = visit(0, "K", [10, 10, 10, 10, 10, 10]) + visit(200, "M", [20, 20]) + \
            [ev(400, "StartJump", JumpType="Supercruise"), ev(401, "SupercruiseEntry")]
        smp = scooprate.samples(evs)
        r = {x["cls"]: x for x in scooprate.rates(smp)}
        self.assertEqual((r["K"]["t_s"], r["K"]["n"], r["K"]["thin"]), (0.5, 6, False))
        self.assertEqual((r["M"]["t_s"], r["M"]["n"], r["M"]["thin"]), (0.25, 2, True))

    def test_gap_and_carrier_do_not_count(self):
        evs = visit(0, "K", [10, 60, 10]) + [ev(200, "CarrierJump", StarSystem="Y"),
                                             ev(210, "FuelScoop", Scooped=5.0), ev(220, "FuelScoop", Scooped=5.0)]
        smp = scooprate.samples(evs)
        self.assertEqual([round(s["t_s"], 2) for s in smp], [0.5, 0.5])   # 60 s gap: clock restarts

    def test_reality_judges_by_the_ones_before(self):
        evs = visit(0, "K", [10] * 5 + [20])
        rc = scooprate.reality(scooprate.samples(evs))
        self.assertEqual(rc["n"], 1)
        self.assertEqual(rc["median_pct"], 100.0)               # 0.25 t/s where 0.5 was learnt
        row = {r["key"]: r for r in realitycheck.build({"scoop": rc})}["scoop"]
        self.assertIsNone(row["good"])                         # n 1: thin, not wrong
        self.assertIsNone(scooprate.reality([]))


if __name__ == "__main__":
    unittest.main()
