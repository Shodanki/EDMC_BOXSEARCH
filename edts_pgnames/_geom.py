# -*- coding: utf-8 -*-
# Derived from EDTS (https://bitbucket.org/Esvandiary/edts), files
# edtslib/sector.py and edtslib/vector3.py at commit
# 5d65cb65a53c5a814dab0421823243a5522c4c30.
# Copyright (c) 2016, Andy Martin. All rights reserved.
# BSD 3-Clause licence - full text in LICENSE.txt next to this file.
# Modified for SHBOXSEARCH (2026, Shodanki): reduced to what the
# hand-authored sector table needs - a plain three-number vector, the
# sphere and the region with its grid origin. Same arithmetic as EDTS.
# SPDX-License-Identifier: BSD-3-Clause
"""Geometry of the hand-authored (HA) sectors: spheres and their origin."""

from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

SECTOR_SIZE = 1280.0
# lower corner of sector index (0, 0, 0)
GALAXY_ORIGIN = (-49985.0, -40985.0, -24105.0)
# EDTS counts sectors relative to Wregoe (the sector holding Sol), which is
# absolute index (39, 32, 18); its corner is the reference of the HA grid.
BASE_SECTOR_INDEX = (39, 32, 18)
BASE_COORDS = tuple(o + i * SECTOR_SIZE for o, i in zip(GALAXY_ORIGIN, BASE_SECTOR_INDEX))


class Vector3(tuple):
    """(x, y, z) with names, as EDTS's Vector3 for the data table."""

    def __new__(cls, x, y=None, z=None):
        if y is None and z is None:
            x, y, z = x
        return super().__new__(cls, (float(x), float(y), float(z)))

    x = property(lambda self: self[0])
    y = property(lambda self: self[1])
    z = property(lambda self: self[2])


def _dist2(a: Sequence[float], b: Sequence[float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


class HASphere:
    __slots__ = ("centre", "radius", "origin")

    def __init__(self, centre: Vector3, radius: float) -> None:
        self.centre = centre
        self.radius = float(radius)
        self.origin = (centre[0] - radius, centre[1] - radius, centre[2] - radius)

    def contains(self, pos: Sequence[float]) -> bool:
        return _dist2(self.centre, pos) <= self.radius * self.radius


class HARegion:
    """A hand-authored sector: one or more spheres under one name."""

    __slots__ = ("name", "size", "spheres", "needs_permit", "centre", "_origin")

    def __init__(self, name: str, size: float, spheres: Iterable[HASphere],
                 needs_permit: bool = False) -> None:
        self.name = name
        self.size = float(size)
        self.spheres = list(spheres)
        self.needs_permit = bool(needs_permit)
        n = float(len(self.spheres))
        self.centre = tuple(sum(s.centre[k] for s in self.spheres) / n for k in range(3))
        self._origin = tuple(min(s.origin[k] for s in self.spheres) for k in range(3))

    @property
    def radius(self) -> float:
        return self.size

    def contains(self, pos: Sequence[float]) -> bool:
        return any(s.contains(pos) for s in self.spheres)

    def get_origin(self, cube_width: float) -> Tuple[float, float, float]:
        """Lower corner of the grid the region's system names count from,
        for boxels of this edge length (EDTS HARegion.get_origin)."""
        cw = int(cube_width)
        out = []
        for k in range(3):
            o = int(math.floor(self._origin[k]))
            o -= (o - int(BASE_COORDS[k])) % cw
            out.append(float(o))
        return (out[0], out[1], out[2])

    def min_dist(self, pos: Sequence[float]) -> float:
        """Distance from pos to the nearest sphere surface (0 inside)."""
        return max(0.0, min(math.sqrt(_dist2(s.centre, pos)) - s.radius for s in self.spheres))

    def __repr__(self) -> str:  # pragma: no cover
        return "HARegion(%s)" % self.name
