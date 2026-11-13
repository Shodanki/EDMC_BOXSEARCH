# -*- coding: utf-8 -*-
# Derived from EliteDangerousRegionMap by Ben Peddell (klightspeed),
# https://github.com/klightspeed/EliteDangerousRegionMap, file RegionMap.py
# at commit 6c1191a58e1e593966f44f16235ab39d1ad24d84.
# Copyright (c) 2020 Ben Peddell. MIT License - full text in LICENSE next to
# this file. The region map was traced from Frontier Developments' galaxy
# map; the region names are Frontier's.
# Modified for SHBOXSEARCH (2026, Shodanki): a package with lazy loading of
# the unchanged RegionMapData.py, names for the id64 boxel kept, and the
# original's EDSM lookup and command line left out - nothing here goes to
# the network.
# SPDX-License-Identifier: MIT
"""
Codex region of a position: find_region(x, y, z) -> (id, name) or None.

The 42 regions of the galaxy (Galactic Centre ... The Void) as the game's
codex names them ("$Codex_RegionName_18;" = Inner Orion Spur). The map is a
2D grid of about 49 ly squares in the galactic plane; height is ignored.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

X0 = -49985
Y0 = -40985
Z0 = -24105

_DATA = None


def _data():
    global _DATA
    if _DATA is None:
        from . import RegionMapData
        _DATA = (RegionMapData.regions, RegionMapData.regionmap)
    return _DATA


def region_names() -> List[str]:
    """All region names, index = region id (0 is None: outside)."""
    return list(_data()[0])


def find_region(x: float, y: float, z: float) -> Optional[Tuple[int, str]]:
    """(region id, name) for a position, or None outside every region."""
    regions, regionmap = _data()
    px = int((x - X0) * 83 / 4096)
    pz = int((z - Z0) * 83 / 4096)
    if px < 0 or pz < 0 or pz >= len(regionmap):
        return None
    row = regionmap[pz]
    rx = 0
    pv = 0
    for rl, v in row:
        if px < rx + rl:
            pv = v
            break
        rx += rl
    if pv == 0:
        return None
    return (pv, regions[pv])


def find_region_for_id64(id64: int) -> Optional[Tuple[int, str]]:
    """Region of the corner of the boxel an id64 names (as the original's
    findRegionForBoxel) - for a system known only by its address."""
    masscode = id64 & 7
    z = (((id64 >> 3) & (0x3FFF >> masscode)) << masscode) * 10 + Z0
    y = (((id64 >> (17 - masscode)) & (0x1FFF >> masscode)) << masscode) * 10 + Y0
    x = (((id64 >> (30 - masscode * 2)) & (0x3FFF >> masscode)) << masscode) * 10 + X0
    return find_region(x, y, z)


def region_id_from_codex(value: str) -> Optional[int]:
    """'$Codex_RegionName_18;' -> 18 (the journal's CodexEntry Region)."""
    if not value:
        return None
    v = value.strip().rstrip(";")
    if not v.startswith("$Codex_RegionName_"):
        return None
    try:
        return int(v[len("$Codex_RegionName_"):])
    except ValueError:
        return None


__all__ = ["find_region", "find_region_for_id64", "region_names", "region_id_from_codex"]
