# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Ship state reminder (5.0, test finding own-3, user 17.11.2026): out of
supercruise, the overlay names on the left what is still out - landing
gear, lights, hardpoints, cargo scoop; in the SRV its lights and high
beam. The game shows these too, but small; this is the second look.

Pure: Status.json flags in, overlay lines out. Read only - nothing is sent
to the game.
"""

from __future__ import annotations

from typing import List, Tuple

Line = Tuple[str, str]

# Status.json Flags
DOCKED, LANDED, GEAR, SUPERCRUISE = 1 << 0, 1 << 1, 1 << 2, 1 << 4
HARDPOINTS, LIGHTS, SCOOP = 1 << 6, 1 << 8, 1 << 9
IN_SHIP, IN_SRV, FSD_JUMP, SRV_HIGH_BEAM = 1 << 24, 1 << 26, 1 << 30, 1 << 31

AMBER = "#FFB23E"            # overlay.COL["warn"]

__all__ = ["reminder_lines"]


def reminder_lines(flags: int) -> List[Line]:
    """What is still out, as one overlay line - empty in supercruise, while
    jumping, docked or landed, and when nothing is out."""
    try:
        flags = int(flags or 0)
    except (TypeError, ValueError):
        return []
    if flags & (SUPERCRUISE | FSD_JUMP | DOCKED | LANDED):
        return []
    if flags & IN_SHIP:
        parts = [name for bit, name in ((GEAR, "GEAR DOWN"), (HARDPOINTS, "HARDPOINTS OUT"),
                                        (SCOOP, "CARGO SCOOP OPEN"), (LIGHTS, "LIGHTS ON")) if flags & bit]
        head = "SHIP"
    elif flags & IN_SRV:
        parts = ["HIGH BEAM" if flags & SRV_HIGH_BEAM else "LIGHTS ON"] if flags & LIGHTS else []
        head = "SRV"
    else:
        return []
    if not parts:
        return []
    return [("%-5s%s" % (head, " · ".join(parts)), AMBER)]
