# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
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

    Loadout        MaxJumpRange, FuelCapacity, UnladenMass, the FSD module
    Cargo          Count (the ship's hold)
    FSDJump        FuelUsed, FuelLevel, JumpDist
    Scan           Rings[].RingClass, StarType
    Status.json    Fuel.FuelMain

Standard library only.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "SCOOPABLE", "RING_TRITIUM", "FuelState", "fsd_power", "mass_tier", "ring_summary",
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

# The fuel power of a frame shift drive by its size. The game's drive burns
# fuel = l * (dist * mass / optimal mass) ** power, so with the mass the
# power is the only shape constant. Measured on the developer's journals
# (SK2, 17.11.2026, fit over dist * mass): size 5 2.45 (n = 48), size 7
# 2.75 (n = 71, both the normal and the SCO drive), size 8 SCO Mk II 2.50
# (n = 56); sizes 2-4 and 6 follow the same steps. Only a prior: from 4
# jumps on, the ship's own fit wins.
FSD_POWER = {2: 2.0, 3: 2.15, 4: 2.3, 5: 2.45, 6: 2.6, 7: 2.75, 8: 2.5}
_FSD_SIZE = re.compile(r"int_hyperdrive(?:_overcharge)?_size(\d)_class", re.I)
MASS_TIER_T = 50.0       # a refit that changes the unladen mass by this is another ship


def fsd_power(item: Optional[str]) -> Optional[float]:
    """The fuel power of an FSD module (Loadout Item), None when unknown."""
    m = _FSD_SIZE.search(item or "")
    return FSD_POWER.get(int(m.group(1))) if m else None


def mass_tier(unladen: Optional[float]) -> Optional[int]:
    """The unladen-mass step a ship's fuel history belongs to (50 t steps)."""
    try:
        u = float(unladen or 0.0)
    except (TypeError, ValueError):
        return None
    return int(round(u / MASS_TIER_T)) if u > 0 else None


class FuelState:
    """
    How far the ship can go before it has to scoop.

    Consumption is strongly non-linear: Frontier's drive burns roughly
    `dist ** 2.7`, so a 64 ly jump costs hundreds of times what a 6 ly hop
    does. Averaging the last few jumps is therefore useless on its own - after
    a run of short hops it would claim thousands of jumps of range.

    Since 5.0 (SK2) the curve is `used = a * (dist * mass) ** b`, fitted in
    log space on the ship's own jumps, mass = unladen mass + fuel before the
    jump + cargo. The mass matters: a Panther Mk II that hauls 1,200 t
    scattered by 32 % around a curve over the distance alone and by 0-12 %
    with the mass; an Explorer NX by 3 % and 0.1-0.7 % (17.11.2026, own
    journals). The history is kept per commander, ship and unladen-mass step.
    With fewer than 4 jumps the power comes from the FSD (fsd_power), and
    without any mass (old data) the curve over the distance alone is used as
    up to 4.12. Range is then quoted for two cases: jumping at full range,
    and at the distance actually being flown.
    """

    FALLBACK_POWER = 2.75
    MIN_FIT = 4

    def __init__(self, capacity: float = 0.0, level: float = 0.0,
                 max_jump: float = 0.0,
                 jumps: Optional[List[Tuple[float, ...]]] = None):
        self.capacity = capacity
        self.level = level
        self.max_jump = max_jump
        # (ly, tonnes) or (ly, tonnes, mass before the jump)
        self.jumps: List[Tuple[float, ...]] = [tuple(j) for j in jumps or []]
        # the jumps belong to one ship of one commander: another ship (or
        # the other commander's) burns differently - mixing them made the
        # fit claim a Caspian at 68 ly needs 29 t a jump (11.11.2026)
        self.ship: Any = None
        self._by_ship: Dict[Any, List[Tuple[float, ...]]] = {}
        self.unladen = 0.0        # Loadout UnladenMass (hull and modules, empty tanks)
        self.cargo = 0.0          # tonnes in the hold (Cargo, Vessel Ship)
        self.fsd: Optional[str] = None     # the FSD module, for the prior power
        # SK2: a reset of the model, per ship: jumps before it are not learned
        self.since: Dict[Any, float] = {}

    def set_ship(self, key: Any, unladen: Optional[float] = None) -> bool:
        """Switch to the jump history of this ship (commander, ShipID) and,
        with the Loadout's unladen mass, its mass step; the previous ship's
        history is kept for when it comes back. Without a mass (LoadGame)
        the same ship keeps its step. True when the ship changed."""
        if key is None:
            return False
        tier = mass_tier(unladen)
        if tier is None:
            if self.ship is not None and tuple(self.ship[:len(key)]) == tuple(key):
                return False
            full = tuple(key)
        else:
            full = tuple(key) + (tier,)
            self.unladen = float(unladen)
        if full == self.ship:
            return False
        if self.ship is not None:
            self._by_ship[self.ship] = self.jumps
        self.ship = full
        self.jumps = list(self._by_ship.get(full, []))
        return True

    def feed(self, e: Dict[str, Any], cmdr: Any = None, ts: Optional[float] = None) -> bool:
        """
        One journal event for the fuel model (SK2): Loadout (ship, mass
        step, FSD, tank, range), LoadGame (ship), Cargo of the ship (hold)
        and FSDJump (the jump with its mass, the level after). True when a
        jump was learnt. The plugin and the journal replay use the same.
        """
        v = e.get("event")
        if v == "Loadout":
            self._loadout(e, cmdr)
        elif v == "LoadGame" and e.get("ShipID") is not None:
            self.set_ship((cmdr, e.get("ShipID")))
        elif v == "Cargo" and e.get("Vessel", "Ship") == "Ship" and e.get("Count") is not None:
            self.cargo = float(e["Count"])
        elif v == "FSDJump":
            learnt = False
            if e.get("FuelUsed") is not None:
                learnt = self.add_jump(e.get("JumpDist"), e.get("FuelUsed"),
                                       self.jump_mass(e.get("FuelUsed"), e.get("FuelLevel")), ts)
            if e.get("FuelLevel") is not None:
                self.level = float(e["FuelLevel"])
            return learnt
        return False

    def _loadout(self, e: Dict[str, Any], cmdr: Any) -> None:
        """Loadout: ship and mass step, FSD, tank size, jump range."""
        if e.get("ShipID") is not None:
            self.set_ship((cmdr, e.get("ShipID")), e.get("UnladenMass"))
        for m in e.get("Modules") or []:
            if m.get("Slot") == "FrameShiftDrive":
                self.fsd = m.get("Item")
        if e.get("MaxJumpRange"):
            self.max_jump = float(e["MaxJumpRange"])
        fc = e.get("FuelCapacity")
        cap = fc.get("Main") if isinstance(fc, dict) else fc
        if cap:
            self.capacity = float(cap)

    def jump_mass(self, used_t: Optional[float], level_after: Optional[float]) -> Optional[float]:
        """The ship's mass when it jumped: unladen + fuel before + cargo,
        None without an unladen mass."""
        try:
            if self.unladen <= 0 or level_after is None or float(level_after) < 0:
                return None
            return self.unladen + float(level_after) + float(used_t or 0.0) + max(0.0, float(self.cargo or 0.0))
        except (TypeError, ValueError):
            return None

    @property
    def mass_now(self) -> Optional[float]:
        """The mass now (unladen + tank + cargo), None without an unladen mass."""
        return self.jump_mass(0.0, self.level) if self.level and self.level > 0 else None

    def add_jump(self, dist_ly: Optional[float], used_t: Optional[float],
                 mass_t: Optional[float] = None, ts: Optional[float] = None) -> bool:
        """Remember the fuel one jump used (the last 60 jumps), with the
        ship's mass before it when known. A jump from before the ship's
        model was reset (ts < since) is not learned. True when learnt."""
        try:
            d, u = float(dist_ly or 0.0), float(used_t or 0.0)
            m = float(mass_t) if mass_t else None
        except (TypeError, ValueError):
            return False
        cut = self.since.get(self.ship)
        if cut is not None and ts is not None and ts < cut:
            return False
        if d > 0.1 and u > 0.0:
            self.jumps.append((d, u, m) if m else (d, u))
            del self.jumps[:-60]
            return True
        return False

    def reset(self, ts: float) -> None:
        """Forget what the current ship has learnt; jumps before ts stay
        unlearnt when the journals are read again (keep `since`)."""
        self.since[self.ship] = float(ts)
        self.jumps = []

    # -- the fitted curve ---------------------------------------------------
    def _points(self) -> Tuple[List[Tuple[float, float]], bool]:
        """(x, used) for the fit: x = dist * mass when at least MIN_FIT jumps
        carry a mass, else dist alone. True when it is the mass."""
        massed = [(j[0] * j[2], j[1]) for j in self.jumps
                  if len(j) > 2 and j[2] and j[0] > 0.5 and j[1] > 0.0]
        if len(massed) >= self.MIN_FIT:
            return massed, True
        return [(j[0], j[1]) for j in self.jumps if j[0] > 0.5 and j[1] > 0.0], False

    def _fit(self) -> Optional[Tuple[float, float]]:
        fit = self._fit_full()
        return (fit[0], fit[1]) if fit else None

    def _fit_full(self) -> Optional[Tuple[float, float, bool, float, int]]:
        """(a, b, with mass, rms scatter as a factor - 1, n), None below
        MIN_FIT jumps or for an implausible power."""
        pts, massed = self._points()
        if len(pts) < self.MIN_FIT:
            return None
        xs = [math.log(x) for x, _ in pts]
        ys = [math.log(u) for _, u in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        if den < 1e-9:
            return None
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        if not (1.5 <= b <= 4.0):        # implausible fit, fall back
            return None
        a = my - b * mx
        rms = math.sqrt(sum((y - a - b * x) ** 2 for x, y in zip(xs, ys)) / n)
        return (math.exp(a), b, massed, math.exp(rms) - 1.0, n)

    def prior_power(self) -> float:
        """The power without a fit: from the FSD, else FALLBACK_POWER."""
        return fsd_power(self.fsd) or self.FALLBACK_POWER

    def learned(self) -> Dict[str, Any]:
        """What the model stands on, for the panel and the FIS: source
        ("fit", "prior" or "none"), power, mass in the curve, scatter in %,
        and n, the jumps it learnt from."""
        f = self._fit_full()
        if f is not None:
            return {"source": "fit", "power": round(f[1], 3), "mass": f[2],
                    "spread_pct": round(100.0 * f[3], 1), "n": f[4]}
        return {"source": "prior" if self.jumps else "none", "power": self.prior_power(),
                "mass": False, "spread_pct": None, "n": len(self.jumps)}

    def cost_of(self, dist_ly: float, mass_t: Optional[float] = None) -> Optional[float]:
        """Fuel for one jump of that length, in tonnes, at mass_t (default:
        the mass now)."""
        f = self._fit_full()
        m = mass_t or self.mass_now
        if f is None:
            return self._cost_prior(dist_ly, m)
        a, b, massed = f[0], f[1], f[2]
        if not massed:
            return a * (dist_ly ** b)
        if not m:
            ms = [j[2] for j in self.jumps if len(j) > 2 and j[2]]
            m = sum(ms) / len(ms)
        return a * ((dist_ly * m) ** b)

    def _cost_prior(self, dist_ly: float, mass_t: Optional[float]) -> Optional[float]:
        """Below MIN_FIT jumps: the last jump scaled by the prior power, with
        the mass when both are known."""
        pts = [j for j in self.jumps if j[0] > 0.5 and j[1] > 0.0]
        if not pts:
            return None
        last = pts[-1]
        p = self.prior_power()
        if len(last) > 2 and last[2] and mass_t:
            return last[1] * ((dist_ly * mass_t) / (last[0] * last[2])) ** p
        return last[1] * (dist_ly / last[0]) ** p

    def jumps_at(self, dist_ly: float) -> Optional[int]:
        """How many jumps of dist_ly the fuel in the tank lasts, or None
        without data."""
        c = self.cost_of(dist_ly)
        if not c or c <= 0 or self.level <= 0:
            return None
        return int(self.level / c)

    @property
    def typical_jump(self) -> float:
        """The distance actually being flown lately."""
        pts = [j[0] for j in self.jumps[-15:]]
        return (sum(pts) / len(pts)) if pts else (self.max_jump or 0.0)

    @property
    def jumps_left(self) -> Optional[int]:
        """Worst case: jumping at maximum range."""
        return self.jumps_at(self.max_jump) if self.max_jump else None

    @property
    def range_left(self) -> Optional[float]:
        """Light years the tank lasts at the longest jump, or None."""
        j = self.jumps_left
        return (j * self.max_jump) if (j is not None and self.max_jump) else None

    @property
    def pct(self) -> float:
        """Fuel in the tank, in percent of its capacity."""
        return (100.0 * self.level / self.capacity) if self.capacity else 0.0

    @property
    def samples(self) -> int:
        """How many jumps the fuel model has learnt from."""
        return len(self.jumps)

    def summary(self) -> str:
        """One line for the panel: fuel, jumps and range left."""
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
        lm = self.learned()
        if lm["source"] == "fit":
            bits.append("burn ~%s^%.2f, ±%.1f%% (learned from %d jumps)"
                        % ("(dist*mass)" if lm["mass"] else "dist", lm["power"], lm["spread_pct"], lm["n"]))
        else:
            bits.append("burn ~dist^%.2f from the FSD (%d of %d jumps to learn)"
                        % (lm["power"], lm["n"], self.MIN_FIT))
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
    """True for the star classes a fuel scoop works at (KGBFOAM)."""
    return bool(star_type) and star_type[0].upper() in SCOOPABLE


# ---------------------------------------------------------------------------
# F1: where to scoop at the latest along a plotted route
# ---------------------------------------------------------------------------

SCOOP_RESERVE = 0.15     # at most this share of the tank is kept back ...
# ... and otherwise one jump in hand: the dearest jump of the route


def scoop_plan(fs: FuelState, hops: Sequence[Tuple[str, Optional[str], float]],
               here: Optional[Tuple[str, Optional[str]]] = None,
               reserve_frac: float = SCOOP_RESERVE) -> Optional[Dict[str, Any]]:
    """
    F1: along a plotted multi-jump route, the star at which you must scoop
    AT THE LATEST so you never run dry.

    hops: the jumps still to fly, in order - (system, star class, jump ly).
    here: (system, star class) where you are now; a scoopable star here is
    a refuel point before the first jump.

    The fuel per jump comes from the commander's own fitted curve
    (FuelState.cost_of), the start from the current tank. A scoopable star
    (KGBFOAM) is a refuel point; scooping there is assumed to fill the tank.
    Walking the route, whenever the next jump would leave less than the
    reserve (fuel for the dearest jump of the route, at most SCOOP_RESERVE
    of the tank - one jump in hand for the model's error), the LAST refuel
    point passed since
    the last fill becomes a "scoop here at the latest" mark and the walk
    goes on from there with a full tank. No refuel point left -> stranded.

    Separately, every stretch between two refuel points (or to the end)
    that needs more than a full tank is a gap - no scooping can bridge it,
    the route has to be plotted differently.

    Returns None without a tank size or fuel model, else
      jumps, latest [{n, name, star_class}] (n = jumps flown when you are
      there, 0 = here), gaps [{from, to, need, cap}], stranded {n, name} or
      None (hard: not even the jump itself, else only the reserve), arrive
      (t left at the end with the marked stops), ok (no stop
      needed at all), reserve (t).
    """
    cap = float(fs.capacity or 0.0)
    if cap <= 0 or not hops:
        return None
    costs: List[float] = []
    for _name, _cls, d in hops:
        c = fs.cost_of(float(d or 0.0)) if d else 0.0
        if c is None:
            return None
        costs.append(max(0.0, c))
    n = len(hops)
    reserve = min(cap * reserve_frac, max(costs))
    names = [here[0] if here else None] + [h[0] for h in hops]
    classes = [here[1] if here else None] + [h[1] for h in hops]
    point = [is_scoopable(c) for c in classes]      # refuel possible at position p

    latest: List[Dict[str, Any]] = []
    stranded = None
    lvl = min(float(fs.level or 0.0), cap)
    last = 0 if point[0] else None                  # latest refuel point since the last fill
    used_at = -1
    i = 0
    while i < n:
        if lvl - costs[i] < reserve:
            if last is None or last == used_at:
                stranded = {"n": i + 1, "name": names[i + 1], "hard": lvl < costs[i]}
                break
            latest.append({"n": last, "name": names[last], "star_class": classes[last]})
            used_at = last
            lvl = cap - sum(costs[last:i])
            if lvl - costs[i] < reserve:
                stranded = {"n": i + 1, "name": names[i + 1], "hard": lvl < costs[i]}
                break
        lvl -= costs[i]
        i += 1
        if point[i]:
            last = i
    gaps = []
    marks = [p for p in range(n + 1) if point[p]]
    for a, b in zip(marks, marks[1:] + [n]):
        need = sum(costs[a:b])
        if b > a and need > cap:
            gaps.append({"from": a + 1, "to": b, "need": round(need, 1), "cap": round(cap, 1)})
    return {"jumps": n, "latest": latest, "gaps": gaps, "stranded": stranded,
            "arrive": None if stranded else round(max(0.0, lvl), 1),
            "ok": not latest and stranded is None, "reserve": round(reserve, 1)}


def scoop_line(plan: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """One overlay line for the plan: (text, level 'ok' | 'warn' | 'alert')."""
    if not plan:
        return None
    if plan["stranded"]:
        s = plan["stranded"]
        return ("FUEL %s by jump %d - plot via scoop stars"
                % ("OUT" if s.get("hard") else "LOW", s["n"]), "alert")
    if plan["gaps"]:
        g = plan["gaps"][0]
        return ("NO SCOOP STAR jumps %d-%d: %.0f t > tank" % (g["from"], g["to"], g["need"]), "alert")
    if plan["latest"]:
        m = plan["latest"][0]
        where = "here" if m["n"] == 0 else "jump %d/%d" % (m["n"], plan["jumps"])
        more = " (+%d)" % (len(plan["latest"]) - 1) if len(plan["latest"]) > 1 else ""
        return ("SCOOP at the latest %s %s%s" % (where, m["star_class"] or "", more), "warn")
    return ("FUEL OK for %d jumps (~%.0f t left)" % (plan["jumps"], plan["arrive"] or 0), "ok")


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
    """The best carrier positions with tritium on site as text lines, or a hint
    when none is known yet."""
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
