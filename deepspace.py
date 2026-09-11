# -*- coding: utf-8 -*-
"""
deepspace.py - fuel range and carrier staging for SHBOXSEARCH v4
================================================================
Three things that decide how far out you can operate:

1. SHIP FUEL - how many jumps are left before you must scoop. Out here that
   is the hard limit, not time.
2. TRITIUM - where the fleet carrier can refuel. Tritium is mined from icy
   rings, so an icy ring in the sphere is what makes a staging point viable.
3. CARRIER STAGING - given everything surveyed so far, where should the
   carrier go next? The answer has to satisfy all of: little overlap with
   ground already covered, plenty of unexplored volume, and tritium on site.

Every input is measured from the journal rather than assumed:

    Loadout        MaxJumpRange, FuelCapacity
    FSDJump        FuelUsed, FuelLevel, JumpDist
    Scan           Rings[].RingClass, StarType
    Status.json    Fuel.FuelMain

Standard library only.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "SCOOPABLE", "RING_TRITIUM", "FuelState", "ring_summary",
    "tritium_systems", "score_staging", "best_staging",
]

# The classic mnemonic: these star types can be scooped.
SCOOPABLE = frozenset("KGBFOAM")

# Tritium is mined from icy rings. Metallic and rocky rings carry other
# commodities but no tritium, so only icy rings make a carrier staging point.
RING_TRITIUM = "eRingClass_Icy"

RING_LABEL = {
    "eRingClass_Icy": "icy (tritium)",
    "eRingClass_Rocky": "rocky",
    "eRingClass_Metalic": "metallic",
    "eRingClass_MetalRich": "metal rich",
}


# ---------------------------------------------------------------------------
# Ship fuel
# ---------------------------------------------------------------------------

class FuelState:
    """
    How far the ship can go before it has to scoop.

    Consumption is strongly non-linear: Frontier's drive burns roughly
    `dist ** 2.7`, so a 64 ly jump costs hundreds of times what a 6 ly hop
    does. Averaging the last few jumps is therefore useless on its own - after
    a run of short hops it would claim thousands of jumps of range.

    Instead a curve `used = a * dist ** b` is fitted to the commander's own
    (JumpDist, FuelUsed) pairs in log space. On the test journals that gives
    b = 2.75, which matches the drive's documented fuel power of 2.6 to 2.8 -
    a good sign the fit is measuring the real thing. Range is then quoted for
    two cases: jumping at full range, and at the distance actually being flown.
    """

    FALLBACK_POWER = 2.75

    def __init__(self, capacity: float = 0.0, level: float = 0.0,
                 max_jump: float = 0.0,
                 jumps: Optional[List[Tuple[float, float]]] = None):
        self.capacity = capacity
        self.level = level
        self.max_jump = max_jump
        self.jumps: List[Tuple[float, float]] = list(jumps or [])  # (ly, tonnes)

    def add_jump(self, dist_ly: Optional[float], used_t: Optional[float]) -> None:
        try:
            d, u = float(dist_ly or 0.0), float(used_t or 0.0)
        except (TypeError, ValueError):
            return
        if d > 0.1 and u > 0.0:
            self.jumps.append((d, u))
            del self.jumps[:-60]

    # -- the fitted curve ---------------------------------------------------
    def _fit(self) -> Optional[Tuple[float, float]]:
        pts = [(d, u) for d, u in self.jumps if d > 0.5 and u > 0.0]
        if len(pts) < 4:
            return None
        xs = [math.log(d) for d, _ in pts]
        ys = [math.log(u) for _, u in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        if den < 1e-9:
            return None
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        if not (1.5 <= b <= 4.0):        # implausible fit, fall back
            return None
        return (math.exp(my - b * mx), b)

    def cost_of(self, dist_ly: float) -> Optional[float]:
        """Fuel for one jump of that length, in tonnes."""
        f = self._fit()
        if f is None:
            pts = [(d, u) for d, u in self.jumps if d > 0.5 and u > 0.0]
            if not pts:
                return None
            d0, u0 = pts[-1]
            return u0 * (dist_ly / d0) ** self.FALLBACK_POWER
        a, b = f
        return a * (dist_ly ** b)

    def jumps_at(self, dist_ly: float) -> Optional[int]:
        c = self.cost_of(dist_ly)
        if not c or c <= 0 or self.level <= 0:
            return None
        return int(self.level / c)

    @property
    def typical_jump(self) -> float:
        """The distance actually being flown lately."""
        pts = [d for d, _ in self.jumps[-15:]]
        return (sum(pts) / len(pts)) if pts else (self.max_jump or 0.0)

    @property
    def jumps_left(self) -> Optional[int]:
        """Worst case: jumping at maximum range."""
        return self.jumps_at(self.max_jump) if self.max_jump else None

    @property
    def range_left(self) -> Optional[float]:
        j = self.jumps_left
        return (j * self.max_jump) if (j is not None and self.max_jump) else None

    @property
    def pct(self) -> float:
        return (100.0 * self.level / self.capacity) if self.capacity else 0.0

    @property
    def samples(self) -> int:
        return len(self.jumps)

    def summary(self) -> str:
        if self.capacity <= 0:
            return "fuel: unknown"
        bits = ["fuel %.0f/%.0ft (%.0f%%)" % (self.level, self.capacity, self.pct)]
        jmax = self.jumps_left
        if jmax is None:
            bits.append("no jump data yet")
            return " | ".join(bits)
        bits.append("%d jumps at max %.0f ly" % (jmax, self.max_jump))
        typ = self.typical_jump
        if typ > 0.5 and abs(typ - self.max_jump) > 2.0:
            jt = self.jumps_at(typ)
            if jt is not None:
                bits.append("%d at your usual %.0f ly" % (jt, typ))
        f = self._fit()
        if f:
            bits.append("burn ~dist^%.1f (%d jumps)" % (f[1], self.samples))
        return " | ".join(bits)

    def warning(self) -> Optional[str]:
        """A short warning when fuel is getting tight, otherwise None."""
        j = self.jumps_left
        if j is None:
            return None
        if j <= 2:
            return "FUEL CRITICAL - %d full-range jumps left, scoop now" % j
        if j <= 5:
            return "fuel low - %d full-range jumps left, find a KGBFOAM star" % j
        return None


def is_scoopable(star_type: Optional[str]) -> bool:
    return bool(star_type) and star_type[0].upper() in SCOOPABLE


# ---------------------------------------------------------------------------
# Rings and tritium
# ---------------------------------------------------------------------------

def ring_summary(rings: Sequence[dict]) -> Dict[str, int]:
    """Count ring classes as written in a Scan event."""
    out: Dict[str, int] = {}
    for r in rings or []:
        cls = r.get("RingClass")
        if cls:
            out[cls] = out.get(cls, 0) + 1
    return out


def tritium_systems(db, center: Sequence[float], radius: float
                    ) -> List[Dict[str, object]]:
    """
    Systems inside the sphere with an icy ring - the carrier can refuel there.

    Ring mass is carried through because a bigger ring means a longer usable
    seam, which matters if the carrier is going to sit there a while.
    """
    out: List[Dict[str, object]] = []
    for row in db.sphere(center, radius):
        if not row["id64"]:
            continue
        icy = 0
        mass = 0.0
        for b in db.bodies_of(row["id64"]):
            try:
                if (b["ring_classes"] or "").find(RING_TRITIUM) >= 0:
                    icy += 1
                    mass += float(b["ring_mass"] or 0.0)
            except (KeyError, IndexError, TypeError):
                continue
        if icy:
            out.append({
                "name": row["name"],
                "id64": row["id64"],
                "pos": (row["x"], row["y"], row["z"]),
                "icy_rings": icy,
                "ring_mass": mass,
                "dist": math.dist((row["x"], row["y"], row["z"]), tuple(center)),
            })
    out.sort(key=lambda d: -d["ring_mass"])
    return out


# ---------------------------------------------------------------------------
# Carrier staging
# ---------------------------------------------------------------------------

def score_staging(db, candidate: Sequence[float], radius: float,
                  has_tritium: bool, known_here: int, unexplored: int,
                  exclude_id: Optional[int] = None) -> Dict[str, object]:
    """
    Rate one candidate position for the next sphere.

    Three things matter and they pull against each other:

      * overlap with what is already surveyed - wasted effort
      * unexplored volume - the reason to go at all
      * tritium on site - without it the carrier is stranded

    Tritium is treated as a hard gate rather than a weighting, because a
    staging point you cannot refuel at is not a staging point.
    """
    ov = db.sphere_overlap(candidate, radius, exclude_id=exclude_id)
    fresh = max(0.0, 100.0 - ov["volume_pct"]) / 100.0
    virgin = (unexplored / max(1, known_here + unexplored))
    score = 0.0 if not has_tritium else (2.0 * fresh + 1.5 * virgin)
    return {
        "pos": tuple(candidate),
        "score": score,
        "overlap_pct": ov["volume_pct"],
        "visited_here": ov["visited"],
        "known_here": ov["known"],
        "unexplored": unexplored,
        "has_tritium": has_tritium,
    }


def best_staging(db, planner, current: Sequence[float], radius: float,
                 masscodes: Sequence[int], max_hops: float = 0.0,
                 limit: int = 6) -> List[Dict[str, object]]:
    """
    Propose the next carrier position.

    Candidates are the tritium systems we already know about, taken from a
    search volume three spheres wide - far enough to leave the current ground
    behind, near enough that the carrier can get there. Each is scored, and
    only those with tritium survive.

    Deliberately conservative: it only ever proposes somewhere we have already
    seen an icy ring with our own eyes. Guessing at unvisited systems would
    risk sending the carrier somewhere it cannot refuel.
    """
    search_r = max(radius * 3.0, 150.0)
    if max_hops:
        search_r = min(search_r, max_hops)
    cands = tritium_systems(db, current, search_r)
    out: List[Dict[str, object]] = []
    for c in cands:
        if c["dist"] < radius * 0.75:
            continue            # too close, it would just repeat this sphere
        plan = planner.build(c["pos"], radius, masscodes=masscodes,
                             probe_depth=0, include_empty=False,
                             include_tasks=False)
        res = score_staging(db, c["pos"], radius, True,
                            plan["known"], plan["boxel_unexplored"])
        res["name"] = c["name"]
        res["dist"] = c["dist"]
        res["icy_rings"] = c["icy_rings"]
        res["ring_mass"] = c["ring_mass"]
        out.append(res)
    out.sort(key=lambda d: -d["score"])
    return out[:limit]


def staging_lines(rows: Sequence[Dict[str, object]]) -> List[str]:
    if not rows:
        return ["no tritium system known far enough out yet - "
                "scan icy rings as you go"]
    out = ["next carrier position (tritium on site):"]
    for r in rows:
        out.append("  %-26s %6.0f ly | %d icy ring%s | overlap %3.0f%% | "
                   "%d boxels unexplored | score %.2f"
                   % (str(r["name"])[:26], r["dist"], r["icy_rings"],
                      "" if r["icy_rings"] == 1 else "s", r["overlap_pct"],
                      r["unexplored"], r["score"]))
    return out
