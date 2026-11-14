# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of miningstat.py (moved from the module in 4.12, N7 - verbatim).

    python tests/miningstat_selftest.py      (from the plugin folder)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.miningstat import (MiningTracker, _ts)  # noqa: E402


def _selftest() -> int:
    """python miningstat.py - checks the lines with a short session."""
    m = MiningTracker()
    m.feed({"event": "Loadout", "CargoCapacity": 322})
    t0 = "2026-11-06T10:00:%02dZ"
    m.feed({"timestamp": t0 % 0, "event": "LaunchDrone", "Type": "Prospector"})
    m.feed({"timestamp": t0 % 5, "event": "ProspectedAsteroid", "Content": "$AsteroidMaterialContent_High;",
            "Materials": [{"Name": "Tritium", "Proportion": 31.5}, {"Name": "Water", "Proportion": 8}],
            "Remaining": 100})
    for i in range(10, 40, 3):
        m.feed({"timestamp": t0 % i, "event": "MiningRefined", "Type": "$tritium_name;", "Type_Localised": "Tritium"},
               cargo={"tritium": (i - 10) // 3 + 1, "drones": 120})
    m.status({"Flags": 1, "Destination": {"Name": "$SAA_RingHotspot:#type=$Tritium_name;;",
                                          "Name_Localised": "Tritium Hotspot"}})
    now = _ts({"timestamp": t0 % 59})
    lines = m.lines(now)
    # in the ring: the session line becomes the hotspot line
    m.feed({"timestamp": t0 % 50, "event": "SupercruiseExit", "Body": "X 4 B Ring", "BodyType": "PlanetaryRing"})
    ring_lines = m.lines(now)
    targeted = m.target
    m.status({"Flags": 1})                    # target dropped
    lost = m.lines(now)
    was_active = m.active(now)
    m.feed({"timestamp": t0 % 58, "event": "Docked", "StationType": "FleetCarrier"})
    docked_active = m.active(now)
    # refining without a limpet (Rhino SRV, the refinery's last tonnes) starts nothing
    rhino = MiningTracker()
    rhino.feed({"timestamp": t0 % 1, "event": "MiningRefined", "Type": "$tantalum_name;"})
    rhino_idle = not rhino.active(now) and not rhino.refined
    # a collector limpet from a ship without mining tools (an explorer) starts nothing
    explorer = MiningTracker()
    explorer.feed({"event": "Loadout", "CargoCapacity": 128,
                   "Modules": [{"Item": "int_dronecontrol_collection_size1_class5"}]})
    explorer.feed({"timestamp": t0 % 1, "event": "LaunchDrone", "Type": "Collection"})
    explorer_idle = not explorer.active(now)
    # a collector limpet even from a mining ship starts nothing - only a prospector does
    collector = MiningTracker()
    collector.feed({"event": "Loadout", "CargoCapacity": 322, "Modules": [{"Item": "hpt_mininglaser_fixed_small"}]})
    collector.feed({"timestamp": t0 % 1, "event": "LaunchDrone", "Type": "Collection"})
    collector_idle = not collector.active(now)
    # a jump ends the session like docking
    jumper = MiningTracker()
    jumper.feed({"timestamp": t0 % 1, "event": "LaunchDrone", "Type": "Prospector"})
    jumper.feed({"timestamp": t0 % 2, "event": "FSDJump", "StarSystem": "X"})
    jump_ends = not jumper.active(now)
    # undocked again: the next limpet starts a new session from zero
    m.feed({"timestamp": "2026-11-06T10:05:00Z", "event": "LaunchDrone", "Type": "Prospector"})
    fresh = sum(m.refined.values()) == 0 and m.limpets_used == 1
    fails = 0
    checks = [
        (len(lines) == 5, "five lines"),
        (lines[0][0].startswith("ROCK  Tritium 31.5 %") and "GOOD" in lines[0][0], "rock line"),
        ("HOLD  10 t ore | 192 t free | 120 limpets" == lines[1][0], "hold line: " + lines[1][0]),
        (lines[2][0].startswith("RATE  60 t/h"), "rate line: " + lines[2][0]),
        (lines[3][0].startswith("SESSION  10 t Tritium"), "session line"),
        (targeted == "tritium", "target from hotspot"),
        (was_active, "active"),
        (not docked_active, "docking ends the session"),
        (fresh, "a new session after docking"),
        (rhino_idle, "refining without a limpet starts nothing"),
        (jump_ends, "a jump ends the session"),
        (explorer_idle, "no session out of a ship without mining tools"),
        (collector_idle, "a collector limpet alone starts no session"),
        (ring_lines[3][0].startswith("HOTSPOT  Tritium Hotspot targeted"), "hotspot line: " + ring_lines[3][0]),
        (lost[3][0].startswith("HOTSPOT  not targeted"), "hotspot lost: " + lost[3][0]),
        (len(lost) == 5, "still five lines"),
    ]
    for ok, what in checks:
        if not ok:
            fails += 1
            print("FAIL", what)
    print("miningstat selftest: %d failures" % fails)
    for ln in lines:
        print("  ", ln[0])
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
