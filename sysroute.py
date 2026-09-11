# -*- coding: utf-8 -*-
"""
sysroute.py - in-system route planning for SHBOXSEARCH v4
=========================================================
After arriving in a system, in which order should the bodies be flown?

Data basis
----------
Every `Scan` event carries a full set of Kepler elements:

    SemiMajorAxis, Eccentricity, OrbitalInclination, Periapsis,
    AscendingNode, MeanAnomaly, OrbitalPeriod, Parents, DistanceFromArrivalLS

Measured on real journals: all seven orbital elements present in 100% of scans,
Parents and DistanceFromArrivalLS in 98% (the exception is the primary star,
which sits at the origin anyway). That is enough to place every body in real
3D space rather than sorting by radial distance alone - two moons can both sit
at "1090 LS" and still be nowhere near each other.

Positions are resolved recursively through the Parents chain, so a moon is
placed relative to its planet and the planet relative to its star.

Cost model
----------
Supercruise time is dominated by acceleration and deceleration, not by cruise
speed, so it is strongly non-linear. The model here is

    t = ENTRY + k * sqrt(distance_ls)

with a hard floor, plus a fixed cost per drop-out. It is calibrated against
clean SupercruiseEntry -> SupercruiseExit segments from the commander's own
journals (see calibrate_from_journal), and falls back to defaults otherwise.

Honest limitation: absolute times are estimates. Measurements taken from real
journals scatter by more than a factor of five for the same distance, because
scanning, mapping and landing time is mixed in. The ORDER of targets, however,
barely depends on the exact constants - it depends on the geometry, which is
exact. Treat the minutes as a rough budget, not a promise.

Standard library only.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["Body", "Stop", "SystemRoute", "plan_route", "DEFAULT_MODEL",
           "CostModel", "group_label", "is_moon", "bodies_from_rows",
           "calibrate_from_journal", "shorten", "resolve_positions"]

LS_PER_METRE = 1.0 / 299792458.0

# Bodies worth a detailed surface scan
VALUABLE = {
    "Earthlike body", "Water world", "Ammonia world",
    "High metal content body", "Metal rich body",
}


class CostModel:
    """
    What a stop actually costs, in seconds.

    Two parts, because they behave completely differently:

    * TRAVEL - supercruise, dominated by acceleration, so entry + k*sqrt(d).
    * WORK - what you do once you arrive. A drive-by scan is seconds; a
      detailed surface scan is a couple of minutes; taking three biological
      samples is the better part of ten.

    Every constant can be measured from the commander's own journals rather
    than guessed, and each carries the sample count that backs it, so the
    panel can say how much the estimate is worth.
    """

    def __init__(self, entry: float = 40.0, k: float = 11.0,
                 dropout: float = 25.0, floor: float = 15.0,
                 samples: int = 0, dss: float = 150.0, bio: float = 205.0,
                 approach: float = 45.0, work_samples: int = 0):
        self.entry = entry            # spin-up before the ship really moves
        self.k = k                    # seconds per sqrt(light second)
        self.dropout = dropout        # cost of dropping out at the target
        self.floor = floor            # nothing is ever faster than this
        self.samples = samples        # measurements behind the travel model
        self.dss = dss                # one detailed surface scan
        self.bio = bio                # one biological sample, log to analyse
        self.approach = approach      # lining up and dropping to a body
        self.work_samples = work_samples

    def travel(self, distance_ls: float) -> float:
        if distance_ls <= 0.05:
            return self.floor
        return max(self.floor, self.entry + self.k * math.sqrt(distance_ls))

    def hop(self, distance_ls: float) -> float:
        return self.travel(distance_ls) + self.dropout

    def work(self, body: "Body") -> float:
        """Time on station at one body, from what it still needs."""
        t = 0.0
        if body.wants_dss:
            t += self.dss + self.approach
        if body.wants_bio:
            outstanding = max(1, body.sig_bio - body.organics)
            t += self.bio * outstanding + self.approach
        return t

    def as_dict(self) -> Dict[str, float]:
        return {"entry": round(self.entry, 1), "k": round(self.k, 2),
                "dropout": self.dropout, "floor": self.floor,
                "travel_samples": self.samples,
                "dss": round(self.dss), "bio": round(self.bio),
                "approach": round(self.approach),
                "work_samples": self.work_samples}


DEFAULT_MODEL = CostModel()


# ---------------------------------------------------------------------------
# Kepler
# ---------------------------------------------------------------------------

def _kepler_E(M: float, e: float, iters: int = 12) -> float:
    """Solve M = E - e sin E by Newton iteration."""
    E = M if e < 0.8 else math.pi
    for _ in range(iters):
        d = E - e * math.sin(E) - M
        denom = 1.0 - e * math.cos(E)
        if abs(denom) < 1e-12:
            break
        step = d / denom
        E -= step
        if abs(step) < 1e-12:
            break
    return E


def orbital_position(sma_m: float, ecc: float, inc_deg: float,
                     peri_deg: float, node_deg: float, mean_anom_deg: float,
                     period_s: Optional[float] = None,
                     seconds_since: float = 0.0) -> Tuple[float, float, float]:
    """
    Position relative to the parent, in light seconds.

    Angles are degrees as written by the journal. seconds_since advances the
    body along its orbit from the epoch of the scan; for planning within one
    session it is normally left at zero, because orbital periods run from days
    to years.
    """
    if not sma_m:
        return (0.0, 0.0, 0.0)
    e = max(0.0, min(0.999, ecc or 0.0))
    M = math.radians(mean_anom_deg or 0.0)
    if period_s and seconds_since:
        M += 2.0 * math.pi * (seconds_since / period_s)
    M = math.fmod(M, 2.0 * math.pi)

    E = _kepler_E(M, e)
    # position in the orbital plane
    xv = sma_m * (math.cos(E) - e)
    yv = sma_m * (math.sqrt(max(0.0, 1.0 - e * e)) * math.sin(E))

    w = math.radians(peri_deg or 0.0)
    O = math.radians(node_deg or 0.0)
    i = math.radians(inc_deg or 0.0)
    cw, sw = math.cos(w), math.sin(w)
    cO, sO = math.cos(O), math.sin(O)
    ci, si = math.cos(i), math.sin(i)

    x = (cw * cO - sw * ci * sO) * xv + (-sw * cO - cw * ci * sO) * yv
    y = (cw * sO + sw * ci * cO) * xv + (-sw * sO + cw * ci * cO) * yv
    z = (sw * si) * xv + (cw * si) * yv
    return (x * LS_PER_METRE, y * LS_PER_METRE, z * LS_PER_METRE)


# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------

class Body:
    """One body of a system, placed in 3D space."""

    __slots__ = ("body_id", "name", "short", "kind", "planet_class", "terraform",
                 "landable", "arrival_ls", "parent_id", "pos", "rel",
                 "scanned", "mapped", "was_discovered", "was_mapped",
                 "sig_bio", "sig_geo", "organics", "rings")

    def __init__(self, body_id: int, name: str, **kw):
        self.body_id = body_id
        self.name = name or ""
        self.short = self.name
        self.kind = kw.get("kind") or "Other"
        self.planet_class = kw.get("planet_class")
        self.terraform = kw.get("terraform")
        self.landable = bool(kw.get("landable"))
        self.arrival_ls = float(kw.get("arrival_ls") or 0.0)
        self.parent_id = kw.get("parent_id")
        self.rel = kw.get("rel") or (0.0, 0.0, 0.0)
        self.pos: Optional[Tuple[float, float, float]] = None
        self.scanned = bool(kw.get("scanned"))
        self.mapped = bool(kw.get("mapped"))
        self.was_discovered = kw.get("was_discovered")
        self.was_mapped = kw.get("was_mapped")
        self.sig_bio = int(kw.get("sig_bio") or 0)
        self.sig_geo = int(kw.get("sig_geo") or 0)
        self.organics = int(kw.get("organics") or 0)
        self.rings = bool(kw.get("rings"))

    # -- what is still to do here ------------------------------------------
    @property
    def wants_dss(self) -> bool:
        if self.mapped or self.kind != "Planet":
            return False
        return (self.sig_bio > 0
                or self.planet_class in VALUABLE
                or (self.terraform or "") == "Terraformable")

    @property
    def wants_bio(self) -> bool:
        return self.sig_bio > 0 and self.organics < self.sig_bio

    @property
    def has_work(self) -> bool:
        return self.wants_dss or self.wants_bio

    def work_label(self) -> str:
        bits = []
        if self.wants_dss:
            bits.append("DSS")
        if self.wants_bio:
            bits.append("bio x%d" % self.sig_bio)
        if self.was_discovered is False:
            bits.append("first")
        if self.planet_class in VALUABLE:
            bits.append(self.planet_class or "")
        elif (self.terraform or "") == "Terraformable":
            bits.append("terraformable")
        return ", ".join(b for b in bits if b)

    def __repr__(self):  # pragma: no cover
        return "<Body %s %s>" % (self.body_id, self.name)


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def resolve_positions(bodies: Dict[int, Body]) -> None:
    """
    Turn parent-relative orbits into absolute positions, recursively.

    Two things matter for correctness:

    * The origin is the ARRIVAL STAR, not the barycentre. In a binary system
      the star you drop out at orbits a barycentre that can sit thousands of
      light seconds away, so everything is shifted onto the arrival star at
      the end. Without that shift a binary system comes out wildly wrong.
    * If a body's parent is missing (partial scan data) it falls back to its
      arrival distance placed on one axis - crude, but it keeps such a body in
      the route instead of dropping it at the origin.
    """
    done: Dict[int, Tuple[float, float, float]] = {}

    def resolve(bid: int, depth: int = 0) -> Tuple[float, float, float]:
        if bid in done:
            return done[bid]
        b = bodies.get(bid)
        if b is None or depth > 8:
            return (0.0, 0.0, 0.0)
        done[bid] = (0.0, 0.0, 0.0)      # guard against orbital cycles
        if b.parent_id is None or b.parent_id not in bodies:
            base = (0.0, 0.0, 0.0)
            if b.parent_id is not None and b.rel == (0.0, 0.0, 0.0):
                base = (b.arrival_ls, 0.0, 0.0)
        else:
            base = resolve(b.parent_id, depth + 1)
        p = (base[0] + b.rel[0], base[1] + b.rel[1], base[2] + b.rel[2])
        done[bid] = p
        b.pos = p
        return p

    for bid in list(bodies):
        resolve(bid)

    for b in bodies.values():
        if b.pos is None:
            b.pos = (b.arrival_ls or 0.0, 0.0, 0.0)

    # --- shift the origin onto the arrival star ---------------------------
    anchor = None
    for b in bodies.values():
        if b.arrival_ls is not None and b.arrival_ls <= 0.01 and b.kind == "Star":
            if anchor is None or b.body_id < anchor.body_id:
                anchor = b
    if anchor is None:
        for b in sorted(bodies.values(), key=lambda x: x.body_id):
            if b.arrival_ls is not None and b.arrival_ls <= 0.01:
                anchor = b
                break
    if anchor is not None and anchor.pos and anchor.pos != (0.0, 0.0, 0.0):
        ox, oy, oz = anchor.pos
        for b in bodies.values():
            if b.pos:
                b.pos = (b.pos[0] - ox, b.pos[1] - oy, b.pos[2] - oz)

    # --- final sanity pass against the journal's own arrival distance -----
    for b in bodies.values():
        if not b.pos or b.arrival_ls is None or b.arrival_ls <= 1.0:
            continue
        r = math.sqrt(b.pos[0] ** 2 + b.pos[1] ** 2 + b.pos[2] ** 2)
        if r < 1e-6 or r > b.arrival_ls * 3.0 + 10.0 or r < b.arrival_ls / 3.0 - 10.0:
            # geometry disagrees with the game's own figure - trust the game,
            # but keep the direction if we have one
            if r > 1e-6:
                f = b.arrival_ls / r
                b.pos = (b.pos[0] * f, b.pos[1] * f, b.pos[2] * f)
            else:
                b.pos = (b.arrival_ls, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

_MOON_TOKEN = re.compile(r"^[a-z]$")


def group_label(body: Body, bodies: Optional[Dict[int, Body]] = None) -> str:
    """
    The planetary system a body belongs to: `2` for `2 d`, `AB 1` for `AB 1 f`.

    Derived from the NAME hierarchy, not from the parent chain. That is
    deliberate: moons frequently orbit an unnamed barycentre between
    themselves, and those barycentres are usually never scanned, so the
    parent chain has holes. Measured on real data, going by parent alone split
    ten moons of one planet into six separate "systems".

    Frontier names bodies strictly hierarchically - `<system> AB 1 d` is moon
    `d` of planet `AB 1` - so the name is the reliable source. Everything up
    to the first single lower-case token is the planetary system.
    """
    short = (body.short or body.name or "").strip()
    if not short:
        return "?"
    parts = short.split()
    keep = []
    for tok in parts:
        if _MOON_TOKEN.match(tok):
            break
        keep.append(tok)
    return " ".join(keep) if keep else short


def is_moon(body: Body) -> bool:
    """True when the name marks this as a moon rather than a planet."""
    short = (body.short or body.name or "").strip()
    parts = short.split()
    return bool(parts) and bool(_MOON_TOKEN.match(parts[-1]))


class Stop:
    __slots__ = ("body", "leg_ls", "leg_s", "cum_s", "work",
                 "group", "group_start", "is_moon", "work_s")

    def __init__(self, body: Body, leg_ls: float, leg_s: float, cum_s: float,
                 group: str = "", group_start: bool = False,
                 is_moon: bool = False, work_s: float = 0.0):
        self.work_s = work_s        # time spent at the body, not travelling
        self.body = body
        self.leg_ls = leg_ls
        self.leg_s = leg_s
        self.cum_s = cum_s
        self.work = body.work_label()
        self.group = group          # which planetary system this belongs to
        self.group_start = group_start   # first stop after switching system
        self.is_moon = is_moon


class SystemRoute:
    def __init__(self, system: str, stops: List[Stop], skipped: int,
                 model: CostModel):
        self.system = system
        self.stops = stops
        self.skipped = skipped
        self.model = model

    @property
    def total_s(self) -> float:
        return self.stops[-1].cum_s if self.stops else 0.0

    @property
    def total_ls(self) -> float:
        return sum(s.leg_ls for s in self.stops)

    @property
    def travel_s(self) -> float:
        return sum(s.leg_s for s in self.stops)

    @property
    def work_s(self) -> float:
        return sum(s.work_s for s in self.stops)

    @property
    def group_switches(self) -> int:
        return sum(1 for s in self.stops[1:] if s.group_start)

    def lines(self, limit: int = 0) -> List[str]:
        out = []
        stops = self.stops if not limit else self.stops[:limit]
        for i, s in enumerate(stops, 1):
            mark = ">>" if (s.group_start and i > 1) else "  "
            name = ("  " + s.body.short) if s.is_moon else s.body.short
            out.append("%s%2d. %-30s %7.0f LS  +%4.0f min  %s"
                       % (mark, i, name[:30], s.leg_ls, s.leg_s / 60.0, s.work))
        if limit and len(self.stops) > limit:
            out.append("    ... %d more" % (len(self.stops) - limit))
        return out

    def groups(self) -> List[Tuple[str, List[Stop]]]:
        """The route as clusters: (planetary system label, its stops in order)."""
        out: List[Tuple[str, List[Stop]]] = []
        for s in self.stops:
            if s.group_start or not out:
                out.append((s.group, [s]))
            else:
                out[-1][1].append(s)
        return out

    def bounds(self) -> Tuple[float, float, float, float]:
        """(min_x, max_x, min_z, max_z) over all stops, for drawing a map."""
        xs = [s.body.pos[0] for s in self.stops if s.body.pos] + [0.0]
        zs = [s.body.pos[2] for s in self.stops if s.body.pos] + [0.0]
        return (min(xs), max(xs), min(zs), max(zs))

    def summary(self) -> str:
        if not self.stops:
            return "%s: nothing left to do here" % self.system
        return ("%s: %d stops in %d planetary systems, %.0f LS, about %.0f min "
                "(%.0f travel + %.0f on station)%s"
                % (self.system, len(self.stops), self.group_switches + 1,
                   self.total_ls, self.total_s / 60.0,
                   self.travel_s / 60.0, self.work_s / 60.0,
                   " | %d bodies need nothing" % self.skipped if self.skipped else ""))


# What counts as "needs doing". Any combination can be active at once.
F_ALL = "all"            # every body, always
F_UNDISCOVERED = "new"   # nobody has scanned it before - the real prize
F_UNMAPPED = "unmapped"  # never surface-scanned by anyone
F_SIGNALS = "signals"    # carries biological or geological signals
F_LANDABLE = "landable"  # you can set down on it
F_VALUABLE = "valuable"  # ELW, water world, ammonia, terraformable
F_RINGS = "rings"        # has rings
F_OUTSTANDING = "todo"   # DSS or bio still open by our own records

ALL_FILTERS = (F_ALL, F_UNDISCOVERED, F_UNMAPPED, F_SIGNALS, F_LANDABLE,
               F_VALUABLE, F_RINGS, F_OUTSTANDING)

FILTER_LABEL = {
    F_ALL: "every body",
    F_UNDISCOVERED: "not discovered by anyone yet",
    F_UNMAPPED: "not surface-scanned by anyone yet",
    F_SIGNALS: "has bio or geo signals",
    F_LANDABLE: "landable",
    F_VALUABLE: "high value (ELW, water, ammonia, terraformable)",
    F_RINGS: "has rings",
    F_OUTSTANDING: "DSS or bio still open",
}


def body_matches(b: Body, filters: Sequence[str]) -> bool:
    """Does this body qualify under the active filters?"""
    if not filters or F_ALL in filters:
        return b.kind in ("Planet", "Star")
    if F_UNDISCOVERED in filters and b.was_discovered is False:
        return True
    if F_UNMAPPED in filters and b.kind == "Planet" and b.was_mapped is False:
        return True
    if F_SIGNALS in filters and (b.sig_bio > 0 or b.sig_geo > 0):
        return True
    if F_LANDABLE in filters and b.landable:
        return True
    if F_VALUABLE in filters and (b.planet_class in VALUABLE
                                  or (b.terraform or "") == "Terraformable"):
        return True
    if F_RINGS in filters and b.rings:
        return True
    if F_OUTSTANDING in filters and b.has_work:
        return True
    return False


def plan_route(system: str, bodies: Dict[int, Body],
               model: CostModel = DEFAULT_MODEL,
               start: Sequence[float] = (0.0, 0.0, 0.0),
               only_work: bool = True,
               group_moons: bool = True,
               filters: Optional[Sequence[str]] = None) -> SystemRoute:
    """
    Order the bodies into a short route.

    Nearest neighbour to build a first tour, then 2-opt to iron out crossings.
    For the 10-40 stops a system typically has, that lands within a few percent
    of optimal in well under a millisecond - and unlike an exact solver it
    degrades gracefully on the rare 60-body system.

    group_moons keeps a planet and its moons together as one cluster. They sit
    within a few light seconds of each other, so splitting them up is always a
    loss, and clustering shrinks the problem the optimiser has to solve.
    """
    resolve_positions(bodies)

    if filters:
        targets = [b for b in bodies.values() if body_matches(b, filters)]
    else:
        targets = [b for b in bodies.values()
                   if (b.has_work if only_work else b.kind in ("Planet", "Star"))]
    skipped = len(bodies) - len(targets)
    if not targets:
        return SystemRoute(system, [], skipped, model)

    # --- cluster by parent so moons stay with their planet -----------------
    if group_moons:
        clusters: Dict[str, List[Body]] = {}
        for b in targets:
            clusters.setdefault(group_label(b), []).append(b)
        groups = list(clusters.values())
    else:
        groups = [[b] for b in targets]

    def gpos(g: List[Body]) -> Tuple[float, float, float]:
        n = float(len(g))
        return (sum(b.pos[0] for b in g) / n,
                sum(b.pos[1] for b in g) / n,
                sum(b.pos[2] for b in g) / n)

    pts = [gpos(g) for g in groups]

    # --- nearest neighbour --------------------------------------------------
    order: List[int] = []
    left = set(range(len(groups)))
    cur = tuple(start)
    while left:
        j = min(left, key=lambda i: _dist(cur, pts[i]))
        order.append(j)
        left.discard(j)
        cur = pts[j]

    # --- 2-opt --------------------------------------------------------------
    def tour_cost(o: List[int]) -> float:
        c = 0.0
        prev = tuple(start)
        for i in o:
            c += model.hop(_dist(prev, pts[i]))
            prev = pts[i]
        return c

    if len(order) > 3:
        best = tour_cost(order)
        improved = True
        rounds = 0
        while improved and rounds < 40:
            improved = False
            rounds += 1
            for i in range(len(order) - 1):
                for j in range(i + 2, len(order)):
                    cand = order[:i + 1] + order[i + 1:j + 1][::-1] + order[j + 1:]
                    c = tour_cost(cand)
                    if c < best - 1e-6:
                        order, best, improved = cand, c, True
                        break
                if improved:
                    break

    # --- expand clusters and cost the legs ---------------------------------
    stops: List[Stop] = []
    cur = tuple(start)
    cum = 0.0
    last_group = None
    for gi in order:
        g = sorted(groups[gi], key=lambda b: (is_moon(b), b.short or "",
                                              b.body_id))
        for b in g:
            d = _dist(cur, b.pos)
            sec = model.hop(d)
            work_s = model.work(b)
            cum += sec + work_s
            grp = group_label(b)
            stops.append(Stop(b, d, sec, cum, group=grp,
                              group_start=(grp != last_group),
                              is_moon=is_moon(b), work_s=work_s))
            last_group = grp
            cur = b.pos
    return SystemRoute(system, stops, skipped, model)


# ---------------------------------------------------------------------------
# Calibration from the commander's own journals
# ---------------------------------------------------------------------------

def _median(xs: List[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0.0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _trimmed(xs: List[float], lo: float = 0.1, hi: float = 0.9) -> List[float]:
    """
    Drop the tails before averaging.

    Journal timings are contaminated in one direction only - the commander
    walks away, takes a screenshot, fights an interdiction - so the upper tail
    is noise while the lower tail is real. Trimming both and taking the median
    of what remains is far more stable than a mean.
    """
    xs = sorted(xs)
    n = len(xs)
    if n < 5:
        return xs
    return xs[int(n * lo):max(int(n * hi), int(n * lo) + 1)]


def calibrate_work_from_journal(dss: List[float], bio: List[float],
                                approach: List[float],
                                base: "CostModel") -> "CostModel":
    """
    Measure how long the work at a body actually takes.

    Unlike supercruise timings these are clean: a detailed surface scan is
    bracketed by arrival and SAAScanComplete, and a biological sample by its
    own Log and Analyse events, with nothing else that can stretch them except
    the commander pausing.
    """
    n = len(dss) + len(bio) + len(approach)
    if n < 4:
        return base
    return CostModel(
        entry=base.entry, k=base.k, dropout=base.dropout, floor=base.floor,
        samples=base.samples,
        dss=_median(_trimmed(dss)) or base.dss,
        bio=_median(_trimmed(bio)) or base.bio,
        approach=_median(_trimmed(approach)) or base.approach,
        work_samples=n)


def calibrate_from_journal(segments: Iterable[Tuple[float, float]],
                           base: CostModel = DEFAULT_MODEL) -> CostModel:
    """
    segments: (distance_ls, seconds) from CLEAN SupercruiseEntry -> Exit pairs,
    i.e. with no scanning, mapping or landing in between.

    Fitted on the lower envelope: any measurement inflated by the commander
    doing something else is noise in one direction only, so the fastest
    observations are the honest ones. Needs at least 8 segments; below that the
    defaults are kept, because a bad fit is worse than a generic one.
    """
    pts = [(d, t) for d, t in segments if d > 1.0 and 5.0 < t < 3600.0]
    if len(pts) < 8:
        return base

    # keep the fastest third - those are the ones without side activity
    pts.sort(key=lambda p: p[1] / max(math.sqrt(p[0]), 1e-6))
    keep = pts[:max(8, len(pts) // 3)]

    best = None
    for k in [x / 2.0 for x in range(8, 60)]:          # 4.0 .. 30.0
        for entry in range(0, 90, 5):
            rss = sum((entry + k * math.sqrt(d) - t) ** 2 for d, t in keep)
            if best is None or rss < best[0]:
                best = (rss, k, entry)
    _, k, entry = best
    return CostModel(entry=float(entry), k=float(k), dropout=base.dropout,
                     floor=base.floor, samples=len(keep),
                     dss=base.dss, bio=base.bio, approach=base.approach,
                     work_samples=base.work_samples)


# ---------------------------------------------------------------------------
# Building bodies from the database
# ---------------------------------------------------------------------------

def bodies_from_rows(rows: Iterable) -> Dict[int, Body]:
    """Build the body map from sysdb `bodies` rows."""
    out: Dict[int, Body] = {}
    for r in rows:
        rel = (0.0, 0.0, 0.0)
        try:
            if r["sma"]:
                rel = orbital_position(r["sma"], r["ecc"] or 0.0,
                                       r["inc"] or 0.0, r["peri"] or 0.0,
                                       r["node"] or 0.0, r["mean_anom"] or 0.0)
        except (KeyError, IndexError, TypeError):
            pass
        b = Body(r["body_id"], r["name"] or "",
                 kind=r["kind"], planet_class=r["planet_class"],
                 terraform=r["terraform"], landable=r["landable"],
                 arrival_ls=_get(r, "arrival_ls"), parent_id=_get(r, "parent_id"),
                 rel=rel, scanned=r["scanned"], mapped=r["mapped"],
                 was_discovered=r["was_discovered"], was_mapped=r["was_mapped"],
                 sig_bio=r["sig_bio"], sig_geo=r["sig_geo"], organics=r["organics"])
        out[b.body_id] = b
    return out


def _get(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def shorten(name: str, system: str) -> str:
    """`Synuefe VC-J b42-3 1 a` -> `1 a`. The primary star keeps a label."""
    if system and name and name.startswith(system):
        rest = name[len(system):].strip()
        return rest if rest else "(main star)"
    return name or "?"
