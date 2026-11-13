# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
boxelplan.py - completeness planner for SHBOXSEARCH v4
======================================================
Turns a sphere (centre, radius) into ONE prioritised work list.

Target kinds
------------
  NEW    known system inside the sphere, never visited
  GAP    n2 missing between 0 and a boxel's maximum
         -> almost certainly exists, but is in no database
  PROBE  n2 above the known maximum -> looking for the end of the boxel
  EMPTY  boxel with no known system at all, probe on "-0"
         -> ONE lookup decides whether the boxel holds any stars
  SCAN   visited, but the FSS sweep is incomplete
  DSS    body with a bio signal or of value, not yet mapped
  BIO    bio signal present, but no sample taken yet

The gap logic rests on this: within a boxel, n2 runs contiguously from 0.
That holds for mass codes a through g. Mass code h has culling gaps, which
is why h is off by default.

The commander checks a candidate in the galaxy map search:
  hit    -> set it as target -> FSDTarget / Status.json Destination
            -> the plugin picks it up automatically
  no hit -> press "not there" -> negative cache, never suggested again
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from procgen import (MASSCODES, boxel_center, boxel_index_of_coords,
                     boxel_intersects_sphere, boxel_key_of, boxel_labels,
                     boxel_size, boxel_prefix, boxels_in_sphere,
                     ha_regions_near, make_name, parse_name)
from sysdb import SystemDB

K_NEW = "new"
K_GAP = "gap"
K_PROBE = "probe"
K_EMPTY = "empty"
K_SCAN = "scan"
K_DSS = "dss"
K_BIO = "bio"
K_CHECK = "check"

# lower = handled earlier within the same distance band
PRIORITY = {K_NEW: 0, K_SCAN: 1, K_DSS: 2, K_BIO: 3,
            K_GAP: 4, K_PROBE: 5, K_EMPTY: 6, K_CHECK: 7}

# Two distinct activities:
#   FLIGHT - fly there, scan, map
#   PROBE  - check in the galaxy map search whether the name exists
FLIGHT_KINDS = (K_NEW, K_SCAN, K_DSS, K_BIO)
PROBE_KINDS = (K_GAP, K_PROBE, K_EMPTY)

# Names of the form "Sector XX-Y d12" are ordinary procgen names with n1 = 0
# (system n2=12 of boxel "XX-Y d") and are planned like any other since 4.1.
# K_CHECK stays defined so older UI code and exports keep working.

LABEL = {
    K_NEW: "known, not yet visited",
    K_GAP: "boxel gap - in no database",
    K_PROBE: "probe above boxel maximum",
    K_EMPTY: "empty probe - boxel unexplored",
    K_SCAN: "FSS sweep incomplete",
    K_DSS: "mapping outstanding",
    K_BIO: "bio sample outstanding",
    K_CHECK: "name without system number - verify first",
}


class Target:
    __slots__ = ("name", "kind", "dist", "dist_origin", "mc", "boxel_key", "n2",
                 "x", "y", "z", "uncertainty", "detail", "id64", "score")

    def __init__(self, name, kind, dist, mc=None, boxel_key=None, n2=None,
                 pos=(None, None, None), detail="", id64=None):
        self.name = name
        self.kind = kind
        self.dist = dist              # distance to the sphere centre
        self.dist_origin = dist       # distance to the commander, set later
        self.mc = mc
        self.boxel_key = boxel_key
        self.n2 = n2
        self.x, self.y, self.z = pos
        self.detail = detail
        self.id64 = id64
        self.score = 0.0
        self.uncertainty = (boxel_size(mc) * math.sqrt(3) / 2) if mc is not None else 0.0

    @property
    def is_speculative(self) -> bool:
        return self.kind in (K_GAP, K_PROBE, K_EMPTY)

    def __repr__(self):  # pragma: no cover
        return "<%s %s %.1fly>" % (self.kind, self.name, self.dist)


def set_origin(targets: List["Target"], origin: Sequence[float]) -> None:
    """(Re)compute the distance of every target from a given point."""
    o = tuple(origin)
    for t in targets:
        if t.x is not None:
            t.dist_origin = math.dist((t.x, t.y, t.z), o)
        else:
            t.dist_origin = t.dist


EXTERNAL_SOURCES = ("EDDiscovery", "Spansh", "EDSM")
_NEIGHBOURS = [(i, j, k)
               for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)
               if (i, j, k) != (0, 0, 0)]


class ProspectMap:
    """
    Where is an unprobed boxel worth a look?

    Two measurable signals, no guesswork:

    1. Neighbourhood density. The Stellar Forge places stars by mass density,
       so a boxel surrounded by populated boxels is far more likely to hold
       something than one in a void. Measured over the 26 adjacent boxels.
    2. Source disagreement. A system that only one of the three databases
       knows is a symptom of thin reporting - and thin reporting is exactly
       where undiscovered systems survive. Measured over the same neighbourhood.

    Both are observations from the data at hand, not a model of the galaxy.
    """

    def __init__(self, rows, masscodes: Sequence[int]):
        self.count: Dict[int, Dict[Tuple[int, int, int], int]] = {}
        self.thin: Dict[int, Dict[Tuple[int, int, int], int]] = {}
        for mc in masscodes:
            c: Dict[Tuple[int, int, int], int] = {}
            t: Dict[Tuple[int, int, int], int] = {}
            for r in rows:
                if r["x"] is None:
                    continue
                g = boxel_index_of_coords(r["x"], r["y"], r["z"], mc)
                c[g] = c.get(g, 0) + 1
                ext = {v for v in (r["sources"] or "").split(",") if v} \
                    & set(EXTERNAL_SOURCES)
                if len(ext) == 1:
                    t[g] = t.get(g, 0) + 1
            self.count[mc] = c
            self.thin[mc] = t

    def score(self, mc: int, gidx: Tuple[int, int, int]) -> float:
        """0 = void, higher = more promising. Roughly 0 .. 5."""
        c, t = self.count.get(mc, {}), self.thin.get(mc, {})
        filled = systems = thin = 0
        for d in _NEIGHBOURS:
            g = (gidx[0] + d[0], gidx[1] + d[1], gidx[2] + d[2])
            n = c.get(g, 0)
            if n:
                filled += 1
                systems += n
            thin += t.get(g, 0)
        if not filled:
            return 0.0
        fill_rate = filled / 26.0
        density = min(systems / 26.0, 2.0)
        underreport = min(thin / max(systems, 1), 1.0)
        return 2.5 * fill_rate + 1.0 * density + 1.5 * underreport


# H3 #7 (4.9): the formula above is a guess about which neighbourhood pays.
# What it actually paid is in the database: boxels no database knows where the
# game client proved a system (route plot, target selection, a jump) - hits -
# and boxels whose first system the galaxy map search ruled out - misses.
CLIENT_SOURCES = {"navroute", "fsdtarget", "destination", "journal", "scan", "startjump",
                  "fss", "inhabited", "carrier"}
NOT_CLIENT = set(EXTERNAL_SOURCES) | {"external"}
SCORE_BANDS = (1.0, 2.0, 3.0, 4.0)       # edges of the formula score
LEARN_WEIGHT = 20.0                       # outcomes a band needs to outweigh the formula
LEARN_MIN_HITS = 5                        # below this the formula alone orders the probes


def _wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


class ProspectCalibration:
    """
    How often a boxel nobody had in a database really held a system, per
    band of the formula score - per mass code, leaning on all mass codes
    where one is thin, and on the formula where both are thin.

    The formula says which neighbourhood is MORE promising, not how often it
    pays; so the outcomes are read relative to their own average:

        pooled = (hits + W * f) / (n + W)          f = mean formula chance
        prior  = pooled * p_formula / f            (no data: the formula)
        p_all  = (hits_band + W * prior) / (n_band + W)
        p_mc   = (hits_mc   + W * p_all) / (n_mc   + W)          W = 20
        score  = 5 * p_mc * f / pooled             (the formula's own scale)

    A band that paid better than the average climbs, one that paid worse
    drops; a band without outcomes keeps its formula score. Nothing changes
    before LEARN_MIN_HITS hits: misses alone say nothing about what pays.
    Counting only - no model. Bias, said openly: hits come from route plots
    and targets the commander picked, misses from galaxy map searches.
    """

    def __init__(self) -> None:
        self.cells: Dict[Tuple[Any, int], List[int]] = {}
        self.hits = 0
        self.n = 0
        self.sum_p0 = 0.0

    @staticmethod
    def band(raw: float) -> int:
        return sum(1 for e in SCORE_BANDS if raw >= e)

    @staticmethod
    def _p0(raw: float) -> float:
        return max(0.0, min(raw / 5.0, 1.0))

    def add(self, mc: int, raw: float, hit: bool) -> None:
        b = self.band(raw)
        for k in ((mc, b), ("*", b)):
            c = self.cells.setdefault(k, [0, 0])
            c[0] += 1 if hit else 0
            c[1] += 1
        self.hits += 1 if hit else 0
        self.n += 1
        self.sum_p0 += self._p0(raw)

    def outcomes(self) -> int:
        return self.n

    def active(self) -> bool:
        return self.hits >= LEARN_MIN_HITS

    def score(self, mc: int, raw: float) -> float:
        if not self.active():
            return raw
        f = self.sum_p0 / self.n
        if f <= 0:
            return raw
        pooled = (self.hits + LEARN_WEIGHT * f) / (self.n + LEARN_WEIGHT)
        b = self.band(raw)
        prior = min(1.0, pooled * self._p0(raw) / f)
        ha, na = self.cells.get(("*", b), (0, 0))
        pa = (ha + LEARN_WEIGHT * prior) / (na + LEARN_WEIGHT)
        hm, nm = self.cells.get((mc, b), (0, 0))
        pm = (hm + LEARN_WEIGHT * pa) / (nm + LEARN_WEIGHT)
        return 5.0 * pm * f / pooled

    def summary(self) -> List[Dict[str, Any]]:
        """Per band over all mass codes: outcomes, hits, rate, 95 % range."""
        out = []
        for b in range(len(SCORE_BANDS) + 1):
            h, n = self.cells.get(("*", b), (0, 0))
            lo = SCORE_BANDS[b - 1] if b else 0.0
            lo_r, hi_r = _wilson(h, n)
            out.append({"band": b, "from": lo,
                        "to": SCORE_BANDS[b] if b < len(SCORE_BANDS) else None,
                        "n": n, "hits": h, "rate": (h / n) if n else None,
                        "low": lo_r, "high": hi_r, "thin": n < LEARN_WEIGHT})
        return out


class Planner:
    def __init__(self, db: SystemDB):
        self.db = db

    # --------------------------------------------------------------------- api
    def build(self, center: Sequence[float], radius: float,
              masscodes: Sequence[int] = (0, 1, 2, 3),
              probe_depth: int = 2, include_empty: bool = True,
              include_tasks: bool = True, limit: int = 20000,
              origin: Optional[Sequence[float]] = None) -> Dict[str, object]:
        """
        origin is the commander's current position. Targets are ordered by
        distance from there, so when you are outside the sphere the queue
        leads you back in by the shortest hop.
        """

        center = tuple(center)
        absent = self.db.absent_set()
        known_rows = self.db.sphere(center, radius)
        known_names = {r["name"] for r in known_rows}
        visited = {r["name"] for r in known_rows if r["visited"]}
        boxel_n2 = self.db.boxel_n2_map()
        # neighbourhood reaches one boxel beyond the sphere
        margin = radius + boxel_size(max(masscodes) if masscodes else 0) * 2
        near_rows = self.db.sphere(center, margin)
        pmap = ProspectMap(near_rows, masscodes)
        # Names a physical boxel was really seen under (4.10): where the
        # surface of a hand-authored sector cuts a boxel, its systems carry
        # either label; a name some source or the journal gave with a
        # position is proof, so it is tried first.
        observed: Dict[Tuple[int, Tuple[int, int, int]], List[Tuple[str, Tuple[int, int, int]]]] = {}
        for r in near_rows:
            p = parse_name(r["name"])
            if p is None or r["x"] is None:
                continue
            g = boxel_index_of_coords(r["x"], r["y"], r["z"], p.mc)
            lab = (p.sector, tuple(p.boxel))
            lst = observed.setdefault((p.mc, g), [])
            if lab not in lst:
                lst.append(lab)
        ha_near = ha_regions_near(center, margin)
        boxel_score: Dict[str, float] = {}
        raw_score: Dict[str, Tuple[int, float]] = {}
        calib = ProspectCalibration()
        # boxels the game client proved a system in, and boxels some
        # database knows - a hit counts only where no database knew it
        client_boxels: Set[str] = set()
        db_boxels: Set[str] = set()
        for r in known_rows:
            p = parse_name(r["name"])
            if p is None:
                continue
            src = {v for v in (r["sources"] or "").split(",") if v}
            if src & NOT_CLIENT:
                db_boxels.add(p.boxel_key)
            elif src & CLIENT_SOURCES:
                client_boxels.add(p.boxel_key)

        targets: List[Target] = []
        counts = {k: 0 for k in PRIORITY}
        boxel_total = 0
        boxel_unknown = 0
        boxel_closed = 0
        boxel_open = 0
        boxel_untested = 0
        # Sample for the estimate: ONLY boxels we have probed to the end.
        # Boxels that merely appear in a database are a biased sample - they
        # are in there precisely because somebody found a system in them.
        probed: Dict[int, List[int]] = {}
        sectors_missing: Set[Tuple[int, int, int]] = set()

        # --- 1. known but unvisited systems ---------------------------------
        for r in known_rows:
            if r["visited"] or r["name"].startswith("#"):
                continue
            d = math.dist((r["x"], r["y"], r["z"]), center)
            p = parse_name(r["name"])
            kind = K_NEW
            targets.append(Target(r["name"], kind, d,
                                  mc=p.mc if p else None,
                                  boxel_key=p.boxel_key if p else None,
                                  n2=p.n2 if p else None,
                                  pos=(r["x"], r["y"], r["z"]),
                                  id64=r["id64"]))
            counts[kind] += 1

        # --- 2./3./4. boxel analysis ----------------------------------------
        for mc in masscodes:
            per_sector = 128 >> mc
            for gidx in boxels_in_sphere(mc, center, radius):
                boxel_total += 1
                # every label this physical boxel can carry: computed
                # (procedural sector, hand-authored spheres cutting it) and
                # seen; a seen label goes first
                labels = boxel_labels(gidx, mc, self.db.sectors.resolve, ha_near)
                seen = observed.get((mc, tuple(gidx)), [])
                labels = ([lab for lab in seen if lab in labels]
                          + [lab for lab in seen if lab not in labels]
                          + [lab for lab in labels if lab not in seen])
                if not labels:
                    sectors_missing.add(tuple(g // per_sector for g in gidx))
                    continue
                keys = [boxel_key_of(s, mc, b) for s, b in labels]
                bcenter = boxel_center(gidx, mc)
                bdist = math.dist(bcenter, center)
                key = keys[0]
                # the system number n2 is shared by all labels of a boxel
                known: Set[int] = set()
                for k in keys:
                    known |= boxel_n2.get(k, set())
                also = ("also named: " + ", ".join(boxel_prefix(k) for k in keys[1:])
                        ) if len(keys) > 1 else ""

                def variant(n2: int) -> Tuple[Optional[str], str, bool]:
                    """(name to probe, its boxel key, already known) - the
                    first label whose name is neither known nor marked
                    'not there'; None when every label was ruled out."""
                    for (s, b), k in zip(labels, keys):
                        nm = make_name(s, mc, b, n2)
                        if nm in known_names:
                            return None, k, True
                    for (s, b), k in zip(labels, keys):
                        nm = make_name(s, mc, b, n2)
                        if nm not in absent:
                            return nm, k, False
                    return None, key, False

                raw = pmap.score(mc, gidx)
                for k in keys:
                    raw_score[k] = (mc, raw)
                probe0, key0, _ = variant(0)
                if any(k in client_boxels for k in keys) and not any(k in db_boxels for k in keys):
                    calib.add(mc, raw, True)
                elif not known and probe0 is None:
                    calib.add(mc, raw, False)

                # closed only when every label's list was seen to its end
                closed = all(self.db.boxel_end(k) is not None for k in keys)
                if closed:
                    boxel_closed += 1
                    probed.setdefault(mc, []).append(len(known))
                elif known:
                    boxel_open += 1
                else:
                    boxel_untested += 1

                if not known:
                    boxel_unknown += 1
                    if include_empty and probe0 is not None:
                        targets.append(Target(probe0, K_EMPTY, bdist, mc, key0, 0, bcenter,
                                              detail=also))
                        counts[K_EMPTY] += 1
                    continue

                top = max(known)
                for n2 in range(0, top):
                    if n2 in known:
                        continue
                    nm, k, _ = variant(n2)
                    if nm is None:
                        continue
                    targets.append(Target(nm, K_GAP, bdist, mc, k, n2, bcenter, detail=also))
                    counts[K_GAP] += 1

                if not closed:
                    for d in range(1, probe_depth + 1):
                        nm, k, _ = variant(top + d)
                        if nm is None:
                            continue
                        targets.append(Target(nm, K_PROBE, bdist, mc, k, top + d, bcenter,
                                              detail=also))
                        counts[K_PROBE] += 1

        # --- 5. outstanding work in systems already visited -----------------
        if include_tasks:
            for t in self.db.unfinished_systems(center, radius):
                sc, bc = t["fss"]
                if bc and sc < bc:
                    targets.append(Target(t["name"], K_SCAN, t["dist"],
                                          detail="%d/%d bodies" % (sc, bc),
                                          id64=t["id64"]))
                    counts[K_SCAN] += 1
                if t["dss"]:
                    targets.append(Target(t["name"], K_DSS, t["dist"],
                                          detail="%d bodies: %s" % (
                                              len(t["dss"]), ", ".join(t["dss"][:3])),
                                          id64=t["id64"]))
                    counts[K_DSS] += 1
                if t["bio"]:
                    targets.append(Target(t["name"], K_BIO, t["dist"],
                                          detail="%d bodies: %s" % (
                                              len(t["bio"]), ", ".join(t["bio"][:3])),
                                          id64=t["id64"]))
                    counts[K_BIO] += 1

        for key, (mc, raw) in raw_score.items():
            boxel_score[key] = calib.score(mc, raw)

        set_origin(targets, origin if origin is not None else center)
        targets.sort(key=lambda t: (int(t.dist_origin // 5), PRIORITY[t.kind],
                                    t.dist_origin, t.n2 if t.n2 is not None else 0))
        if len(targets) > limit:
            targets = targets[:limit]

        flight = [t for t in targets if t.kind in FLIGHT_KINDS]
        # Probes are grouped per boxel: one galaxy map search shows the whole
        # boxel at once, so working boxel by boxel is far cheaper than hopping
        # between them in pure distance order.
        probe = [t for t in targets if t.kind in PROBE_KINDS]
        boxel_rank: Dict[str, float] = {}
        for t in probe:
            k = t.boxel_key or t.name
            if k not in boxel_rank or t.dist_origin < boxel_rank[k]:
                boxel_rank[k] = t.dist_origin
        # Effective cost per expected find: distance discounted by how
        # promising the neighbourhood is. A boxel twice as far but three times
        # as likely wins.
        def cost(key: str) -> float:
            return boxel_rank.get(key, 0.0) / (1.0 + boxel_score.get(key, 0.0))

        probe.sort(key=lambda t: (cost(t.boxel_key or t.name),
                                  t.boxel_key or "", t.n2 if t.n2 is not None else 0))
        for t in probe:
            t.score = boxel_score.get(t.boxel_key or "", 0.0)
        check = [t for t in targets if t.kind == K_CHECK]

        return {
            "center": center, "radius": radius,
            "targets": targets,
            "flight": flight, "probe": probe, "check": check,
            "counts": counts,
            "known": len(known_rows),
            "visited": len(visited),
            "boxel_total": boxel_total,
            "boxel_unexplored": boxel_unknown,
            "boxel_closed": boxel_closed,
            "boxel_open": boxel_open,
            "boxel_untested": boxel_untested,
            "probed_sample": probed,
            "boxel_score": boxel_score,
            "prospect_learning": calib.summary(),
            "prospect_outcomes": calib.outcomes(),
            "prospect_active": calib.active(),
            "masscodes": list(masscodes),
            "sectors_missing": sorted(sectors_missing),
        }

    # ------------------------------------------------------------- statistics
    def statistics(self, plan: Dict[str, object]) -> Dict[str, object]:
        """
        Turn a plan into an honest picture of the area:

          known      systems in the database inside the sphere
          visited    of those, actually flown to
          surveyed   visited, FSS complete and nothing left to map or sample
          certain    boxel gaps - they exist, no database has them
          estimate   statistical guess for boxels nobody has ever probed,
                     derived from the fill rate measured in this very sphere
          coverage   share of the estimated total that is already visited
        """
        db = self.db
        center, radius = plan["center"], plan["radius"]
        rows = db.sphere(center, radius)
        known = len(rows)
        visited = sum(1 for r in rows if r["visited"])

        surveyed = first_disc = 0
        bodies = mapped = 0
        for r in rows:
            if not r["visited"] or not r["id64"]:
                continue
            p = db.system_progress(r["id64"])
            bodies += p["scanned"]
            mapped += p["mapped"]
            first_disc += p["new_discoveries"]
            complete_fss = p["fss_complete"] or (
                p["body_count"] and p["scanned"] >= p["body_count"])
            if complete_fss and not p["dss_open"] and not p["bio_open"]:
                surveyed += 1

        certain = plan["counts"].get(K_GAP, 0)

        # Estimate for boxels nobody has ever probed. The sample is only the
        # boxels WE probed to the end - anything taken from a database is
        # biased, because it is listed precisely because a system was found
        # there. Below MIN_SAMPLE the estimate is refused rather than faked.
        MIN_SAMPLE = 20
        per_mc = {}
        probed = plan.get("probed_sample") or {}
        sample_total = 0
        for mc in plan.get("masscodes", []):
            samples = probed.get(mc) or []
            n = len(samples)
            sample_total += n
            nonempty = sum(1 for v in samples if v > 0)
            per_mc[MASSCODES[mc]] = {
                "probed": n,
                "nonempty": nonempty,
                "fill_rate": (nonempty / n) if n else 0.0,
                "avg_systems": (sum(samples) / nonempty) if nonempty else 0.0,
            }
        untested = plan.get("boxel_untested", 0)
        estimate = 0.0
        estimate_valid = sample_total >= MIN_SAMPLE
        if estimate_valid and untested:
            weight = sum(v["probed"] for v in per_mc.values()) or 1
            per_boxel = sum(v["fill_rate"] * v["avg_systems"] * v["probed"]
                            for v in per_mc.values()) / weight
            estimate = untested * per_boxel

        total_est = known + certain + estimate
        open_probes = len(plan["probe"])
        open_flight = len(plan["flight"])
        finished = (open_flight == 0 and open_probes == 0
                    and not plan["sectors_missing"])

        # How long a system actually takes, from the bodies we have on record.
        per_sys = []
        for r in rows:
            if not r["visited"] or not r["id64"]:
                continue
            n = len(db.bodies_of(r["id64"]))
            if n:
                per_sys.append(n)
        avg_bodies = (sum(per_sys) / len(per_sys)) if per_sys else 0.0

        cov = db.source_coverage(center, radius)
        scores = sorted((plan.get("boxel_score") or {}).items(),
                        key=lambda kv: -kv[1])
        hot = [(k, v) for k, v in scores if v >= 2.0]

        return {
            "source_coverage": cov,
            "prospect_learning": plan.get("prospect_learning") or [],
            "prospect_outcomes": plan.get("prospect_outcomes") or 0,
            "prospect_active": bool(plan.get("prospect_active")),
            "hot_boxels": hot[:10],
            "hot_count": len(hot),
            "avg_bodies": avg_bodies,
            "systems_measured": len(per_sys),
            "known": known,
            "visited": visited,
            "surveyed": surveyed,
            "certain_unknown": certain,
            "estimated_unknown": estimate,
            "estimate_valid": estimate_valid,
            "estimate_sample": sample_total,
            "total_estimate": total_est,
            "coverage_pct": (100.0 * visited / total_est) if total_est else 0.0,
            "survey_pct": (100.0 * surveyed / total_est) if total_est else 0.0,
            "bodies_scanned": bodies,
            "bodies_mapped": mapped,
            "first_discoveries": first_disc,
            "boxel_total": plan["boxel_total"],
            "boxel_closed": plan["boxel_closed"],
            "boxel_open": plan["boxel_open"],
            "boxel_untested": plan["boxel_untested"],
            "boxel_pct": (100.0 * plan["boxel_closed"] / plan["boxel_total"]
                          if plan["boxel_total"] else 0.0),
            "per_masscode": per_mc,
            "open_flight": open_flight,
            "open_probes": open_probes,
            "finished": finished,
        }

    @staticmethod
    def stats_table(st: Dict[str, object]) -> List[Tuple[str, List[Tuple[str, str]]]]:
        """
        The statistics as titled tables of (label, value).

        Only what actually informs the next decision is here. Percentages are
        clamped to 100: coverage is measured against an estimate, and an
        estimate that turns out low must not produce "112% explored".
        """
        def pct(v: float) -> str:
            return "%.1f%%" % max(0.0, min(100.0, v))

        cov = st.get("source_coverage") or {}
        out = []

        out.append(("Progress in this sphere", [
            ("Systems known", "%d" % st["known"]),
            ("Visited", "%d  (%s)" % (st["visited"], pct(st["coverage_pct"]))),
            ("Fully surveyed", "%d  (%s)" % (st["surveyed"], pct(st["survey_pct"]))),
            ("Still to fly", "%d" % st["open_flight"]),
            ("Still to check", "%d" % st["open_probes"]),
        ]))

        est = ("%.0f" % st["estimated_unknown"]) if st["estimate_valid"] else "?"
        total = ("~%.0f" % st["total_estimate"] if st["estimate_valid"]
                 else ">=%.0f" % st["total_estimate"])
        out.append(("Undiscovered systems", [
            ("Certain (boxel gaps)", "%d" % st["certain_unknown"]),
            ("Estimated further", est),
            ("Estimated total here", total),
            ("Boxels closed", "%d of %d  (%s)"
             % (st["boxel_closed"], st["boxel_total"], pct(st["boxel_pct"]))),
            ("Boxels never probed", "%d" % st["boxel_untested"]),
        ]))

        out.append(("What we contributed", [
            ("Bodies scanned", "%d" % st["bodies_scanned"]),
            ("Bodies mapped", "%d" % st["bodies_mapped"]),
            ("First discoveries", "%d" % st["first_discoveries"]),
        ]))

        if cov.get("total"):
            per = cov["per_source"]
            rows = [(k, "%d" % v) for k, v in per.items()]
            rows.append(("Only one source knows it",
                         "%d  (%s)" % (cov["by_count"].get(1, 0),
                                       pct(cov["disagreement_pct"]))))
            if cov["disagreement_pct"] >= 15:
                rows.append(("Verdict", "thin reporting - good odds here"))
            out.append(("Database coverage", rows))

        if st.get("prospect_outcomes"):
            rows = []
            for b in st.get("prospect_learning") or []:
                if not b["n"]:
                    continue
                band = ("score %.0f+" % b["from"] if b["to"] is None
                        else "score %.0f-%.0f" % (b["from"], b["to"]))
                rows.append((band, "%d of %d held a system (%.0f-%.0f%%)%s"
                             % (b["hits"], b["n"], 100 * b["low"], 100 * b["high"],
                                ", thin" if b["thin"] else "")))
            rows.append(("Used for", "probe order - thin bands lean on the formula"
                         if st.get("prospect_active") else
                         "nothing yet - the formula orders the probes until %d of them "
                         "held a system" % LEARN_MIN_HITS))
            out.append(("Prospecting learnt from your probes", rows))

        return out

    @staticmethod
    def stats_lines(st: Dict[str, object]) -> List[str]:
        """Compact rendering for the panel."""
        if st["estimate_valid"]:
            guess = "estimated %.0f more (sample %d boxels)" % (
                st["estimated_unknown"], st["estimate_sample"])
            total = "total ~%.0f" % st["total_estimate"]
        else:
            guess = "estimate needs %d more probed boxels" % (
                20 - st["estimate_sample"])
            total = "total >= %d" % st["total_estimate"]
        L = [
            "known %d | visited %d | fully surveyed %d"
            % (st["known"], st["visited"], st["surveyed"]),
            "certain unknown %d | %s | %s" % (st["certain_unknown"], guess, total),
            "coverage %.1f%% visited | %.1f%% surveyed"
            % (st["coverage_pct"], st["survey_pct"]),
            "boxels %d closed / %d open / %d never probed  (of %d, %.0f%% done)"
            % (st["boxel_closed"], st["boxel_open"], st["boxel_untested"],
               st["boxel_total"], st["boxel_pct"]),
            "bodies %d scanned, %d mapped | first discoveries %d"
            % (st["bodies_scanned"], st["bodies_mapped"], st["first_discoveries"]),
            "open: %d flight, %d probes" % (st["open_flight"], st["open_probes"]),
        ]
        cov = st.get("source_coverage") or {}
        if cov.get("total"):
            per = cov["per_source"]
            L.append("sources: " + ", ".join("%s %d" % (k, v) for k, v in per.items())
                     + " | only one knows it: %d (%.0f%%)"
                     % (cov["by_count"].get(1, 0), cov["disagreement_pct"]))
            if cov["disagreement_pct"] >= 15:
                L.append("thin reporting here - good odds for undiscovered systems")
        if st.get("systems_measured"):
            L.append("systems: %.1f bodies each on average (%d measured)"
                     % (st["avg_bodies"], st["systems_measured"]))
        if st.get("hot_count"):
            top = ", ".join("%s %.1f" % (k, v) for k, v in st["hot_boxels"][:3])
            L.append("promising boxels: %d  (top: %s)" % (st["hot_count"], top))
        if st["finished"]:
            L.append("AREA COMPLETE - safe to move to the next sphere")
        return L

    # ----------------------------------------------------------------- output
    @staticmethod
    def summary(plan: Dict[str, object]) -> str:
        c = plan["counts"]
        L = []
        L.append("sphere r=%.0f ly around (%.2f, %.2f, %.2f)"
                 % (plan["radius"], *plan["center"]))
        L.append("  known systems       : %d (visited %d)" % (plan["known"], plan["visited"]))
        L.append("  boxels in sphere    : %d (without a known system %d)"
                 % (plan["boxel_total"], plan["boxel_unexplored"]))
        L.append("  --- work queue ---")
        for k in sorted(c, key=lambda x: PRIORITY[x]):
            if c[k]:
                L.append("  %-8s %6d   %s" % (k, c[k], LABEL[k]))
        L.append("  flight targets      : %d" % len(plan["flight"]))
        L.append("  galaxy map probes   : %d" % len(plan["probe"]))
        L.append("  total               : %d" % len(plan["targets"]))
        if plan["sectors_missing"]:
            L.append("  ! %d sectors have no name mapping - no system is known there yet."
                     % len(plan["sectors_missing"]))
        return "\n".join(L)

    @staticmethod
    def boxel_prefixes(plan: Dict[str, object], limit: int = 100
                       ) -> List[Tuple[str, float, int]]:
        """
        Fastest manual route: one search prefix per boxel in the galaxy map.
        The result list shows every system of that boxel at once.
        """
        agg: Dict[str, List[float]] = {}
        for t in plan["targets"]:
            if not t.is_speculative or not t.boxel_key:
                continue
            e = agg.setdefault(t.boxel_key, [t.dist, 0])
            e[0] = min(e[0], t.dist)
            e[1] += 1
        rows = [(boxel_prefix(k), v[0], int(v[1])) for k, v in agg.items()]
        rows.sort(key=lambda r: r[1])
        return rows[:limit]

    @staticmethod
    def export_csv(plan: Dict[str, object], path: str) -> int:
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["kind", "system", "distance_ly", "masscode", "boxel", "n2",
                        "x", "y", "z", "uncertainty_ly", "detail"])
            for t in plan["targets"]:
                w.writerow([t.kind, t.name, round(t.dist, 2),
                            MASSCODES[t.mc] if t.mc is not None else "",
                            t.boxel_key or "", t.n2 if t.n2 is not None else "",
                            t.x if t.x is not None else "",
                            t.y if t.y is not None else "",
                            t.z if t.z is not None else "",
                            round(t.uncertainty, 1), t.detail])
        return len(plan["targets"])


# ---------------------------------------------------------------------------
# Route plotting as a probe: where to plot a NavRoute to
# ---------------------------------------------------------------------------
#
# Every route plotted in the game writes NavRoute.json with every hop - name,
# SystemAddress and exact position, straight from the game's own galaxy, also
# for systems that are in no database. The plugin harvests those hops. So
# the direction of a plot decides what it finds: a route whose straight line
# runs through boxels nobody has probed turns each hop into a fair chance of
# an unknown system - without a single galaxy map search.
#
# The commander plots the route himself (one action, nothing automated); this
# only picks a target worth plotting to.

def _seg_dist(p, a, b) -> Tuple[float, float]:
    """Distance of point p from segment a-b, and the position along it (0..1)."""
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    L2 = sum(v * v for v in ab)
    if L2 <= 0:
        return math.dist(p, a), 0.0
    t = max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / L2))
    q = [a[i] + t * ab[i] for i in range(3)]
    return math.dist(p, q), t


def bundled_probe_prefix(probe: Sequence["Target"], n: int = 5) -> Tuple[str, List[str]]:
    """
    One galaxy-map search prefix for several of the next probe boxels.

    Boxels of one sector, letter group and mass code differ only in their
    n1 digits ("Synuefe VA-I b2", "Synuefe VA-I b3"), so the key without its
    digits - "Synuefe VA-I b" - lists them all in one search (and the other
    b boxels of VA-I as well; the galaxy map sorts them by name). Looks at
    the next n distinct boxels of the queue and bundles those that share the
    first one's group; boxels of other groups are left for later - a shorter
    common prefix would list a whole sector. Grouping by the full key text
    keeps sector names of several words ("Col 285 Sector ...") intact.
    Returns (prefix, bundled boxel keys); ("", []) for an empty queue.
    """
    keys: List[str] = []
    for t in probe:
        k = getattr(t, "boxel_key", None)
        if k and k not in keys:
            keys.append(k)
            if len(keys) >= max(1, n):
                break
    if not keys:
        return "", []
    group = keys[0].rstrip("0123456789")
    bundle = [k for k in keys if k.rstrip("0123456789") == group]
    if len(bundle) == 1:
        return boxel_prefix(keys[0]), bundle
    return group, bundle


def _selftest() -> int:
    """python boxelplan.py - the probe bundle prefix."""
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    class T:
        def __init__(self, key):
            self.boxel_key = key

    q = [T("Synuefe VA-I b2"), T("Synuefe VA-I b2"), T("Synuefe VA-I b3"),
         T("Synuefe XV-C d"), T("Synuefe VA-I b17")]
    p, b = bundled_probe_prefix(q)
    check(p == "Synuefe VA-I b" and b == ["Synuefe VA-I b2", "Synuefe VA-I b3",
                                          "Synuefe VA-I b17"],
          "same sector, letters and mass code: one prefix for three boxels")
    p, b = bundled_probe_prefix([T("Col 285 Sector AB-C d12"), T("Col 285 Sector AB-C d13"),
                                 T("Col 285 Sector ZZ-Y d4")])
    check(p == "Col 285 Sector AB-C d" and len(b) == 2,
          "sector of several words stays whole; other letter group left out")
    p, b = bundled_probe_prefix([T("Synuefe XV-C d"), T("Synuefe VA-I b2")])
    check(p == "Synuefe XV-C d" and b == ["Synuefe XV-C d"],
          "nothing to bundle: the single boxel's own prefix")
    # H3 #7: calibration on own probe outcomes
    c = ProspectCalibration()
    check(c.score(0, 2.5) == 2.5 and c.score(1, 6.0) == 6.0,
          "no outcomes: the formula itself")
    for _ in range(70):
        c.add(0, 2.5, False)
    check(not c.active() and c.score(0, 2.5) == 2.5,
          "misses alone (as in the real survey, 0 of 131) change nothing")
    for _ in range(40):
        c.add(0, 3.5, False)                       # band 3 never paid in mass code a
    for _ in range(10):
        c.add(0, 0.5, True)                        # band 0 always did
    check(c.active() and c.score(0, 0.5) > c.score(0, 3.5),
          "measured outcomes turn the order round: %.2f vs %.2f"
          % (c.score(0, 0.5), c.score(0, 3.5)))
    check(abs(c.score(0, 1.5) - 1.5) < 1e-9,
          "a band without outcomes keeps its formula score")
    check(c.score(0, 3.5) < c.score(2, 3.5) < 3.5,
          "a mass code without outcomes leans on all mass codes, less strongly")
    sm = {x["band"]: x for x in c.summary()}
    check(sm[3]["n"] == 40 and sm[3]["hits"] == 0 and not sm[3]["thin"]
          and sm[0]["thin"] and sm[0]["rate"] == 1.0 and sm[1]["n"] == 0,
          "summary per band with thin marker")
    lo, hi = _wilson(0, 40)
    check(lo == 0.0 and 0.05 < hi < 0.1, "Wilson range of 0 of 40: 0-%.0f%%" % (100 * hi))
    check(ProspectCalibration.band(0.99) == 0 and ProspectCalibration.band(4.0) == 4,
          "band edges")
    p, b = bundled_probe_prefix([T("Synuefe VA-I b2"), T("Synuefe VA-I b3")], n=1)
    check(p == "Synuefe VA-I b2-" and len(b) == 1, "n=1: just the next boxel")
    check(bundled_probe_prefix([]) == ("", []), "empty queue")
    print("failures: %d" % fails)
    return fails


def corridor_targets(origin: Sequence[float], candidates: Sequence[Dict[str, object]],
                     empties: Sequence[Tuple[float, float, float, float]],
                     jump_range: float, limit: int = 3,
                     min_dist: float = 30.0, max_dist: float = 250.0
                     ) -> List[Dict[str, object]]:
    """
    Rank plot targets by unprobed boxels along the way.

    origin      current position
    candidates  [{"name", "x", "y", "z"}] - systems with exact coordinates
    empties     [(x, y, z, prospect_score)] - centres of boxels never probed
    jump_range  laden max jump, ly

    Score = sum over the boxels in a narrow corridor (at most 20 ly either
    side of the straight line) of (1 + prospect). A route that runs a long
    way through promising, unprobed ground wins; void boxels count little.

    How many systems a plot yields is set by the hops, not by the corridor:
    a route plotted as "economical" makes more, shorter jumps and therefore
    harvests more systems than a "fastest" one. The UI says so.
    """
    jr = max(10.0, float(jump_range or 0.0))
    half = min(20.0, max(10.0, jr * 0.5))
    o = tuple(origin)
    out = []
    for c in candidates:
        p = (float(c["x"]), float(c["y"]), float(c["z"]))
        d = math.dist(o, p)
        if d < min_dist or d > max_dist:
            continue
        jumps = max(1, math.ceil(d / jr))
        hit = 0
        value = 0.0
        # cheap box test first: only boxels inside the segment's bounding box
        # (plus the corridor width) can be close enough to the line
        lo = [min(o[k], p[k]) - half for k in range(3)]
        hi = [max(o[k], p[k]) + half for k in range(3)]
        for e in empties:
            if not (lo[0] <= e[0] <= hi[0] and lo[1] <= e[1] <= hi[1]
                    and lo[2] <= e[2] <= hi[2]):
                continue
            dist, t = _seg_dist(e[:3], o, p)
            if dist <= half and 0.02 < t < 0.98:
                hit += 1
                value += 1.0 + float(e[3] or 0.0)
        if not hit:
            continue
        out.append({"name": c["name"], "dist": d, "jumps": jumps,
                    "boxels": hit, "score": value, "pos": p})
    out.sort(key=lambda r: -r["score"])
    # do not offer three targets in the same direction
    picked: List[Dict[str, object]] = []
    for r in out:
        if all(_angle(o, r["pos"], q["pos"]) > 25.0 for q in picked):
            picked.append(r)
        if len(picked) >= limit:
            break
    return picked


def _angle(o, a, b) -> float:
    va = [a[i] - o[i] for i in range(3)]
    vb = [b[i] - o[i] for i in range(3)]
    na = math.sqrt(sum(v * v for v in va)) or 1.0
    nb = math.sqrt(sum(v * v for v in vb)) or 1.0
    cos = max(-1.0, min(1.0, sum(va[i] * vb[i] for i in range(3)) / (na * nb)))
    return math.degrees(math.acos(cos))


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
