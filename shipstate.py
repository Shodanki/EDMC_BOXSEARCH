# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Ship state reminder (5.0, test finding own-3, user 17.11.2026): out of
supercruise, the overlay names on the left what is still out - landing
gear, lights, hardpoints, cargo scoop; in the SRV and the Nomad lander
their gear, hardpoints, lights and high beam. The game shows these too,
but small; this is the second look.

Round 2 (user 18.11.2026, "installed but not shown"): the Nomad
(LaunchVessel, VesselType lander01) reports itself as an SRV in Status.json
(InSRV) with gear and hardpoints set - the line only knew the SRV's lights.
It now names the vehicle from the journal and stands left middle in blue,
which the orange HUD does not swallow.

Round 3 (user 19.11.2026, r2-own3): "SRV no indicators; Rhino only lights;
for both the cargo scoop would matter; the Nomad has no hardpoint
retraction". An SRV is always on the ground, so Landed no longer hides its
line; Scarab and Rhino are named (SRVType) and show the cargo scoop; the
Nomad leaves hardpoints out.

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

BLUE = "#4DA6FF"             # not the HUD's orange - stands out against it

# what each vehicle names (Status.json bit, text) - user 19.11.: the Nomad
# cannot retract its hardpoints, SRVs have no gear
_SHIP_PARTS = ((GEAR, "GEAR DOWN"), (HARDPOINTS, "HARDPOINTS OUT"), (SCOOP, "CARGO SCOOP OPEN"))
_LANDER_PARTS = ((GEAR, "GEAR DOWN"), (SCOOP, "CARGO SCOOP OPEN"))
_SRV_PARTS = ((HARDPOINTS, "HARDPOINTS OUT"), (SCOOP, "CARGO SCOOP OPEN"))
_LANDERS = ("NOMAD", "VESSEL")

__all__ = ["reminder_lines", "VehicleWatch"]


class VehicleWatch:
    """Which small vehicle is out, from the journal: LaunchSRV names the SRV,
    LaunchVessel the Nomad lander (it reports as InSRV in Status.json)."""

    def __init__(self) -> None:
        self.kind = "SRV"

    def feed(self, ev: str, entry: dict) -> None:
        """Note a launch; any other event leaves the last one standing."""
        if ev == "LaunchSRV":
            name = str(entry.get("SRVType_Localised") or entry.get("SRVType") or "").lower()
            self.kind = "RHINO" if "rhino" in name else "SCARAB" if "scarab" in name or "testbuggy" in name else "SRV"
        elif ev == "LaunchVessel":
            name = str(entry.get("VesselType_Localised") or entry.get("VesselType") or "")
            self.kind = "NOMAD" if "nomad" in name.lower() or "lander" in name.lower() else "VESSEL"


def reminder_lines(flags: int, vehicle: str = "SRV") -> List[Line]:
    """What is still out, as one overlay line - empty in supercruise, while
    jumping, docked or landed, and when nothing is out. ``vehicle`` names
    what InSRV is (SRV, NOMAD - VehicleWatch.kind)."""
    try:
        flags = int(flags or 0)
    except (TypeError, ValueError):
        return []
    head = "SHIP" if flags & IN_SHIP else (vehicle or "SRV")[:6] if flags & IN_SRV else None
    ground = head not in (None, "SHIP") + _LANDERS      # an SRV is always on the ground
    if head is None or flags & (SUPERCRUISE | FSD_JUMP | DOCKED) or (flags & LANDED and not ground):
        return []
    table = _SHIP_PARTS if head == "SHIP" else _LANDER_PARTS if head in _LANDERS else _SRV_PARTS
    parts = [name for bit, name in table if flags & bit]
    if flags & LIGHTS:
        parts.append("HIGH BEAM" if ground and flags & SRV_HIGH_BEAM else "LIGHTS ON")
    if not parts:
        return []
    return [("%-5s %s" % (head, " · ".join(parts)), BLUE)]
