# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Suit temperature warning (5.0, test finding own-2, user 17.11.2026): on
foot in heat or cold the overlay says so on the left, with the suit's
health and - once it falls - how long you can stay outside at the rate it
falls now.

Status.json on foot carries Health (0..1) and Temperature (K); Flags2 say
cold, hot, very cold, very hot. The journal keeps no health, so the rate
is measured live from the last WINDOW_S seconds of Status ticks: an
estimate (~), with the seconds it rests on. Pure - nothing is sent to the
game.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

Line = Tuple[str, str]

# Status.json Flags2
ON_FOOT, COLD, HOT, VERY_COLD, VERY_HOT = 1 << 0, 1 << 8, 1 << 9, 1 << 10, 1 << 11
AMBER, RED, GREY = "#FFB23E", "#FF4D4D", "#8FA3A6"     # overlay.COL warn, alert, dim

WINDOW_S = 20.0             # the rate from this many seconds of ticks
MIN_SPAN_S = 2.0            # at least this far apart before a rate is given

__all__ = ["SuitWatch"]


def _what(flags2: int) -> Optional[Tuple[str, str]]:
    for bit, name, col in ((VERY_HOT, "VERY HOT", RED), (VERY_COLD, "VERY COLD", RED),
                           (HOT, "HOT", AMBER), (COLD, "COLD", AMBER)):
        if flags2 & bit:
            return name, col
    return None


def _mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return "%d:%02d" % (s // 60, s % 60)


class SuitWatch:
    """Status ticks in, the warning lines out (empty when all is well)."""

    def __init__(self) -> None:
        self.samples: List[Tuple[float, float]] = []      # (time, health) while too hot / cold

    def feed(self, now: float, flags2: object, health: object, temp_k: object) -> List[Line]:
        """One Status.json tick: the lines to show, [] when on foot in a
        bearable place, aboard or without the fields."""
        try:
            f2 = int(flags2 or 0)
            h = float(health) if health is not None else None
        except (TypeError, ValueError):
            f2, h = 0, None
        what = _what(f2) if f2 & ON_FOOT else None
        if what is None or h is None:
            self.samples = []
            return []
        self.samples = [s for s in self.samples if now - s[0] <= WINDOW_S] + [(now, h)]
        try:
            temp = " %.0f K" % float(temp_k) if temp_k is not None else ""
        except (TypeError, ValueError):
            temp = ""
        out = [("SUIT %s%s - %s" % (what[0], temp, "suit takes damage" if what[1] == RED else "near the limit"),
                what[1])]
        rate, span = self.rate()
        if rate:
            out.append(("     health %.0f %% · ~%s left (from %.0f s)" % (100 * h, _mmss(h / rate), span), what[1]))
        else:
            out.append(("     health %.0f %% · no damage measured yet" % (100 * h), GREY))
        return out

    def rate(self) -> Tuple[Optional[float], float]:
        """Health lost per second over the window, and the seconds it rests
        on; None while too short or nothing was lost."""
        if len(self.samples) < 2:
            return None, 0.0
        (t0, h0), (t1, h1) = self.samples[0], self.samples[-1]
        span = t1 - t0
        if span < MIN_SPAN_S or h1 >= h0:
            return None, span
        return (h0 - h1) / span, span
