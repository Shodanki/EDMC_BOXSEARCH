# -*- coding: utf-8 -*-
"""
biopredict.py - which genera to expect on a body, learned from your own finds
=============================================================================
Before a DSS probe the game only says "2 biological signals". Which genera
those are decides whether a landing is worth it - biology pays several hundred
times more per unit of effort than mapping (README section 20).

This module does NOT ship a rule table copied from elsewhere. It learns, from
the bodies you have actually sampled (ScanOrganic -> species, stored since
4.1), the conditions each genus has been seen under:

    atmosphere type   - the strongest single predictor
    planet class
    surface gravity   - range in g
    surface temperature - range in K

and compares a not-yet-probed body against those envelopes. The result is a
ranked list of genera with how many of your own finds back each one. It gets
better with every sample you take, and it says how thin its evidence is
rather than pretending to certainty.

Once a DSS probe has run the game names the genera itself (SAASignalsFound
"Genuses"); the plugin then shows those instead of a prediction.

Plain Python, no EDMC imports.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

G = 9.80665          # journal SurfaceGravity is m/s^2

# Minimum distance between two samples of one species before the game
# accepts the next one ("clonal colony range"), in metres. Community-known
# values, not published by Frontier - check them in game; the overlay shows
# the measured distance next to them so a wrong value is easy to spot.
COLONY_RANGE_M = {
    "Aleoida": 150, "Bacterium": 500, "Cactoida": 300, "Clypeus": 150,
    "Concha": 150, "Electricae": 1000, "Fonticulua": 500, "Frutexa": 150,
    "Fumerola": 100, "Fungoida": 300, "Osseus": 800, "Recepta": 150,
    "Stratum": 500, "Tubus": 800, "Tussock": 200,
    # sampleable since the Nomad update; 100 m community value, consistent
    # with own samples 2026-11-05 (accepted at 102 m on HIP 31189 A 1 d)
    "Brain Trees": 100,
}


def surface_distance_m(lat1: float, lon1: float, lat2: float, lon2: float,
                       radius_m: float) -> float:
    """Great-circle distance on a body of the given radius (haversine)."""
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(a)))
GRAV_TOL = 0.15      # +-15 % around the observed gravity range
TEMP_TOL = 15.0      # +-15 K around the observed temperature range


def _atmo(row: Any) -> str:
    v = row["atmo_type"] if row["atmo_type"] else ""
    return v if v and v != "None" else "none"


class GenusEnvelope:
    __slots__ = ("genus", "n", "atmos", "classes", "g_min", "g_max",
                 "t_min", "t_max", "species")

    def __init__(self, genus: str):
        self.genus = genus
        self.n = 0
        self.atmos: Dict[str, int] = {}
        self.classes: Dict[str, int] = {}
        self.g_min = self.t_min = float("inf")
        self.g_max = self.t_max = float("-inf")
        self.species: Dict[str, int] = {}

    def add(self, atmo: str, pclass: str, g: Optional[float], t: Optional[float],
            species: str) -> None:
        self.n += 1
        self.atmos[atmo] = self.atmos.get(atmo, 0) + 1
        self.classes[pclass] = self.classes.get(pclass, 0) + 1
        if g is not None:
            self.g_min, self.g_max = min(self.g_min, g), max(self.g_max, g)
        if t is not None:
            self.t_min, self.t_max = min(self.t_min, t), max(self.t_max, t)
        if species:
            self.species[species] = self.species.get(species, 0) + 1

    def score(self, atmo: str, pclass: str, g: Optional[float],
              t: Optional[float]) -> float:
        """0 = ruled out by what we have seen; otherwise roughly 0 .. 1."""
        if atmo not in self.atmos:
            return 0.0                        # never seen in this atmosphere
        s = 0.4 + 0.2 * (self.atmos[atmo] / self.n)
        if pclass in self.classes:
            s += 0.15
        if g is not None and self.g_min <= self.g_max:
            lo, hi = self.g_min * (1 - GRAV_TOL), self.g_max * (1 + GRAV_TOL)
            s += 0.15 if lo <= g <= hi else -0.25
        if t is not None and self.t_min <= self.t_max:
            lo, hi = self.t_min - TEMP_TOL, self.t_max + TEMP_TOL
            s += 0.1 if lo <= t <= hi else -0.25
        return max(0.0, min(1.0, s))


class BioModel:
    def __init__(self) -> None:
        self.genera: Dict[str, GenusEnvelope] = {}
        self.bodies = 0

    @classmethod
    def learn(cls, rows: Iterable[Any]) -> "BioModel":
        """rows: sysdb `bodies` rows (needs bio_species, atmo_type, ...)."""
        m = cls()
        for r in rows:
            raw = r["bio_species"]
            if not raw:
                continue
            try:
                found = json.loads(raw)
            except ValueError:
                continue
            g = (r["gravity"] / G) if r["gravity"] is not None else None
            t = r["temp_k"]
            atmo, pclass = _atmo(r), r["planet_class"] or "?"
            m.bodies += 1
            for sp in found:
                genus = sp.get("genus") or ""
                if not genus:
                    continue
                env = m.genera.get(genus)
                if env is None:
                    env = m.genera[genus] = GenusEnvelope(genus)
                env.add(atmo, pclass, g, t, sp.get("species") or "")
        return m

    def predict(self, row: Any, limit: int = 4) -> List[Tuple[str, float, int]]:
        """[(genus, score 0..1, finds backing it)] best first, score > 0 only."""
        g = (row["gravity"] / G) if row["gravity"] is not None else None
        atmo, pclass = _atmo(row), row["planet_class"] or "?"
        out = []
        for env in self.genera.values():
            s = env.score(atmo, pclass, g, row["temp_k"])
            if s > 0.3:
                out.append((env.genus, s, env.n))
        out.sort(key=lambda x: (-x[1], -x[2]))
        return out[:limit]

    def hint(self, row: Any) -> str:
        """
        Short text for the route list and the overlay.

        After a DSS probe the genera are known - those are shown as they are.
        Before it, the prediction, marked with '?'.
        """
        if not (row["sig_bio"] or 0):
            return ""
        known = row["genuses"]
        if known:
            return ", ".join(x.strip() for x in known.split(",") if x.strip())
        if not self.genera:
            return ""
        pred = self.predict(row, limit=3)
        if not pred:
            return "unknown here"
        return ", ".join("%s?" % genus for genus, _s, _n in pred)

    def summary(self) -> str:
        if not self.genera:
            return "bio model: no samples yet - analyse a few organisms first"
        top = sorted(self.genera.values(), key=lambda e: -e.n)[:5]
        return ("bio model from %d sampled bodies, %d genera (%s)"
                % (self.bodies, len(self.genera),
                   ", ".join("%s %d" % (e.genus, e.n) for e in top)))


def validate(rows: List[Any]) -> Dict[str, float]:
    """
    Leave-one-out check on our own data: hide one body, learn from the rest,
    see whether its real genera come out on top. Honest measure of how much
    the prediction is worth today.
    """
    sampled = [r for r in rows if r["bio_species"]]
    hits = total = top1 = 0
    for i, r in enumerate(sampled):
        model = BioModel.learn(sampled[:i] + sampled[i + 1:])
        real = {sp.get("genus") for sp in json.loads(r["bio_species"])}
        pred = [g for g, _s, _n in model.predict(r, limit=3)]
        total += len(real)
        hits += len(real & set(pred))
        if pred and pred[0] in real:
            top1 += 1
    return {"bodies": len(sampled),
            "recall_top3": (hits / total) if total else 0.0,
            "top1_right": (top1 / len(sampled)) if sampled else 0.0}
