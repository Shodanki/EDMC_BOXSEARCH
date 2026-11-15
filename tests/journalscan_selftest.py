# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of journalscan.py (moved from the module in 4.12, N7 - verbatim).

    python tests/journalscan_selftest.py      (from the plugin folder)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.journalscan import (WorkMeter, approached_bodies, journal_files, last_body,  # noqa: E402
                                     newest_location, replay_fuel, replay_work)


def _selftest() -> int:
    import tempfile
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    def t(s: int) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1_800_000_000 + s))

    ev1 = [
        {"event": "Commander", "Name": "Tester"},
        {"event": "Loadout", "ShipID": 3, "MaxJumpRange": 55.0, "FuelCapacity": {"Main": 32.0}},
        {"event": "FSDJump", "StarSystem": "Js A", "SystemAddress": 11, "StarPos": [1, 2, 3],
         "JumpDist": 40.0, "FuelUsed": 4.0, "FuelLevel": 28.0},
        {"event": "SupercruiseExit", "Body": "Js A 1", "BodyID": 1, "SystemAddress": 11},
        {"event": "SAAScanComplete", "BodyName": "Js A 1", "BodyID": 1, "SystemAddress": 11},
        {"event": "SupercruiseEntry", "SystemAddress": 11},
        {"event": "SupercruiseExit", "Body": "Js A 2", "BodyID": 2, "SystemAddress": 11},
        {"event": "SAAScanComplete", "BodyName": "Js A 3", "BodyID": 3, "SystemAddress": 11},
    ]
    times1 = [0, 1, 10, 100, 190, 300, 360, 600]
    ev2 = [
        {"event": "ScanOrganic", "ScanType": "Log", "SystemAddress": 11, "Body": 2, "Species": "S"},
        {"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 11, "Body": 2, "Species": "S"},
        {"event": "Location", "StarSystem": "Js B", "SystemAddress": 12, "StarPos": [4, 5, 6]},
        {"event": "Touchdown", "Body": "Js B 4", "BodyID": 4, "SystemAddress": 12},
    ]
    times2 = [700, 1100, 1200, 1300]
    with tempfile.TemporaryDirectory() as d:
        for fn, evs, ts in (("Journal.2026-11-13T010000.01.log", ev1, times1),
                            ("Journal.2026-11-13T020000.01.log", ev2, times2)):
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                for e, s in zip(evs, ts):
                    f.write(json.dumps(dict(e, timestamp=t(s))) + "\n")
                f.write("not json\n")
        files = journal_files(d)
        check(len(files) == 2 and files[0].endswith("010000.01.log"), "journal files oldest first")
        check(newest_location(d) == ("Js B", 12, (4, 5, 6)), "newest location: the later Location")
        lb = last_body(d)
        check(lb == {"body_id": 4, "name": "Js B 4", "sys": 12}, "last body: the Touchdown")
        m = replay_work(files)
        check(m.dss == [90.0, 410.0], "DSS: arrival bracket 90 s, then gap since last mapping 410 s")
        check(m.bio == [400.0], "sampling: Log -> Analyse 400 s")
        check(m.sc_legs == [(11, "Js A 1", "Js A 2", 1_800_000_300.0, 60.0)],
              "one body-to-body supercruise leg")

        class Fuel:
            def __init__(self):
                self.ship, self.jumps, self.level = None, [], None
                self.max_jump = self.capacity = None

            def set_ship(self, s):
                self.ship = s

            def add_jump(self, dist, used):
                self.jumps.append((dist, used))

        fu = replay_fuel(files, Fuel())
        check(fu.ship == ("Tester", 3) and fu.capacity == 32.0 and fu.max_jump == 55.0
              and fu.jumps == [(40.0, 4.0)] and fu.level == 28.0, "fuel replay")
        check(approached_bodies(d, 11) == [("Js A 1", 1_800_000_100.0),
                                           ("Js A 2", 1_800_000_360.0),
                                           ("Js A 3", 1_800_000_600.0)]
              and approached_bodies(d, 99) == [], "bodies approached in one system, in order")
        check(newest_location(os.path.join(d, "none")) is None and journal_files(None) == [],
              "no folder -> nothing")
    live = WorkMeter()
    check(live.feed({"event": "ApproachBody", "Body": "X 1", "SystemAddress": 5}, 0.0) is None
          and live.feed({"event": "SAAScanComplete", "BodyName": "X 1", "SystemAddress": 5}, 5.0)
          is None, "under 10 s is no measurement")
    print("journalscan self test: %s" % ("all OK" if not fails else "%d FAILED" % fails))
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
