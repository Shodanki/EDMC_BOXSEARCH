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
from SHBOXSEARCH.overlay import (ANCHORS, COL, CockpitOverlay, briefing_lines)  # noqa: E402
from SHBOXSEARCH import shipstate as ss  # noqa: E402
from SHBOXSEARCH import suittemp as st  # noqa: E402


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
    od = briefing_lines(dict(name="X", kind="target", known_sources=["EDSM"], level="known",
                             odds={"p": 0.137, "n": 131, "reason": "off-plane, mc b"}))
    check(("FIND ~14 % (131)  off-plane, mc b", COL["data"]) in od, "FX5: the chance of a find and why")
    hi = briefing_lines(dict(name="X", odds={"p": 0.2, "n": 40, "reason": "off-plane"}))
    check(("FIND ~20 % (40)  off-plane", COL["new"]) in hi, "FX5: from 15 % (findodds band) it stands out")
    check(not any(t.startswith("FIND") for t in texts()), "FX5: no odds, no line")
    lo = briefing_lines(dict(name="X", odds={"p": 0.02, "n": 0, "reason": "no own data yet"}))
    check(("FIND ~2 % (0)  no own data yet", COL["dim"]) in lo, "FX5: a low chance is dim")
    # 5.0 (own-3): gear, lights, hardpoints still out - left, out of supercruise
    ship = ss.IN_SHIP
    rl = ss.reminder_lines
    check(rl(ship | ss.GEAR | ss.LIGHTS | ss.HARDPOINTS)[0][0] == "SHIP GEAR DOWN · HARDPOINTS OUT · LIGHTS ON",
          "own-3: in orbit, all named: %r" % rl(ship | ss.GEAR | ss.LIGHTS | ss.HARDPOINTS))
    check(all(not rl(ship | ss.GEAR | x) for x in (ss.SUPERCRUISE, ss.FSD_JUMP, ss.DOCKED, ss.LANDED)),
          "own-3: nothing in supercruise, jumping, docked or landed")
    check(not rl(ship) and not rl(None) and not rl("x"), "own-3: nothing out, nothing shown")
    check(rl(ss.IN_SRV | ss.LIGHTS)[0][0] == "SRV  LIGHTS ON"
          and rl(ss.IN_SRV | ss.LIGHTS | ss.SRV_HIGH_BEAM)[0][0] == "SRV  HIGH BEAM" and not rl(ss.IN_SRV),
          "own-3: SRV lights and high beam")
    sent.clear()
    ov.hidden = False
    check(ov.show_state(rl(ship | ss.GEAR)) and sent and sent[-1][0].endswith("state-0")
          and ov._origin("state") == ANCHORS["bottom-left"], "own-3: drawn bottom left while the blocks start at the top")
    n = len(sent)
    check(ov.show_state(rl(ship | ss.GEAR)) and len(sent) == n, "own-3: unchanged - not sent again")
    check(not ov.show_state([]) and sent[-1][1] == "" and not ov._drawn.get("state"), "own-3: gear up - blanked")
    ov.position = "bottom-left"
    check(ov._origin("state") == ANCHORS["top-left"], "own-3: blocks at the bottom - top left")
    ov.hidden = True
    check(not ov.show_state(rl(ship | ss.GEAR)), "own-3: not over a map screen")
    # 5.0 (own-2): on foot in heat or cold - suit health and time left
    w = st.SuitWatch()
    foot = st.ON_FOOT
    check(w.feed(0, foot, 1.0, 290) == [] and w.feed(0, st.VERY_HOT, 1.0, 900) == [],
          "own-2: bearable, or hot but not on foot: nothing")
    first = w.feed(100.0, foot | st.VERY_HOT, 1.0, 812.4)
    check(first[0] == ("SUIT VERY HOT 812 K - suit takes damage", st.RED) and "no damage measured yet" in first[1][0],
          "own-2: very hot, no rate yet: %r" % first)
    w.feed(105.0, foot | st.VERY_HOT, 0.9, 812)
    lines = w.feed(110.0, foot | st.VERY_HOT, 0.8, 812)      # 2 % per second
    check(lines[1][0] == "     health 80 % · ~0:40 left (from 10 s)", "own-2: time left at the rate now: %r" % lines)
    w.feed(140.0, foot | st.VERY_HOT, 0.8, 812)
    check(w.rate() == (None, 0.0) or w.rate()[0] is None, "own-2: older ticks than 20 s drop out of the rate")
    check(w.feed(141.0, foot | st.COLD, 0.8, 150)[0] == ("SUIT COLD 150 K - near the limit", st.AMBER),
          "own-2: cold is amber, near the limit")
    check(w.feed(142.0, foot, 0.8, 250) == [] and w.samples == [], "own-2: bearable again - gone, rate forgotten")
    check(w.feed(143.0, foot | st.HOT, None, 400) == [] and w.feed(144.0, "x", 1, 1) == [],
          "own-2: without health or with junk: nothing")
    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
