# -*- coding: utf-8 -*-
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
from typing import Dict, List, Optional, Sequence, Set, Tuple

from procgen import (MASSCODES, boxel_center, boxel_index_of_coords,
                     boxel_intersects_sphere, boxel_size,
                     boxels_in_sphere, make_name, parse_name)
from sysdb import Q_EXTERNAL, SystemDB

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

# Names of the form "Sector XX-Y d12" without -n2. Frontier omits the running
# number when a boxel holds exactly one system, so with exact coordinates
# behind it such a name IS a real system - and that boxel needs no probing.
import re as _re
_BOXEL_ONLY = _re.compile(r"^.+?\s+[A-Za-z][A-Za-z]-[A-Za-z]\s+[A-Ha-h]\d*$")

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
        pmap = ProspectMap(self.db.sphere(center, margin), masscodes)
        boxel_score: Dict[str, float] = {}

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
            if p is None and _BOXEL_ONLY.match(r["name"]):
                # A boxel designation without a running number. If the entry
                # carries exact coordinates from EDSM/Spansh/EDDiscovery or the
                # journal, somebody has actually been there - it is a real
                # system and a valid flight target. Only unverified entries
                # (legacy JSON, POI lists) are held back for checking.
                kind = K_NEW if (r["quality"] or 0) >= Q_EXTERNAL else K_CHECK
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
                sect_idx = tuple(g // per_sector for g in gidx)
                sect = self.db.sectors.name_of(sect_idx)
                if sect is None:
                    sectors_missing.add(sect_idx)
                    continue
                bx = tuple(g % per_sector for g in gidx)
                bcenter = boxel_center(gidx, mc)
                bdist = math.dist(bcenter, center)
                probe0 = make_name(sect, mc, bx, 0)
                key = parse_name(probe0).boxel_key
                known = boxel_n2.get(key, set())
                boxel_score[key] = pmap.score(mc, gidx)

                closed = self.db.boxel_end(key) is not None
                if closed:
                    boxel_closed += 1
                    probed.setdefault(mc, []).append(len(known))
                elif known:
                    boxel_open += 1
                else:
                    boxel_untested += 1

                if not known:
                    boxel_unknown += 1
                    if include_empty and probe0 not in absent:
                        targets.append(Target(probe0, K_EMPTY, bdist, mc, key, 0, bcenter))
                        counts[K_EMPTY] += 1
                    continue

                top = max(known)
                for n2 in range(0, top):
                    if n2 in known:
                        continue
                    nm = make_name(sect, mc, bx, n2)
                    if nm in absent or nm in known_names:
                        continue
                    targets.append(Target(nm, K_GAP, bdist, mc, key, n2, bcenter))
                    counts[K_GAP] += 1

                if not closed:
                    for k in range(1, probe_depth + 1):
                        nm = make_name(sect, mc, bx, top + k)
                        if nm in absent or nm in known_names:
                            continue
                        targets.append(Target(nm, K_PROBE, bdist, mc, key, top + k, bcenter))
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
        rows = [(k + "-", v[0], int(v[1])) for k, v in agg.items()]
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
