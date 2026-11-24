# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
MP4 (5.1.0, user 24.11.): the chance that a mining field turns out good,
before mining there - learnt from the commander's own fields as MP3
(fieldrating) rated them, so every newly mined field teaches it.

"Good" here means not "poor": the field needed at most POOR_RATIO times the
commander's average prospectors per good rock of that material (fieldrating).

What a ring is known by before the first laser shot (plugin database):

- the ring class (Icy, Rocky, Metal Rich, Metallic);
- the reserve level of its body (Pristine ... Depleted);
- whether the ring has a hotspot of the material, and whether more than one
  (overlapping hotspots) - known once the ring was mapped with the DSS;
  unknown rings leave both out;
- the material.

Naive Bayes with Laplace counts (+1) over those features, each class
counted only over the fields where that feature was known, over the values
seen so far (a feature alike in every rated field stays neutral). A feature
unknown for a ring, or a
value never seen in a rated field yet (a material never mined), is left
out - it says nothing yet, rather than pulling towards the smaller class. Below MIN_FIELDS rated fields there is
no number. The reality check takes each rated field out in turn, predicts it
from the others and counts how often the side (good / poor) was right.
Read only, counting - no AI.
"""
import math
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

POOR = "poor"
MIN_FIELDS = 3             # rated fields before a chance is given
THIN_FIELDS = 10           # below this the chance is shown dim
LIKELY = 0.65              # >= likely good, <= 1 - LIKELY likely poor
FEATURES = ("cls", "reserve", "spot", "overlap", "mat")

_lock = threading.Lock()
_cache: Dict[str, Tuple[Any, Any]] = {}


def _mat(name: Optional[str]) -> str:
    from .mining import type_key
    return type_key(name)


def _reserve(raw: Optional[str]) -> Optional[str]:
    """'PristineResources' -> 'Pristine'."""
    s = (raw or "").replace("Resources", "").strip()
    return s or None


def ring_features(db: Any) -> Dict[str, Dict[str, Any]]:
    """ring name -> {"cls", "reserve", "spots": {material: count} or None}
    from the plugin database (scanned bodies and the hotspot list)."""
    from . import prospect
    from .data import _json
    out: Dict[str, Dict[str, Any]] = {}
    if db is None:
        return out

    def ring(name: str) -> Dict[str, Any]:
        return out.setdefault(name, {"cls": None, "reserve": None, "spots": None})
    try:
        for r in db.query("SELECT reserve, rings_json FROM bodies WHERE rings_json IS NOT NULL"):
            for g in _json(r["rings_json"], []) or []:
                if g.get("name"):
                    f = ring(g["name"])
                    f["cls"] = prospect.ring_class(g.get("cls")) or f["cls"]
                    f["reserve"] = _reserve(r["reserve"]) or f["reserve"]
    except Exception:
        pass
    try:
        for h in db.query("SELECT body_name, material, count, ring_class FROM hotspots"):
            if not h["body_name"]:
                continue
            f = ring(h["body_name"])
            f["cls"] = f["cls"] or prospect.ring_class(h["ring_class"]) or None
            f["spots"] = f["spots"] or {}
            k = _mat(h["material"])
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
    def learn(cls, samples: Iterable[Tuple[Dict[str, Optional[str]], int]]) -> "Odds":
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


def samples(rated: List[Dict[str, Any]], rf: Dict[str, Dict[str, Any]]) -> List[Tuple[Dict[str, Optional[str]], int]]:
    """The MP3 rows that carry a rating, as (features, good)."""
    return [(features(r["ring"], r["mat"], rf), 0 if r["rating"] == POOR else 1) for r in rated if r.get("rating")]


def verdict(p: Optional[float]) -> Optional[str]:
    """'good' / 'open' / 'poor' for a chance."""
    if p is None:
        return None
    return "good" if p >= LIKELY else "poor" if p <= 1.0 - LIKELY else "open"


def reality(smp: List[Tuple[Dict[str, Optional[str]], int]]) -> Optional[Dict[str, Any]]:
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


def model(events: List[Dict[str, Any]], db: Any) -> Tuple[Odds, Dict[str, Dict[str, Any]], List[Tuple[Any, int]]]:
    """The model, the ring features and the samples - rebuilt only when the
    journals moved (the live view asks every few seconds)."""
    sig = (len(events), events[-1].get("timestamp") if events else None, id(db))
    with _lock:
        hit = _cache.get("model")
        if hit and hit[0] == sig:
            return hit[1]
    from . import fieldrating
    rf = ring_features(db)
    smp = samples(fieldrating.rate_fields(events), rf)
    val = (Odds.learn(smp), rf, smp)
    with _lock:
        _cache["model"] = (sig, val)
    return val


def odds_for(m: Odds, rf: Dict[str, Dict[str, Any]], ring: Optional[str],
             mat: Optional[str]) -> Optional[Dict[str, Any]]:
    """The chance for one field, with what it rests on - for the FIS."""
    if not ring or not mat:
        return None
    x = features(ring, mat, rf)
    p = m.chance(x)
    same = sum(m.counts["mat"][y].get(mat, 0) for y in (0, 1))
    return {"p": round(p, 2) if p is not None else None, "verdict": verdict(p), "n": m.fields, "n_mat": same,
            "thin": m.fields < THIN_FIELDS or not same, "known": m.uses(x)}
