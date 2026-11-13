# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
procgen.py - Elite Dangerous procedural generation maths
========================================================
Name  <->  id64 (SystemAddress)  <->  boxel geometry

Verified against:
  Eol Prou RS-T d3-94 (Colonia) = id64 3238296097059 @ (-9530.5, -910.28125, 19808.125)
  All procgen systems from the supplied journals and JSON files - 0 mismatches.

No external dependencies. Python 3.8+.

Name format:   <Sector> <L1><L2>-<L3> <mc><n1>-<n2>     when n1 > 0
               <Sector> <L1><L2>-<L3> <mc><n2>          when n1 = 0
  Example:     Synuefe   VA   - I      b  2   - 1
               Synuefe   XV   - C      d  12          (n1 = 0, n2 = 12)
  Frontier drops "0-" when the high part of the boxel number is zero. Such a
  name is NOT a boxel holding a single system - it is system n2 of boxel
  "XV-C d", and that boxel may hold d0, d1, d2 ... like any other. Verified
  against the game's own SystemAddress: Synuefe XV-C d12 = id64 422810994947
  decodes to n2 = 12. Mass code h boxels always have n1 = 0 for that reason.
  boxel id   = n1*26^3 + L3*26^2 + L2*26 + L1
  boxel id   = bx | (by << 7) | (bz << 14)      (7 bits per axis, base 128)
  boxel size = 10 * 2^mc  ly   (a=10, b=20, c=40, d=80, e=160, f=320, g=640, h=1280)

id64 bit layout (LSB -> MSB):
  [3 bit masscode][14-mc bit Z][13-mc bit Y][14-mc bit X][11+3mc bit n2][9 bit body id]
  where each Z/Y/X field holds (boxel | sector << (7-mc)).
"""

from __future__ import annotations

import math
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

try:
    # Sector names computed with EDTS's algorithm (BSD 3-Clause, Andy
    # Martin) - see edts_pgnames/SOURCE.md. Without the folder the plugin
    # falls back to the names it learnt, as before 4.10.
    import edts_pgnames as _edts
except Exception:  # pragma: no cover - folder missing or broken
    _edts = None

__all__ = [
    "GALAXY_ORIGIN", "SECTOR_SIZE", "MASSCODES",
    "ParsedName", "parse_name", "make_name", "boxel_size",
    "id64_from_parts", "decode_id64", "id64_from_name",
    "sector_index_of_coords", "boxel_index_of_coords",
    "boxel_corner", "boxel_center", "boxel_intersects_sphere",
    "boxels_in_sphere", "SectorRegistry", "parse_boxel_only",
    "boxel_prefix", "name_in_boxel", "parse_boxel_key",
    "computed_sector_name", "computed_sector_index", "is_ha_sector",
    "ha_regions_near", "boxel_labels", "boxel_key_of",
]

# Lower corner of sector (0,0,0) in galactic coordinates
GALAXY_ORIGIN: Tuple[float, float, float] = (-49985.0, -40985.0, -24105.0)
SECTOR_SIZE: float = 1280.0
MASSCODES: str = "abcdefgh"

_NAME_RE = re.compile(
    r"^(?P<sector>.+?)\s+"
    r"(?P<l1>[A-Za-z])(?P<l2>[A-Za-z])-(?P<l3>[A-Za-z])\s+"
    r"(?P<mc>[A-Ha-h])(?:(?P<n1>\d+)-)?(?P<n2>\d+)$"
)


def parse_boxel_only(name: str):
    """
    Kept for backwards compatibility only - always returns None.

    Up to 4.0 a name like "Synuefe XV-C d12" was read as a boxel holding a
    single system. That was wrong: it is system n2=12 of boxel "XV-C d"
    (n1 = 0), and parse_name() now handles it like any other procgen name.
    """
    return None


def boxel_prefix(key: str) -> str:
    """
    Galaxy map search prefix for a boxel key.

    "Synuefe VA-I b2" -> "Synuefe VA-I b2-"   (lists b2-0, b2-1 ...)
    "Synuefe XV-C d"  -> "Synuefe XV-C d"     (lists d0, d1 ... - and also
                                               the d1-.., d2-.. boxels, which
                                               are different boxels)
    """
    return key if key[-1:].isalpha() else key + "-"


def name_in_boxel(key: str, n2: int) -> str:
    """Name of system n2 inside the boxel with this key."""
    return "%s%d" % (boxel_prefix(key), n2)


def parse_boxel_key(key: str) -> "Optional[ParsedName]":
    """Parse a boxel key by parsing its system -0."""
    return parse_name(name_in_boxel(key, 0))


def boxel_size(mc: int) -> float:
    """Edge length of a boxel of the given mass code, in ly."""
    return 10.0 * (1 << mc)


class ParsedName:
    """A decomposed procedurally generated system name."""

    __slots__ = ("sector", "mc", "n1", "n2", "boxel", "letters", "raw")

    def __init__(self, sector: str, mc: int, n1: int, n2: int,
                 boxel: Tuple[int, int, int], letters: Tuple[str, str, str], raw: str):
        self.sector = sector
        self.mc = mc
        self.n1 = n1
        self.n2 = n2
        self.boxel = boxel          # boxel index within the sector
        self.letters = letters
        self.raw = raw

    @property
    def size(self) -> float:
        return boxel_size(self.mc)

    @property
    def boxel_key(self) -> str:
        """Stable identifier of the boxel (name without the -n2 suffix)."""
        n1 = str(self.n1) if self.n1 else ""
        return "%s %s%s-%s %s%s" % (
            self.sector, self.letters[0], self.letters[1], self.letters[2],
            MASSCODES[self.mc], n1,
        )

    @property
    def prefix(self) -> str:
        """Galaxy map search prefix that lists this boxel."""
        return boxel_prefix(self.boxel_key)

    def with_n2(self, n2: int) -> str:
        return make_name(self.sector, self.mc, self.boxel, n2)

    def __repr__(self) -> str:  # pragma: no cover
        return "<ParsedName %s mc=%s boxel=%s n2=%s>" % (
            self.sector, MASSCODES[self.mc], self.boxel, self.n2)


def parse_name(name: str) -> Optional[ParsedName]:
    """Decompose a procgen name. Returns None for catalogue/hand-authored names."""
    if not name:
        return None
    m = _NAME_RE.match(name.strip())
    if not m:
        return None
    g = m.groupdict()
    mc = MASSCODES.index(g["mc"].lower())
    n1 = int(g["n1"]) if g["n1"] else 0
    l1, l2, l3 = g["l1"].upper(), g["l2"].upper(), g["l3"].upper()
    boxel_id = (n1 * 17576
                + (ord(l3) - 65) * 676
                + (ord(l2) - 65) * 26
                + (ord(l1) - 65))
    boxel = (boxel_id & 0x7F, (boxel_id >> 7) & 0x7F, (boxel_id >> 14) & 0x7F)
    return ParsedName(g["sector"], mc, n1, int(g["n2"]), boxel, (l1, l2, l3), name.strip())


def make_name(sector: str, mc: int, boxel: Sequence[int], n2: int) -> str:
    """Build a procgen name from sector name, mass code, boxel index and n2."""
    bx, by, bz = boxel
    if not (0 <= bx < 128 and 0 <= by < 128 and 0 <= bz < 128):
        raise ValueError("boxel index out of range 0..127: %r" % (boxel,))
    boxel_id = bx | (by << 7) | (bz << 14)
    n1, rem = divmod(boxel_id, 17576)
    i3, rem = divmod(rem, 676)
    i2, i1 = divmod(rem, 26)
    core = "%s%s-%s %s" % (chr(65 + i1), chr(65 + i2), chr(65 + i3), MASSCODES[mc])
    if n1:
        return "%s %s%d-%d" % (sector, core, n1, n2)
    # n1 = 0: Frontier writes "XV-C d12", not "XV-C d0-12" or "XV-C d-12"
    return "%s %s%d" % (sector, core, n2)


# ---------------------------------------------------------------------------
# id64
# ---------------------------------------------------------------------------

def id64_from_parts(sector_idx: Sequence[int], mc: int,
                    boxel: Sequence[int], n2: int, body_id: int = 0) -> int:
    """Assemble an id64 (SystemAddress) from its components."""
    sx, sy, sz = sector_idx
    bx, by, bz = boxel
    b = 7 - mc
    v = mc
    v |= (bz | (sz << b)) << 3
    v |= (by | (sy << b)) << (3 + 14 - mc)
    v |= (bx | (sx << b)) << (3 + 14 - mc + 13 - mc)
    v |= n2 << (44 - 3 * mc)
    v |= body_id << 55
    return v


def decode_id64(id64: int) -> Dict[str, object]:
    """Split an id64 into mass code, sector/boxel index, n2 and boxel corner."""
    mc = id64 & 7
    b = 7 - mc
    zf = (id64 >> 3) & ((1 << (14 - mc)) - 1)
    yf = (id64 >> (3 + 14 - mc)) & ((1 << (13 - mc)) - 1)
    xf = (id64 >> (3 + 14 - mc + 13 - mc)) & ((1 << (14 - mc)) - 1)
    n2 = (id64 >> (44 - 3 * mc)) & ((1 << (11 + 3 * mc)) - 1)
    size = boxel_size(mc)
    corner = (GALAXY_ORIGIN[0] + (xf << mc) * 10.0,
              GALAXY_ORIGIN[1] + (yf << mc) * 10.0,
              GALAXY_ORIGIN[2] + (zf << mc) * 10.0)
    return {
        "mc": mc,
        "n2": n2,
        "body_id": (id64 >> 55) & 0x1FF,
        "size": size,
        "corner": corner,
        "center": (corner[0] + size / 2, corner[1] + size / 2, corner[2] + size / 2),
        "sector_idx": (xf >> b, yf >> b, zf >> b),
        "boxel": (xf & ((1 << b) - 1), yf & ((1 << b) - 1), zf & ((1 << b) - 1)),
    }


def id64_slot(id64: int) -> Tuple[int, Tuple[int, int, int], int]:
    """(mass code, global boxel index, n2) of an id64 - the physical slot.

    The slot is there whatever name the system carries: a catalogue star
    ("HIP 33254") fills n2 = 0 of "Synuefe RH-U c19" as much as a procedural
    name would; the galaxy map then lists no "-0" under that prefix."""
    d = decode_id64(id64)
    per = 128 >> d["mc"]
    g = tuple(s * per + b for s, b in zip(d["sector_idx"], d["boxel"]))
    return d["mc"], g, d["n2"]  # type: ignore[return-value]


def id64_of_slot(mc: int, gidx: Sequence[int], n2: int) -> int:
    """The id64 of slot n2 in a physical boxel (global index)."""
    per = 128 >> mc
    sector = tuple(int(g) // per for g in gidx)
    boxel = tuple(int(g) % per for g in gidx)
    return id64_from_parts(sector, mc, boxel, n2)


def id64_matches_position(id64: int, pos: Sequence[float], tol: float = 0.2) -> bool:
    """Does a position lie inside the boxel the id64 names? A check that a
    number some database calls an id64 really is one."""
    try:
        d = decode_id64(int(id64))
    except (TypeError, ValueError):
        return False
    c, s = d["corner"], d["size"]
    return all(c[i] - tol <= float(pos[i]) <= c[i] + s + tol for i in range(3))


def id64_from_name(name: str, sector_idx: Sequence[int]) -> Optional[int]:
    """id64 from a name plus a known sector index."""
    p = parse_name(name)
    if p is None:
        return None
    return id64_from_parts(sector_idx, p.mc, p.boxel, p.n2)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def star_pos(value: object) -> Optional[Tuple[float, float, float]]:
    """A journal StarPos as (x, y, z) - or None unless it is three finite
    numbers. The game always writes a list of three floats; anything else
    (a damaged line, a third-party tool) must not become the position, or
    every distance after it fails."""
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        out = tuple(float(v) for v in value[:3])
    except (TypeError, ValueError):
        return None
    if any(isinstance(v, bool) for v in value[:3]) or not all(math.isfinite(v) for v in out):
        return None
    return out  # type: ignore[return-value]


def sector_index_of_coords(x: float, y: float, z: float) -> Tuple[int, int, int]:
    return tuple(int(math.floor((c - o) / SECTOR_SIZE))
                 for c, o in zip((x, y, z), GALAXY_ORIGIN))  # type: ignore[return-value]


def boxel_index_of_coords(x: float, y: float, z: float, mc: int) -> Tuple[int, int, int]:
    """Global (not sector-relative) boxel index."""
    s = boxel_size(mc)
    return tuple(int(math.floor((c - o) / s))
                 for c, o in zip((x, y, z), GALAXY_ORIGIN))  # type: ignore[return-value]


def boxel_corner(global_idx: Sequence[int], mc: int) -> Tuple[float, float, float]:
    s = boxel_size(mc)
    return tuple(o + i * s for i, o in zip(global_idx, GALAXY_ORIGIN))  # type: ignore[return-value]


def boxel_center(global_idx: Sequence[int], mc: int) -> Tuple[float, float, float]:
    s = boxel_size(mc)
    c = boxel_corner(global_idx, mc)
    return (c[0] + s / 2, c[1] + s / 2, c[2] + s / 2)


def boxel_intersects_sphere(global_idx: Sequence[int], mc: int,
                            center: Sequence[float], radius: float) -> bool:
    """Exact AABB / sphere intersection test."""
    s = boxel_size(mc)
    c = boxel_corner(global_idx, mc)
    d2 = 0.0
    for k in range(3):
        lo, hi = c[k], c[k] + s
        v = center[k]
        if v < lo:
            d2 += (lo - v) ** 2
        elif v > hi:
            d2 += (v - hi) ** 2
    return d2 <= radius * radius


def boxels_in_sphere(mc: int, center: Sequence[float], radius: float
                     ) -> List[Tuple[int, int, int]]:
    """All global boxel indices of that mass code whose cube meets the sphere."""
    s = boxel_size(mc)
    rng = []
    for k in range(3):
        lo = int(math.floor((center[k] - radius - GALAXY_ORIGIN[k]) / s))
        hi = int(math.floor((center[k] + radius - GALAXY_ORIGIN[k]) / s))
        rng.append((lo, hi))
    out: List[Tuple[int, int, int]] = []
    for i in range(rng[0][0], rng[0][1] + 1):
        for j in range(rng[1][0], rng[1][1] + 1):
            for k in range(rng[2][0], rng[2][1] + 1):
                if boxel_intersects_sphere((i, j, k), mc, center, radius):
                    out.append((i, j, k))
    return out


# ---------------------------------------------------------------------------
# Computed sector names and hand-authored sectors (edts_pgnames)
# ---------------------------------------------------------------------------
#
# Every sector of the 128 x 128 x 128 grid has a procedural name the game
# computes from its index. On top of that lie some 470 hand-authored (HA)
# sectors - "Col 285 Sector", "NGC 2232 Sector" ... - spheres whose systems
# are named after the sphere instead, with boxel letters counted from the
# sphere's own grid origin. The physical boxel and the system number n2 stay
# the same (checked: 665 such systems of a real survey, id64 against name),
# only the label changes. A boxel that a sphere's surface cuts can hold
# systems of both labels: which one a star gets depends on where it lies.

def computed_sector_name(idx: Sequence[int]) -> Optional[str]:
    """Procedural name of the sector at an absolute index, or None."""
    if _edts is None:
        return None
    try:
        return _edts.sector_name(idx)
    except Exception:
        return None


def computed_sector_index(name: str) -> Optional[Tuple[int, int, int]]:
    """Absolute index of a procedural sector name, or None (unknown, a
    hand-authored name, or edts_pgnames missing)."""
    if _edts is None or not name:
        return None
    try:
        return _edts.sector_index(name)
    except Exception:
        return None


def is_ha_sector(name: str) -> bool:
    """True for a hand-authored sector name the table knows."""
    return _edts is not None and _edts.ha_region(name) is not None


def ha_regions_near(center: Sequence[float], radius: float) -> list:
    """Hand-authored sectors whose spheres meet this sphere (smallest first)."""
    if _edts is None:
        return []
    return _edts.ha_regions_near(center, radius)


def _corners(gidx: Sequence[int], mc: int) -> List[Tuple[float, float, float]]:
    s = boxel_size(mc)
    c = boxel_corner(gidx, mc)
    return [(c[0] + i * s, c[1] + j * s, c[2] + k * s)
            for i in (0, 1) for j in (0, 1) for k in (0, 1)]


def _ha_label(region, gidx: Sequence[int], mc: int
              ) -> Optional[Tuple[str, Tuple[int, int, int]]]:
    """(region name, boxel index in the region's grid) - or None if that
    index falls outside 0..127 (it never does for real regions)."""
    cw = boxel_size(mc)
    o = region.get_origin(cw)
    rel = tuple(int(gidx[k]) - int(round((o[k] - GALAXY_ORIGIN[k]) / cw)) for k in range(3))
    if not all(0 <= v < 128 for v in rel):
        return None
    return (region.name, rel)  # type: ignore[return-value]


def boxel_labels(gidx: Sequence[int], mc: int,
                 sector_of: Optional[Callable[[Tuple[int, int, int]], Optional[str]]] = None,
                 regions: Optional[list] = None
                 ) -> List[Tuple[str, Tuple[int, int, int]]]:
    """
    Every (sector name, boxel index within that sector) a system of this
    physical boxel can be named with, the most likely first: the label of
    the boxel's centre. One label for most boxels; two or more where the
    surface of a hand-authored sphere cuts the boxel.

    sector_of(index) gives the procedural sector name (learnt names first);
    by default the computed name. regions limits the hand-authored sectors
    looked at (ha_regions_near of the sphere being planned) - by default
    the ones near this boxel. Empty list: no name known at all.
    """
    gidx = (int(gidx[0]), int(gidx[1]), int(gidx[2]))
    s = boxel_size(mc)
    centre = boxel_center(gidx, mc)
    if regions is None:
        regions = ha_regions_near(centre, s * 0.8661)
    labels: List[Tuple[str, Tuple[int, int, int]]] = []
    centre_label: Optional[Tuple[str, Tuple[int, int, int]]] = None
    fully_inside = False
    if regions:
        corners = _corners(gidx, mc)
        for r in regions:                               # smallest first
            if not any(boxel_intersects_sphere(gidx, mc, sp.centre, sp.radius)
                       for sp in r.spheres):
                continue
            lab = _ha_label(r, gidx, mc)
            if lab is not None:
                labels.append(lab)
                if centre_label is None and r.contains(centre):
                    centre_label = lab
            if any(all(sp.contains(c) for c in corners) for sp in r.spheres):
                fully_inside = True                     # nothing larger names it
                break
    if not fully_inside:
        per = 128 >> mc
        sidx = (gidx[0] // per, gidx[1] // per, gidx[2] // per)
        name = sector_of(sidx) if sector_of is not None else computed_sector_name(sidx)
        if name:
            pg_label = (name, (gidx[0] % per, gidx[1] % per, gidx[2] % per))
            labels.append(pg_label)
            if centre_label is None:
                centre_label = pg_label
    if centre_label is not None and labels and labels[0] != centre_label:
        labels.remove(centre_label)
        labels.insert(0, centre_label)
    return labels


def boxel_key_of(sector: str, mc: int, boxel: Sequence[int]) -> str:
    """Boxel key ("Synuefe XV-C d") of a sector name and boxel index."""
    p = parse_name(make_name(sector, mc, boxel, 0))
    return p.boxel_key if p else ""


# ---------------------------------------------------------------------------
# Sector registry
# ---------------------------------------------------------------------------

class SectorRegistry:
    """
    Learns the sector name <-> sector index mapping from observed systems.

    This removes any need to reimplement Frontier's sector name generator:
    a single known system per sector is enough to construct procgen names
    there. Observations from the journal (name + id64) are exact, and so are
    observations from external databases (name + coordinates) as long as the
    coordinates are correct.
    """

    def __init__(self) -> None:
        self.by_name: Dict[str, Tuple[int, int, int]] = {}
        self.by_index: Dict[Tuple[int, int, int], str] = {}
        self.conflicts: List[Tuple[str, Tuple[int, int, int], Tuple[int, int, int]]] = []

    def learn_from_id64(self, name: str, id64: int) -> bool:
        p = parse_name(name)
        if p is None:
            return False
        d = decode_id64(id64)
        if d["mc"] != p.mc or d["boxel"] != p.boxel or d["n2"] != p.n2:
            return False  # name and id64 disagree - ignore
        return self._add(p.sector, d["sector_idx"])  # type: ignore[arg-type]

    def learn_from_coords(self, name: str, x: float, y: float, z: float) -> bool:
        p = parse_name(name)
        if p is None:
            return False
        si = sector_index_of_coords(x, y, z)
        # sanity check: the coordinate must lie inside the boxel the name implies
        s = p.size
        corner = tuple(o + si[k] * SECTOR_SIZE + p.boxel[k] * s
                       for k, o in enumerate(GALAXY_ORIGIN))
        for k, c in enumerate((x, y, z)):
            if not (corner[k] <= c < corner[k] + s):
                return False
        return self._add(p.sector, si)

    def _add(self, sector: str, idx: Tuple[int, int, int]) -> bool:
        idx = (int(idx[0]), int(idx[1]), int(idx[2]))
        if _edts is not None and computed_sector_index(sector) != idx:
            # The registry holds procedural sectors only. A hand-authored
            # name, or a pair that disagrees with the computed name (bad
            # external coordinates), would put the wrong name on a whole
            # sector - it is refused and kept as a conflict.
            self.conflicts.append((sector, computed_sector_index(sector), idx))
            return False
        old = self.by_name.get(sector)
        if old is not None and old != idx:
            self.conflicts.append((sector, old, idx))
            return False
        self.by_name[sector] = idx
        self.by_index[idx] = sector
        return True

    def index_of(self, sector: str) -> Optional[Tuple[int, int, int]]:
        return self.by_name.get(sector)

    def name_of(self, idx: Sequence[int]) -> Optional[str]:
        return self.by_index.get(tuple(idx))  # type: ignore[arg-type]

    def resolve(self, idx: Sequence[int]) -> Optional[str]:
        """Procedural sector name: learnt if known, else computed."""
        return self.name_of(idx) or computed_sector_name(idx)

    def name_for_coords(self, x: float, y: float, z: float) -> Optional[str]:
        return self.name_of(sector_index_of_coords(x, y, z))

    def known_sectors_in_sphere(self, center: Sequence[float], radius: float
                                ) -> List[Tuple[str, Tuple[int, int, int]]]:
        found, missing = [], []
        rng = []
        for k in range(3):
            lo = int(math.floor((center[k] - radius - GALAXY_ORIGIN[k]) / SECTOR_SIZE))
            hi = int(math.floor((center[k] + radius - GALAXY_ORIGIN[k]) / SECTOR_SIZE))
            rng.append((lo, hi))
        for i in range(rng[0][0], rng[0][1] + 1):
            for j in range(rng[1][0], rng[1][1] + 1):
                for k in range(rng[2][0], rng[2][1] + 1):
                    nm = self.by_index.get((i, j, k))
                    (found if nm else missing).append(
                        (nm, (i, j, k)) if nm else (None, (i, j, k)))
        self.last_missing = missing
        return found

    def to_dict(self) -> Dict[str, List[int]]:
        return {k: list(v) for k, v in self.by_name.items()}

    def load_dict(self, d: Dict[str, Sequence[int]]) -> None:
        for k, v in d.items():
            self._add(k, tuple(v))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Self test
# ---------------------------------------------------------------------------

def _selftest() -> int:
    fails = 0

    def check(label, got, want):
        nonlocal fails
        ok = got == want
        if not ok:
            fails += 1
        print("  [%s] %-42s got=%r want=%r" % ("OK" if ok else "FAIL", label, got, want))

    print("procgen self test")
    p = parse_name("Eol Prou RS-T d3-94")
    check("parse mass code", p.mc, 3)
    check("parse boxel", p.boxel, (9, 4, 4))
    check("parse n2", p.n2, 94)
    i = id64_from_parts((31, 31, 34), p.mc, p.boxel, p.n2)
    check("id64 Colonia", i, 3238296097059)
    d = decode_id64(i)
    check("decode sector", d["sector_idx"], (31, 31, 34))
    check("decode boxel", d["boxel"], (9, 4, 4))
    check("name round trip", make_name("Eol Prou", p.mc, p.boxel, p.n2), "Eol Prou RS-T d3-94")
    corner = d["corner"]
    inside = all(corner[k] <= c < corner[k] + d["size"]
                 for k, c in enumerate((-9530.5, -910.28125, 19808.125)))
    check("Colonia inside boxel", inside, True)

    reg = SectorRegistry()
    check("learn from id64", reg.learn_from_id64("Eol Prou RS-T d3-94", 3238296097059), True)
    check("sector index", reg.index_of("Eol Prou"), (31, 31, 34))

    # Boxel with n1 = 0 (boxel id < 26^3): Frontier drops the "0-"
    nm = make_name("Synuefe", 1, (0, 0, 0), 7)
    check("make_name n1=0", nm, "Synuefe AA-A b7")
    check("re-parse", parse_name(nm).boxel, (0, 0, 0))
    check("boxel key n1=0", parse_name(nm).boxel_key, "Synuefe AA-A b")
    check("prefix n1=0", parse_name(nm).prefix, "Synuefe AA-A b")
    check("name_in_boxel n1=0", name_in_boxel("Synuefe AA-A b", 3), "Synuefe AA-A b3")
    check("name_in_boxel n1>0", name_in_boxel("Synuefe VA-I b2", 3), "Synuefe VA-I b2-3")
    check("invalid 'b-7' form rejected", parse_name("Synuefe AA-A b-7"), None)

    # Ground truth from the game: SystemAddress values out of real journals
    for nm, id64, sect in (("Synuefe XV-C d12", 422810994947, (39, 31, 18)),
                           ("Synuefe WG-J d10-78", 2690637597019, (39, 31, 18))):
        p = parse_name(nm)
        d = decode_id64(id64)
        check("%s n2" % nm, p.n2 if p else None, d["n2"])
        check("%s boxel" % nm, p.boxel if p else None, d["boxel"])
        check("%s id64" % nm, id64_from_parts(sect, p.mc, p.boxel, p.n2) if p else None, id64)
        check("%s round trip" % nm,
              make_name("Synuefe", d["mc"], d["boxel"], d["n2"]), nm)

    for mc in range(8):
        for bx in (0, 1, 63, 127 >> mc):
            b = (bx, (bx * 3) % (128 >> mc), (bx * 7) % (128 >> mc))
            nm = make_name("X", mc, b, 5)
            pp = parse_name(nm)
            if pp is None or pp.boxel != b or pp.mc != mc or pp.n2 != 5:
                fails += 1
                print("  [FAIL] round trip mc=%d boxel=%s -> %s" % (mc, b, nm))
    print("  [%s] round trip across all mass codes" % ("OK" if fails == 0 else "FAIL"))
    check("star_pos list", star_pos([1, 2.5, -3]), (1.0, 2.5, -3.0))
    check("star_pos extra items", star_pos((1.0, 2.0, 3.0, 4.0)), (1.0, 2.0, 3.0))
    check("star_pos text", star_pos("garbage"), None)
    check("star_pos short", star_pos([1.0, 2.0]), None)
    check("star_pos None in it", star_pos([1.0, None, 2.0]), None)
    check("star_pos nan", star_pos([1.0, float("nan"), 2.0]), None)
    check("star_pos bool", star_pos([True, 0.0, 0.0]), None)
    check("star_pos missing", star_pos(None), None)

    # 4.10: sector names computed (edts_pgnames), hand-authored sectors
    if _edts is not None:
        for idx, nm in (((39, 31, 18), "Synuefe"), ((39, 32, 18), "Wregoe"),
                        ((39, 31, 17), "Oochorrs"), ((38, 31, 18), "Synuefai"),
                        ((31, 31, 34), "Eol Prou"), ((40, 31, 15), "Pyurks")):
            check("computed name %s" % nm, computed_sector_name(idx), nm)
            check("computed index %s" % nm, computed_sector_index(nm), idx)
        check("HA name has no procedural index", computed_sector_index("Col 285 Sector"), None)
        check("nonsense has no index", computed_sector_index("Qqqq Xx"), None)
        check("Col 285 Sector is hand-authored", is_ha_sector("Col 285 Sector"), True)

        def labels_of(id64):
            d = decode_id64(id64)
            per = 128 >> d["mc"]
            g = tuple(s * per + b for s, b in zip(d["sector_idx"], d["boxel"]))
            return [boxel_key_of(n, d["mc"], b) for n, b in boxel_labels(g, d["mc"])]

        # real systems (game id64): a boxel deep inside a hand-authored
        # sphere has its name only; one its surface cuts has both
        check("inside NGC 2232 Sector", labels_of(2877225116705), ["NGC 2232 Sector KO-P b6"])
        check("inside NGC 2244 Sector (X1 case)", labels_of(87677669314),
              ["NGC 2244 Sector LO-W c16"])
        check("edge of NGC 2244 Sector: both labels",
              labels_of(10997434331), ["Pyurks FH-J d10", "NGC 2244 Sector GW-M d7"])
        check("procedural boxel: one label", labels_of(2690637597019)[:1], ["Synuefe WG-J d10"])
        reg = SectorRegistry()
        check("registry refuses a hand-authored name",
              reg.learn_from_id64("NGC 2232 Sector KO-P b6-1", 2877225116705), False)
        check("registry resolves an unknown sector by computing it",
              reg.resolve((40, 31, 15)), "Pyurks")
    # 4.10: physical slots - "Synuefe RH-U c19-1" (game id64), and its slot 0
    # which is a catalogue star (HIP) in the game
    mc, g, n2 = id64_slot(359669830314)
    check("slot of an id64: mass code and n2", (mc, n2), (2, 1))
    check("slot -> id64 round trip", id64_of_slot(mc, g, 1), 359669830314)
    check("slot 0 of the same boxel", id64_of_slot(mc, g, 0), 84791923370)
    check("id64 matches its position", id64_matches_position(
        359669830314, (553.625, -166.34375, -217.0)), True)
    check("id64 refuses a position elsewhere", id64_matches_position(
        359669830314, (0.0, 0.0, 0.0)), False)
    print("failures:", fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(_selftest())
