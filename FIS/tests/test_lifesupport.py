# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""R8: the LIFE SUPPORT lamp in the SHIP panel, DANGER's tooltip and the
hazard log line - the game writes no event when life support is off."""
import json
import os
import sys
import tempfile
import unittest

from fis import fleet as fl, hazards, shipview
from fis.live import parse_ts
from tests.fixtures import PLUGIN_DIR

IN_SHIP, LANDED, DANGER, OVERHEAT = 1 << 24, 1 << 1, 1 << 22, 1 << 20
LO = {"timestamp": "2026-11-18T20:07:37Z",
      "Modules": [{"Slot": "LifeSupport", "Item": "int_lifesupport_size5_class2", "On": True, "Health": 1.0}]}


def _panel():
    return [{"key": k, "level": lv, "on": k == "danger"} for k, lv in shipview.PANEL]


class LifeSupportPanelTest(unittest.TestCase):
    def setUp(self):
        if PLUGIN_DIR not in sys.path:          # as Config.use_plugin_path does
            sys.path.append(PLUGIN_DIR)

    def _run(self, flags, alerts, lo=LO, info=None):
        p = _panel()
        shipview._life_support(p, flags, lo, info or {}, alerts, parse_ts("2026-11-18T20:11:00Z"))
        return {x["key"]: x for x in p}

    def test_afmu_session_with_danger(self):
        alerts = [{"event": "ModuleInfo", "ts": parse_ts("2026-11-18T20:08:42Z")},
                  {"event": "AfmuRepairs", "ts": parse_ts("2026-11-18T20:10:30Z"),
                   "module_key": "$int_lifesupport_size5_class2_name;"}]
        p = self._run(IN_SHIP | LANDED | DANGER, alerts)
        self.assertTrue(p["life_support"]["on"] and p["life_support"]["probable"])
        self.assertEqual(p["danger"]["why"], "life_support")
        self.assertEqual(shipview.PANEL[1], ("life_support", "warning"))

    def test_no_repair_no_guess(self):
        p = self._run(IN_SHIP | DANGER | OVERHEAT, [])
        self.assertFalse(p["life_support"]["on"])
        self.assertEqual(p["danger"]["why"], "overheat")

    def test_loadout_off_is_sure(self):
        lo = dict(LO, Modules=[dict(LO["Modules"][0], On=False)])
        p = self._run(IN_SHIP, [], lo)
        self.assertTrue(p["life_support"]["on"])
        self.assertFalse(p["life_support"]["probable"])

    def test_repairs_before_the_loadout_do_not_count(self):
        old = [{"event": "ModuleInfo", "ts": parse_ts("2026-11-18T20:00:00Z")}]
        self.assertFalse(self._run(IN_SHIP | DANGER, old)["life_support"]["on"])


class LifeSupportHazardTest(unittest.TestCase):
    def test_afmu_repair_of_life_support_is_logged(self):
        def ev(hms, name, **kw):
            return dict({"timestamp": "2026-11-18T%sZ" % hms, "event": name}, **kw)
        lines = [ev("20:00:00", "Commander", FID="F1", Name="X"), ev("20:00:00", "LoadGame", Commander="X"),
                 ev("20:01:00", "Location", StarSystem="Alpha"),
                 ev("20:09:15", "AfmuRepairs", Module="$int_engine_size7_class5_name;", Health=1.0),
                 ev("20:10:30", "AfmuRepairs", Module="$int_lifesupport_size5_class2_name;", Health=1.0)]
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Journal.2026-11-18T200000.01.log"), "w", encoding="utf-8") as fh:
                for e in lines:
                    fh.write(json.dumps(e) + "\n")
            h = hazards.build_hazards(fl.Archive(d), now=parse_ts("2026-11-18T21:00:00Z"))
        self.assertEqual([i["kind"] for i in h["items"]], ["LifeSupportOff"])
        self.assertEqual((h["items"][0]["level"], h["items"][0]["system"]), ("danger", "Alpha"))


if __name__ == "__main__":
    unittest.main()
