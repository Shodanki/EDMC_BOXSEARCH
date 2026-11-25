# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""RB1 (5.1.0): the overlay warns when the credits would not pay the rebuy -
only in the ship away from a pad, only when switched on (off by default)."""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import rebuywarn as rb  # noqa: E402

IN_SHIP, DOCKED, LANDED = rb.IN_SHIP, rb.DOCKED, rb.LANDED


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def main():
    assert rb.short_by(10_000_000, 12_300_000) == 2_300_000
    assert rb.short_by(20_000_000, 12_300_000) is None
    assert rb.short_by(None, 12_300_000) is None and rb.short_by(5, None) is None
    assert rb.short_by(0, 0) is None
    line = rb.overlay_lines(IN_SHIP, 10_000_000, 12_300_000)
    assert line == [("REBUY 12.3 M CR - CREDITS 10.0 M - 2.3 M SHORT", rb.AMBER)], line
    assert rb.overlay_lines(IN_SHIP | DOCKED, 1, 12_300_000) == [], "docked: no line"
    assert rb.overlay_lines(IN_SHIP | LANDED, 1, 12_300_000) == [], "landed: no line"
    assert rb.overlay_lines(0, 1, 12_300_000) == [], "on foot / SRV: no line"
    assert rb.overlay_lines(IN_SHIP, 20_000_000, 12_300_000) == []
    w = rb.RebuyWatch()
    w.feed("LoadGame", {"Credits": 9_000_000})
    w.feed("Loadout", {"Rebuy": 12_300_000})
    assert w.lines({"Flags": IN_SHIP})[0][0].startswith("REBUY 12.3 M CR - CREDITS 9.0 M")
    assert w.lines({"Flags": IN_SHIP, "Balance": 50_000_000}) == [], "Status Balance is live"
    assert w.credits == 50_000_000
    # wiring: fed on every event, shown last, switch off by default
    j = read("journal.py")
    assert "_REBUY.feed(ev, entry)" in j
    assert 'if not lines and ov.enabled and cfg_bool(CFG["overlay_rebuy"], False):' in j
    assert 'r.check("overlay_rebuy", "overlay_rebuy", False,' in read("prefs.py")
    assert '"overlay_rebuy": "%s_overlay_rebuy" % PLUGIN_NAME' in read("state.py")
    print("rebuy warning: ok")


if __name__ == "__main__":
    main()
