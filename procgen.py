# -*- coding: utf-8 -*-
"""
procgen.py - Elite Dangerous procedural generation maths
========================================================
Name  <->  id64 (SystemAddress)  <->  boxel geometry

Verified against:
  Eol Prou RS-T d3-94 (Colonia) = id64 3238296097059 @ (-9530.5, -910.28125, 19808.125)
  All procgen systems from the supplied journals and JSON files - 0 mismatches.

No external dependencies. Python 3.8+.

Name format:   <Sector> <L1><L2>-<L3> <mc>[<n1>]-<n2>
  Example:     Synuefe   VA   - I      b  2   - 1
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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "GALAXY_ORIGIN", "SECTOR_SIZE", "MASSCODES",
    "ParsedName", "parse_name", "make_name", "boxel_size",
    "id64_from_parts", "decode_id64", "id64_from_name",
    "sector_index_of_coords", "boxel_index_of_coords",
    "boxel_corner", "boxel_center", "boxel_intersects_sphere",
    "boxels_in_sphere", "SectorRegistry", "parse_boxel_only",
]

# Lower corner of sector (0,0,0) in galactic coordinates
GALAXY_ORIGIN: Tuple[float, float, float] = (-49985.0, -40985.0, -24105.0)
SECTOR_SIZE: float = 1280.0
MASSCODES: str = "abcdefgh"

_NAME_RE = re.compile(
    r"^(?P<sector>.+?)\s+"
    r"(?P<l1>[A-Za-z])(?P<l2>[A-Za-z])-(?P<l3>[A-Za-z])\s+"
    r"(?P<mc>[A-Ha-h])(?P<n1>\d+)?-(?P<n2>\d+)$"
)


_BOXEL_ONLY_RE = re.compile(
    r"^(?P<sector>.+?)\s+"
    r"(?P<l1>[A-Za-z])(?P<l2>[A-Za-z])-(?P<l3>[A-Za-z])\s+"
    r"(?P<mc>[A-Ha-h])(?P<n1>\d+)?$"
)


def parse_boxel_only(name: str):
    """
    Recognise names of the form "Synuefe XV-C d12" - a boxel designation with
    no -n2 suffix. Frontier omits the running number when a boxel holds
    exactly one system, so such a name IS a real, flyable system and the
    boxel around it is complete: no -0, -1 ... exist there.

    Returns (sector, mass_code, boxel_index, boxel_key) or None.
    """
    if not name:
        return None
    m = _BOXEL_ONLY_RE.match(name.strip())
    if not m:
        return None
    g = m.groupdict()
    mc = MASSCODES.index(g["mc"].lower())
    n1 = int(g["n1"]) if g["n1"] else 0
    l1, l2, l3 = g["l1"].upper(), g["l2"].upper(), g["l3"].upper()
    boxel_id = (n1 * 17576 + (ord(l3) - 65) * 676
                + (ord(l2) - 65) * 26 + (ord(l1) - 65))
    boxel = (boxel_id & 0x7F, (boxel_id >> 7) & 0x7F, (boxel_id >> 14) & 0x7F)
    key = "%s %s%s-%s %s%s" % (g["sector"], l1, l2, l3, MASSCODES[mc],
                               str(n1) if n1 else "")
    return g["sector"], mc, boxel, key


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
        core += str(n1)
    return "%s %s-%d" % (sector, core, n2)


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


def id64_from_name(name: str, sector_idx: Sequence[int]) -> Optional[int]:
    """id64 from a name plus a known sector index."""
    p = parse_name(name)
    if p is None:
        return None
    return id64_from_parts(sector_idx, p.mc, p.boxel, p.n2)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

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

    # Boxel ohne n1 (BoxelID < 26^3)
    nm = make_name("Synuefe", 1, (0, 0, 0), 7)
    check("make_name mc b 0,0,0", nm, "Synuefe AA-A b-7")
    check("re-parse", parse_name(nm).boxel, (0, 0, 0))

    for mc in range(8):
        for bx in (0, 1, 63, 127 >> mc):
            b = (bx, (bx * 3) % (128 >> mc), (bx * 7) % (128 >> mc))
            nm = make_name("X", mc, b, 5)
            pp = parse_name(nm)
            if pp is None or pp.boxel != b or pp.mc != mc or pp.n2 != 5:
                fails += 1
                print("  [FAIL] round trip mc=%d boxel=%s -> %s" % (mc, b, nm))
    print("  [%s] round trip across all mass codes" % ("OK" if fails == 0 else "FAIL"))
    print("failures:", fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(_selftest())
