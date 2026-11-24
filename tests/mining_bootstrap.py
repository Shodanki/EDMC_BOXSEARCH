# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.1.0 (user 24.11., MO1): EDMC started while the game ran - the mining
overlay takes the hold capacity from the newest journal's Loadout and the
cargo from Cargo.json, so HOLD shows the free room again.

    python tests/mining_bootstrap.py      (from the plugin folder)
"""
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ("config", "theme", "myNotebook", "monitor", "l10n", "companion", "plug",
          "EDMCLogging", "ttkHyperlinkLabel"):
    sys.modules[m] = mock.MagicMock()
try:
    import tkinter  # noqa: F401
except ImportError:
    for m in ("tkinter", "tkinter.filedialog", "tkinter.ttk"):
        sys.modules[m] = mock.MagicMock()

import plugin_pkg  # noqa: E402
plugin_pkg.import_plugin()
from SHBOXSEARCH import maintenance, miningstat, survey  # noqa: E402
from SHBOXSEARCH.state import ST  # noqa: E402

LOADOUT = {"timestamp": "2026-11-24T20:40:00Z", "event": "Loadout", "Ship": "lakonminer", "ShipID": 52,
           "CargoCapacity": 322, "Modules": [{"Slot": "MediumHardpoint1", "Item": "hpt_mininglaser_fixed_medium"}]}


def main():
    fails = 0
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "Journal.2026-11-24T203634.01.log"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": "2026-11-24T20:36:34Z", "event": "Fileheader"}) + "\n")
            fh.write(json.dumps(dict(LOADOUT, CargoCapacity=64, timestamp="2026-11-24T20:38:00Z")) + "\n")   # older
            fh.write(json.dumps(LOADOUT) + "\n")
        with open(os.path.join(d, "Cargo.json"), "w", encoding="utf-8") as fh:
            json.dump({"Vessel": "Ship", "Count": 160, "Inventory": [{"Name": "drones", "Count": 150},
                                                                     {"Name": "platinum", "Count": 10}]}, fh)
        ST.mine = miningstat.MiningTracker()
        with mock.patch.object(maintenance, "_journal_dir", return_value=d):
            survey._bootstrap_mining()
            got = (ST.mine.capacity, ST.mine.miner, ST.mine.cargo)
            ok = got == (322, True, {"drones": 150, "platinum": 10})
            print("  [%s] capacity, mining ship and cargo from the journal: %r" % ("OK" if ok else "FAIL", got))
            fails += 0 if ok else 1
            ST.mine.status({"Flags": 1 << 24})            # flying, not docked
            lines = ST.mine.flight_lines()
            ok = bool(lines) and "162 t free" in lines[0][0]
            print("  [%s] HOLD shows the free room: %r" % ("OK" if ok else "FAIL", lines))
            fails += 0 if ok else 1
            ST.mine.capacity, ST.mine.cargo = 500, {"drones": 1}       # something fresher arrived meanwhile
            survey._bootstrap_mining()
            ok = (ST.mine.capacity, ST.mine.cargo) == (500, {"drones": 1})
            print("  [%s] a fresher Loadout / cargo is kept" % ("OK" if ok else "FAIL"))
            fails += 0 if ok else 1
    print("mining bootstrap: %s" % ("all OK" if not fails else "%d FAILED" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
