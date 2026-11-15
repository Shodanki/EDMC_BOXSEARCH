# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of overlay.py (moved from the module in 4.12, N7 - verbatim).

    python tests/overlay_selftest.py      (from the plugin folder)
"""
from typing import List, Tuple
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.overlay import (COL, CockpitOverlay, briefing_lines)  # noqa: E402


def _selftest() -> int:
    """python overlay.py - the targets block stays on screen (fake client)."""
    sent: List[Tuple[str, str, int]] = []

    class Client:
        def send_message(self, mid, text, colour, x, y, ttl=4, size="normal"):
            sent.append((mid, text, ttl))

    ov = CockpitOverlay(client=Client())
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    ov._last_targets = [("NEXT TARGETS", COL["head"]), ("1. A 2  DSS", COL["data"])]
    t0 = 1000.0
    ov._targets_t = t0
    check(not ov.keep_targets(t0 + 60), "fresh block is left alone")
    check(ov.keep_targets(t0 + ov.TARGETS_REFRESH + 1) and sent[-1][2] == ov.TARGETS_TTL,
          "sent again before its time on screen runs out")
    n = len(sent)
    ov.hidden = True
    check(not ov.keep_targets(ov._targets_t + 9999) and len(sent) == n, "not over a map screen")
    ov.hidden, ov.mute_targets = False, True
    check(not ov.keep_targets(ov._targets_t + 9999), "not while mining")
    ov.mute_targets, ov._last_targets = False, []
    check(not ov.keep_targets(ov._targets_t + 9999), "nothing to keep")

    def texts(**kw):
        return [t for t, _c in briefing_lines(dict(name="X", kind="target", **kw))]
    nb = "IN NO DATABASE - first discovery likely"
    check(nb not in texts(known_sources=[], level="unchecked")
          and "NOT CHECKED - outside our data frame" in texts(known_sources=[], level="unchecked"),
          "I1: not asked -> 'NOT CHECKED', never 'in no database'")
    tx = texts(known_sources=[], level="checked", checked_by=["Spansh", "EDSM"])
    check(nb in tx and "checked: Spansh, EDSM" in tx, "I1: asked and unknown -> in no database + by whom")
    check(nb not in texts(known_sources=[], level="inhabited")
          and "INHABITED - known to the databases" in texts(known_sources=[], level="inhabited"),
          "I1: inhabited -> known, no request")
    check("KNOWN  EDSM" in texts(known_sources=["EDSM"], level="known"), "I1: known stays known")
    check("SCOOP at the latest jump 3/9 K" in texts(scoop=("SCOOP at the latest jump 3/9 K", "warn")),
          "F1: the latest scoop line in the briefing")
    check("LOST IN CRASH  5 scan, 4 map, 2 bio - redo" in texts(
        visited=True, lost={"scan": 5, "map": 4, "bio": ["A", "B"]}),
          "lost in a crash: named in the briefing next to 'visited before'")
    check("also explored by Xerxes" in texts(also_by=["Xerxes"])
          and not any(t.startswith("also") for t in texts()),
          "C1: 'also explored by' only when another commander was there")
    check("REGION  Inner Orion Spur" in texts(region="Inner Orion Spur")
          and not any(t.startswith("REGION") for t in texts()),
          "4.10: the codex region when known, nothing otherwise")
    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
