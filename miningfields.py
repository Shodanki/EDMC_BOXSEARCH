# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.1.0: the mining fields, rated and predicted - shared by the plugin's
overlay (SP2, a ring hotspot as target) and the FIS (MINING, PLANET INFO).
Plain Python, no EDMC, no Tk; moved here from the FIS's fieldrating.py
(MP3) and fieldodds.py (MP4) so both sides count the same way.

MP3 - a field is a ring and the material mostly refined there. From the
commander's own laser-mining sessions:

- purity: how many of the prospected rocks held that material at all, and
  its mean share in those;
- prospectors per good rock: prospector limpets launched for every rock
  that held at least the commander's typical share of that material (the
  median over all their rocks of it - tritium and platinum differ);
- by-catch: what else was refined there, in tonnes and share.

Rated against the commander's own average for that material: "good" when a
field needs clearly fewer prospectors per good rock (GOOD_RATIO), "poor"
clearly more (POOR_RATIO), else "fair"; a material mined in one field only
is "fair".

MP4 - the chance that a field turns out good (not "poor") before mining
there, learnt from the rated fields, from what a ring is known by before
the first shot: ring class, the reserve level of its body, a hotspot of the
material and overlapping hotspots (known once the ring was mapped with the
DSS), the material. Naive Bayes with Laplace counts (+1); each class counted
only over the fields where that feature was known, over the values seen so
far (a feature alike in every rated field stays neutral). A feature unknown
for a ring, or a value never seen in a rated field yet, is left out. Below
MIN_FIELDS rated fields there is no number. Counting - no AI; read only.
"""

from __future__ import annotations

import calendar
import json
import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

__all__ = ["runs", "rate_fields", "ring_features", "features", "Odds", "samples", "verdict", "reality",
           "odds_for", "mat_key"]

GOOD_RATIO = 0.8             # prospectors per good rock against the material's average
POOR_RATIO = 1.25
RING_RESET = ("FSDJump", "Location", "Docked", "SupercruiseEntry")
GAP_S = 30 * 60              # as the FIS's mining sessions
EVENTS = ("ProspectedAsteroid", "MiningRefined", "LaunchDrone", "AsteroidCracked")
VEHICLE_OUT = ("LaunchSRV", "LaunchVessel")
VEHICLE_IN = ("DockSRV", "DockVessel")
# what a journal reader needs to keep for the fields (plus the ring and session borders)
NEEDED = EVENTS + VEHICLE_OUT + VEHICLE_IN + RING_RESET + ("SupercruiseExit",)

POOR = "poor"
MIN_FIELDS = 3             # rated fields before a chance is given
THIN_FIELDS = 10           # below this the chance is shown dim
LIKELY = 0.65              # >= likely good, <= 1 - LIKELY likely poor
FEATURES = ("cls", "reserve", "spot", "overlap", "mat")

Row = Dict[str, Any]
Sample = Tuple[Dict[str, Optional[str]], int]


def parse_ts(stamp: Any) -> Optional[float]:
    """A journal timestamp as Unix time, or None."""
    if not isinstance(stamp, str) or len(stamp) < 19:
        return None
    try:
        return float(calendar.timegm((int(stamp[0:4]), int(stamp[5:7]), int(stamp[8:10]), int(stamp[11:13]),
                                      int(stamp[14:16]), int(stamp[17:19]), 0, 0, 0)))
    except ValueError:
        return None


def mat_key(typ: Optional[str]) -> str:
    """'$tritium_name;' / 'Tritium' / 'LowTemperatureDiamond' -> 'tritium' ..."""
    s = (typ or "").strip().strip("$;").lower()
    if s.endswith("_name"):
        s = s[:-5]
    return s.replace(" ", "")


def _key(name: Optional[str]) -> str:
    return (name or "").strip("$;").replace("_name", "").lower()


def ring_class(raw: Optional[str]) -> str:
    """'eRingClass_Icy' / 'Icy' -> 'Icy'; MetalRich, Metalic, Rocky kept."""
    return (raw or "").replace("eRingClass_", "").replace("$", "").replace(";", "")


# ---------------------------------------------------------------- sessions
def _vehicle_name(e: Row) -> str:
    return (e.get("SRVType_Localised") or e.get("VesselType_Localised")
            or e.get("SRVType") or e.get("VesselType") or "SRV")


def runs(events: Iterable[Row]) -> List[List[Row]]:
    """Mining events in runs without a break longer than GAP_S, as the FIS's
    mining sessions; only runs that refined or prospected something. Events
    refined out in a surface vehicle carry ``_vehicle``."""
    out: List[List[Row]] = []
    cur: List[Row] = []
    vehicle: Optional[str] = None
    for e in events:
        ev = e.get("event")
        if ev in VEHICLE_OUT:
            vehicle = _vehicle_name(e)
            continue
        if ev in VEHICLE_IN:
            vehicle = None
            continue
        if not ((ev in EVENTS or ev == "Docked") and parse_ts(e.get("timestamp"))):
            continue
        if ev == "LaunchDrone" and (e.get("Type") or "").lower() not in ("prospector", "collection"):
            continue
        if ev == "Docked":                     # docking ends a session
            vehicle = None
            if cur:
                cur[-1] = dict(cur[-1], _docked=True)
                out.append(cur)
                cur = []
            continue
        if vehicle and ev == "MiningRefined":
            e = dict(e, _vehicle=vehicle)
        if cur and ((parse_ts(e["timestamp"]) or 0.0) - (parse_ts(cur[-1]["timestamp"]) or 0.0) > GAP_S
                    or bool(e.get("_vehicle")) != bool(cur[-1].get("_vehicle"))):
            out.append(cur)
            cur = []
        cur.append(e)
    if cur:
        out.append(cur)
    return [r for r in out if any(e["event"] in ("MiningRefined", "ProspectedAsteroid") for e in r)]


# ---------------------------------------------------------------- MP3 rating
def tagged(events: Iterable[Row]) -> List[Row]:
    """The events with the ring they happened in (``_ring``)."""
    ring: Optional[str] = None
    out = []
    for e in events:
        ev = e.get("event")
        if ev == "SupercruiseExit":
            ring = e.get("Body") if e.get("BodyType") == "PlanetaryRing" else None
        elif ev in RING_RESET:
            ring = None
        if ring and ev in ("ProspectedAsteroid", "MiningRefined", "LaunchDrone"):
            e = dict(e, _ring=ring)
        out.append(e)
    return out


def _run_field(run: List[Row], acc: Dict[tuple, Row]) -> None:
    """Add one run to its field (ring + material mostly refined)."""
    rings: Dict[str, int] = {}
    refined: Dict[str, Row] = {}
    for e in run:
        if e.get("_ring"):
            rings[e["_ring"]] = rings.get(e["_ring"], 0) + 1
        if e["event"] == "MiningRefined" and not e.get("_vehicle"):
            k = _key(e.get("Type"))
            r = refined.setdefault(k, {"n": 0, "name": e.get("Type_Localised") or k.capitalize()})
            r["n"] += 1
    if not rings or not refined:
        return
    ring = max(rings, key=lambda k: rings[k])
    main = max(refined, key=lambda k: refined[k]["n"])
    f = acc.setdefault((ring, main), {"ring": ring, "mat": main, "mat_name": refined[main]["name"], "sessions": 0,
                                      "rocks": 0, "with_mat": 0, "share_sum": 0.0, "shares": [], "prospectors": 0,
                                      "main_t": 0, "other": {}, "last": 0.0})
    f["sessions"] += 1
    f["last"] = max(f["last"], parse_ts(run[-1].get("timestamp")) or 0.0)
    for k, r in refined.items():
        if k == main:
            f["main_t"] += r["n"]
        else:
            o = f["other"].setdefault(k, {"name": r["name"], "t": 0})
            o["t"] += r["n"]
    for e in run:
        if e["event"] == "LaunchDrone" and (e.get("Type") or "").lower() == "prospector":
            f["prospectors"] += 1
        elif e["event"] == "ProspectedAsteroid":
            f["rocks"] += 1
            share = max((float(m.get("Proportion") or 0) for m in e.get("Materials") or []
                         if _key(m.get("Name")) == main), default=0.0)
            if share > 0:
                f["with_mat"] += 1
                f["share_sum"] += share
                f["shares"].append(share)


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _row(f: Row, good_pct: Optional[float]) -> Row:
    total_t = f["main_t"] + sum(o["t"] for o in f["other"].values())
    good = sum(1 for x in f["shares"] if good_pct is not None and x >= good_pct)
    catch = sorted(f["other"].values(), key=lambda o: -o["t"])
    return {"ring": f["ring"], "mat": f["mat"], "mat_name": f["mat_name"], "sessions": f["sessions"],
            "rocks": f["rocks"], "purity": round(100.0 * f["with_mat"] / f["rocks"]) if f["rocks"] else None,
            "mean_share": round(f["share_sum"] / f["with_mat"], 1) if f["with_mat"] else None,
            "good_pct": round(good_pct, 1) if good_pct is not None else None, "good": good,
            "prospectors": f["prospectors"], "per_good": round(f["prospectors"] / good, 1) if good else None,
            "rating": None, "main_t": f["main_t"], "bycatch_t": total_t - f["main_t"],
            "bycatch_pct": round(100.0 * (total_t - f["main_t"]) / total_t) if total_t else 0,
            "bycatch": [{"name": o["name"], "t": o["t"]} for o in catch[:4]], "last": f["last"] or None}


def _rate(rows: List[Row]) -> None:
    """Each field against the commander's average for its material."""
    by: Dict[str, List[Row]] = {}
    for r in rows:
        by.setdefault(r["mat"], []).append(r)
    for rs in by.values():
        pros, good = sum(r["prospectors"] for r in rs), sum(r["good"] for r in rs)
        avg = pros / good if good else None
        for r in rs:
            if not r["rocks"]:
                continue
            if r["per_good"] is None:
                r["rating"] = "poor"
            elif avg is None or len(rs) == 1:
                r["rating"] = "fair"
            else:
                q = r["per_good"] / avg
                r["rating"] = "good" if q <= GOOD_RATIO else "poor" if q >= POOR_RATIO else "fair"
            r["avg_per_good"] = round(avg, 1) if avg else None


def rate_fields(events: Iterable[Row], split: Optional[Callable[[List[Row]], List[List[Row]]]] = None) -> List[Row]:
    """MP3: one row per mining field (ring + material looked for), the best
    first (fewest prospectors per good rock), the most recent on a tie.
    ``split`` cuts the events into sessions (default: runs())."""
    acc: Dict[tuple, Row] = {}
    for run in (split or runs)(tagged(events)):
        if any(e.get("_vehicle") for e in run):
            continue                                        # ground mining has no rings
        _run_field(run, acc)
    shares: Dict[str, List[float]] = {}
    for f in acc.values():
        shares.setdefault(f["mat"], []).extend(f["shares"])
    rows = [_row(f, _median(shares[f["mat"]])) for f in acc.values()]
    _rate(rows)
    order = {"good": 0, "fair": 1, "poor": 2, None: 3}
    rows.sort(key=lambda r: (order[r["rating"]], r["per_good"] if r["per_good"] is not None else 1e9,
                             -(r["last"] or 0)))
    return rows


# ---------------------------------------------------------------- MP4 odds
def _reserve(raw: Optional[str]) -> Optional[str]:
    """'PristineResources' -> 'Pristine'."""
    s = (raw or "").replace("Resources", "").strip()
    return s or None


def _json(raw: Any) -> List[Any]:
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return v if isinstance(v, list) else []


def ring_features(query: Callable[[str], Iterable[Any]]) -> Dict[str, Dict[str, Any]]:
    """ring name -> {"cls", "reserve", "spots": {material: count} or None}
    from the plugin database (scanned bodies and the hotspot list);
    ``query(sql)`` returns rows that index by column name."""
    out: Dict[str, Dict[str, Any]] = {}

    def ring(name: str) -> Dict[str, Any]:
        return out.setdefault(name, {"cls": None, "reserve": None, "spots": None})
    try:
        for r in query("SELECT reserve, rings_json FROM bodies WHERE rings_json IS NOT NULL"):
            for g in _json(r["rings_json"]):
                if isinstance(g, dict) and g.get("name"):
                    f = ring(g["name"])
                    f["cls"] = ring_class(g.get("cls")) or f["cls"]
                    f["reserve"] = _reserve(r["reserve"]) or f["reserve"]
    except Exception:
        pass
    try:
        for h in query("SELECT body_name, material, count, ring_class FROM hotspots"):
            if not h["body_name"]:
                continue
            f = ring(h["body_name"])
            f["cls"] = f["cls"] or ring_class(h["ring_class"]) or None
            f["spots"] = f["spots"] or {}
            k = mat_key(h["material"])
            f["spots"][k] = max(f["spots"].get(k, 0), int(h["count"] or 0))
    except Exception:
        pass
    return out


def features(ring: Optional[str], mat: str, rf: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """What is known of a field before mining it."""
    f = rf.get(ring or "") or {}
    spots = f.get("spots")
    n = spots.get(mat, 0) if spots is not None else None
    return {"cls": f.get("cls") or None, "reserve": f.get("reserve"),
            "spot": None if n is None else "yes" if n else "no",
            "overlap": ("yes" if n >= 2 else "no") if n else None, "mat": mat or None}


class Odds:
    """Naive Bayes over the rated fields: good (not poor) against poor."""

    def __init__(self) -> None:
        self.n = [0, 0]                                       # poor, good
        self.counts: Dict[str, List[Dict[str, int]]] = {f: [{}, {}] for f in FEATURES}
        self.known: Dict[str, List[int]] = {f: [0, 0] for f in FEATURES}     # fields per class with f known

    @classmethod
    def learn(cls, samples: Iterable[Sample]) -> "Odds":
        """From (features, 1 good / 0 poor) pairs."""
        m = cls()
        for x, y in samples:
            m.n[y] += 1
            for f in FEATURES:
                if x.get(f) is not None:
                    m.known[f][y] += 1
                    c = m.counts[f][y]
                    c[x[f]] = c.get(x[f], 0) + 1
        return m

    @property
    def fields(self) -> int:
        """How many rated fields it learnt from."""
        return self.n[0] + self.n[1]

    def uses(self, x: Dict[str, Optional[str]]) -> List[str]:
        """The features of ``x`` the chance rests on (known, and seen before)."""
        return [f for f in FEATURES if x.get(f) is not None
                and (x[f] in self.counts[f][0] or x[f] in self.counts[f][1])]

    def chance(self, x: Dict[str, Optional[str]]) -> Optional[float]:
        """P(good) for a field, or None below MIN_FIELDS."""
        if self.fields < MIN_FIELDS:
            return None
        logp = []
        for y in (0, 1):
            lp = math.log((self.n[y] + 1.0) / (self.fields + 2.0))
            for f in FEATURES:
                v = x.get(f)
                seen = set(self.counts[f][0]) | set(self.counts[f][1])
                if v is None or v not in seen:
                    continue
                lp += math.log((self.counts[f][y].get(v, 0) + 1.0) / (self.known[f][y] + len(seen)))
            logp.append(lp)
        top = max(logp)
        e = [math.exp(v - top) for v in logp]
        return e[1] / (e[0] + e[1])


def samples(rated: List[Row], rf: Dict[str, Dict[str, Any]]) -> List[Sample]:
    """The rated fields as (features, good)."""
    return [(features(r["ring"], r["mat"], rf), 0 if r["rating"] == POOR else 1) for r in rated if r.get("rating")]


def verdict(p: Optional[float]) -> Optional[str]:
    """'good' / 'open' / 'poor' for a chance."""
    if p is None:
        return None
    return "good" if p >= LIKELY else "poor" if p <= 1.0 - LIKELY else "open"


def reality(smp: List[Sample]) -> Optional[Dict[str, Any]]:
    """Leave one out: each rated field predicted from all the others."""
    hits = n = 0
    brier = 0.0
    for i, (x, y) in enumerate(smp):
        p = Odds.learn(smp[:i] + smp[i + 1:]).chance(x)
        if p is None:
            continue
        n += 1
        hits += (p >= 0.5) == bool(y)
        brier += (p - y) ** 2
    if not n:
        return None
    return {"n": n, "hits": hits, "hit_pct": round(100.0 * hits / n, 1), "brier": round(brier / n, 3)}


def odds_for(m: Odds, rf: Dict[str, Dict[str, Any]], ring: Optional[str],
             mat: Optional[str]) -> Optional[Dict[str, Any]]:
    """The chance for one field, with what it rests on."""
    if not ring or not mat:
        return None
    x = features(ring, mat, rf)
    p = m.chance(x)
    same = sum(m.counts["mat"][y].get(mat, 0) for y in (0, 1))
    return {"p": round(p, 2) if p is not None else None, "verdict": verdict(p), "n": m.fields, "n_mat": same,
            "thin": m.fields < THIN_FIELDS or not same, "known": m.uses(x)}


def field_of(rated: List[Row], ring: Optional[str], mat: Optional[str]) -> Optional[Row]:
    """The rated row of one field, if it was mined."""
    return next((r for r in rated if r["ring"] == ring and r["mat"] == mat), None)


def _slim(e: Row) -> Row:
    """Only what the fields read: borders keep their name, time and ring."""
    if e.get("event") in EVENTS:
        return e
    return {k: e[k] for k in ("event", "timestamp", "Body", "BodyType") if k in e}


class FieldBook:
    """SP2: the plugin's memory of the mining events - filled once from the
    journals (and EDDiscovery's archive when switched on) by a worker, then
    fed every live journal event. rated() counts; call it in a worker only."""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self.events: List[Row] = []
        self.loaded = False
        self._rated: Optional[List[Row]] = None

    def add(self, e: Row) -> None:
        """A live journal event; only those the fields need are kept."""
        if e.get("event") in NEEDED:
            with self._lock:
                self.events.append(_slim(e))
                self._rated = None

    def load(self, events: Iterable[Row]) -> None:
        """The history, oldest first; live events that came meanwhile stay."""
        base = [_slim(e) for e in events if e.get("event") in NEEDED]
        last = max((e.get("timestamp") or "" for e in base), default="")
        with self._lock:
            live = [e for e in self.events if (e.get("timestamp") or "") > last]
            self.events = base + live
            self.loaded = True
            self._rated = None

    def rated(self) -> List[Row]:
        """The rated fields (cached until the next event)."""
        with self._lock:
            if self._rated is None:
                self._rated = rate_fields(self.events)
            return self._rated


def hotspot_material(name: Optional[str]) -> Optional[str]:
    """Status.json's destination '$SAA_RingHotspot:#type=$Tritium_name;;' ->
    'tritium'; None when it is no ring hotspot."""
    raw = name or ""
    if "#type=" not in raw:
        return None
    return mat_key(raw.split("#type=", 1)[1].strip(";")) or None
