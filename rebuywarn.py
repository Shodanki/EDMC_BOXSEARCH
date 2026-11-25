# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
RB1 (5.1.0, user 24.11.): an overlay warning when the credits would not pay
the rebuy of the ship you fly - optional, off until switched on.

The rebuy comes with every Loadout (``Rebuy``), the credits with LoadGame
(``Credits``) and, live, with Status.json (``Balance``). The line shows only
in the ship and away from a pad (not docked, not landed): that is where the
ship can be lost. Read only - nothing is sent to the game.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

Line = Tuple[str, str]

DOCKED, LANDED, IN_SHIP = 1 << 0, 1 << 1, 1 << 24
AMBER = "#FFB000"

__all__ = ["RebuyWatch", "short_by", "overlay_lines"]


def short_by(credits: Any, rebuy: Any) -> Optional[int]:
    """How many credits are missing for the rebuy, or None when enough (or
    either is unknown)."""
    try:
        c, r = int(credits), int(rebuy)
    except (TypeError, ValueError):
        return None
    return r - c if r > 0 and c < r else None


def _mcr(v: int) -> str:
    return "%.1f M" % (v / 1e6) if abs(v) >= 1e6 else "{:,}".format(v)


def overlay_lines(flags: Any, credits: Any, rebuy: Any) -> List[Line]:
    """The amber line in the ship, away from a pad, while the credits do not
    cover the rebuy; else nothing."""
    try:
        flags = int(flags or 0)
    except (TypeError, ValueError):
        return []
    if not flags & IN_SHIP or flags & (DOCKED | LANDED):
        return []
    miss = short_by(credits, rebuy)
    if miss is None:
        return []
    return [("REBUY %s CR - CREDITS %s - %s SHORT" % (_mcr(int(rebuy)), _mcr(int(credits)), _mcr(miss)), AMBER)]


class RebuyWatch:
    """The rebuy of the ship flown and the last known credits."""

    def __init__(self) -> None:
        self.rebuy: Optional[int] = None
        self.credits: Optional[int] = None

    def feed(self, ev: str, entry: Dict[str, Any]) -> None:
        """Loadout: the rebuy; LoadGame: the credits at login."""
        if ev == "Loadout" and entry.get("Rebuy") is not None:
            self.rebuy = entry.get("Rebuy")
        elif ev == "LoadGame" and entry.get("Credits") is not None:
            self.credits = entry.get("Credits")

    def lines(self, status: Dict[str, Any]) -> List[Line]:
        """From a Status.json entry (its Balance is the live credit count)."""
        if status.get("Balance") is not None:
            self.credits = status.get("Balance")
        return overlay_lines(status.get("Flags"), self.credits, self.rebuy)
