# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
FX3 (5.0): how likely a system still holds a body nobody has discovered -
counted from the commander's own visits, with a range and "learnt from n".

The FX1 measurement (18.11.2026) showed where the finds are: not new arrival
stars (0 in 661 jumps) but bodies in systems a database already lists - in
the explored deep space of the survey sphere one system in four. So the
outcome counted here is "this commander's scans found at least one body
with WasDiscovered false" in a system whose FSS was completed (or that
paid). The features are what is known BEFORE the visit:

    height galactic height |y| below or above HEIGHT_LY ("?" = no position).
           FX3 measurement: 3 % of the settled visits near the plane paid,
           14 % above or below it - the one feature with a clear signal
    kind   procgen mass code a-h, or "named" (catalogue and hand-made systems)
    star   the arrival star's class group (M, K, FG, OBA, LTY, rest)
    level  shells.info_level before arrival: known / checked / unchecked /
           inhabited ("" for visits before the V0 log existed)

The cells nest in that order. Counting only, no model: each cell leans on its broader cell with weight
WEIGHT (pseudo-visits), the root on a weak prior. The V0 loop: on the first
arrival in a system the prediction is kept in the table find_log
(SystemDB.keep_find_prediction); calibration() sets predictions against
what the scans then showed (FIS STATISTICS > LEARNING STATUS).

Pure module without imports from the plugin, so the FIS can load it as
well: no EDMC, no Tk, no network. ``query`` is any callable (sql, args) ->
rows (sqlite3.Row or tuples in the selected order).
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

WEIGHT = 10.0            # pseudo-visits a cell needs before its own count outweighs its parent
ROOT_WEIGHT = 10.0       # the prior's weight at the root, like any parent cell
# FX1 measurement (own scans, 18.11.2026): pg 20 of 241 systems, named 1 of 30
PRIOR = {"pg": 0.08, "named": 0.03}
HEIGHT_LY = 100.0                 # |y| that splits "near the plane" from "above / below"
BANDS = (0.05, 0.15, 0.30)        # edges of the predicted chance in calibration()
# the mass code of a procgen name, as procgen._NAME_RE reads it (tests/findodds.py compares)
_MC_RE = re.compile(r"^.+?\s+[A-Za-z][A-Za-z]-[A-Za-z]\s+([A-Ha-h])(?:\d+-)?\d+$")

Query = Callable[[str, Sequence[Any]], Iterable[Any]]


def star_group(star_class: Optional[str]) -> str:
    """The arrival star's class as one of six groups ("" = not known)."""
    s = (star_class or "").strip().upper()
    if not s:
        return ""
    if s[0] in "MK" and not s.startswith("MS"):
        return s[0]
    if s[0] in "FG":
        return "FG"
    if s[0] in "OBA" and not s.startswith("AEBE"):
        return "OBA"
    if s[0] in "LTY" and s != "TTS":
        return "LTY"
    return "rest"


def kind_of(name: Optional[str]) -> str:
    """The procgen mass code of a system name, or "named"."""
    m = _MC_RE.match((name or "").strip())
    return m.group(1).lower() if m else "named"


def height_band(y: Optional[float]) -> str:
    """ "low" near the galactic plane, "high" above or below, "?" unknown."""
    try:
        return "high" if abs(float(y)) >= HEIGHT_LY else "low"
    except (TypeError, ValueError):
        return "?"


def _keys(kind: str, star: str, level: str, height: str) -> List[Tuple[str, ...]]:
    """The cells of one visit, from the broadest to the narrowest."""
    root = ("pg",) if kind != "named" else ("named",)
    h = root + (height or "?",)
    keys = [root, h, h + (kind,)]
    if star:
        keys.append(h + (kind, star))
        if level:
            keys.append(h + (kind, star, level))
    return keys


def _wilson(k: float, n: float, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = min(1.0, max(0.0, k / n))
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


class FindOdds:
    """The counted chance of a find, from (kind, star, level, hit, height) visits."""

    def __init__(self, visits: Iterable[Tuple[str, str, str, bool, str]] = ()) -> None:
        self.cells: Dict[Tuple[str, ...], List[int]] = {}
        self.n = 0
        for kind, star, level, hit, height in visits:
            self.add(kind, star, level, hit, height)

    def add(self, kind: str, star: str, level: str, hit: bool, height: str = "?") -> None:
        """Count one visit with its outcome."""
        for k in _keys(kind, star, level, height):
            c = self.cells.setdefault(k, [0, 0])
            c[0] += 1 if hit else 0
            c[1] += 1
        self.n += 1

    def predict(self, name: Optional[str], star_class: Optional[str] = None,
                level: str = "", y: Optional[float] = None) -> Dict[str, Any]:
        """
        The chance that a first visit finds an undiscovered body:
        {p, low, high, n (visits of the narrowest cell with data), learnt
        (all visits), kind, star, level, height, why (the cell that decided)}.
        y is the system's galactic height (StarPos[1]).
        """
        kind, star, height = kind_of(name), star_group(star_class), height_band(y)
        keys = _keys(kind, star, level or "", height)
        p = PRIOR[keys[0][0]]
        weight = ROOT_WEIGHT
        n_used, why = 0, "prior"
        for k in keys:
            h, n = self.cells.get(k, (0, 0))
            p = (h + weight * p) / (n + weight)
            if n:
                n_used, why = n, "/".join(k)
            weight = WEIGHT
        eff = n_used + WEIGHT
        lo, hi = _wilson(p * eff, eff)
        return {"p": p, "low": lo, "high": hi, "n": n_used, "learnt": self.n,
                "kind": kind, "star": star, "level": level or "", "height": height, "why": why}


# --------------------------------------------------------------- from the DB

_VISITS_SQL = (
    "SELECT s.name, s.star_class, cb.fid, cb.sys_id64, s.y, "
    "MAX(CASE WHEN cb.was_discovered = 0 THEN 1 ELSE 0 END) AS hit, "
    "MAX(COALESCE(cs.fss_complete, 0)) AS done, fl.level AS level "
    "FROM cmdr_bodies cb JOIN systems s ON s.id64 = cb.sys_id64 "
    "LEFT JOIN cmdr_systems cs ON cs.fid = cb.fid AND cs.sys_id64 = cb.sys_id64 "
    "LEFT JOIN find_log fl ON fl.fid = cb.fid AND fl.sys_id64 = cb.sys_id64 "
    "WHERE cb.scanned = 1 GROUP BY cb.fid, cb.sys_id64")


def visits(query: Query) -> List[Dict[str, Any]]:
    """Every (commander, system) with own scans whose outcome is settled:
    the FSS was completed, or a scan found an undiscovered body."""
    out = []
    try:
        rows = list(query(_VISITS_SQL, ()))
    except Exception:
        return out
    for name, star, fid, sid, y, hit, done, level in rows:
        if not (hit or done):
            continue
        out.append({"name": name, "star": star_class_of(star), "fid": fid, "sys_id64": sid,
                    "hit": bool(hit), "level": level or "", "height": height_band(y)})
    return out


def star_class_of(v: Any) -> str:
    """The stored star class as text."""
    return v if isinstance(v, str) else ""


def model(query: Query, skip: Optional[Tuple[Any, Any]] = None) -> FindOdds:
    """The odds counted from all settled visits; skip = (fid, sys_id64) of
    a visit to leave out (the one being predicted)."""
    m = FindOdds()
    for v in visits(query):
        if skip is not None and (v["fid"], v["sys_id64"]) == tuple(skip):
            continue
        m.add(kind_of(v["name"]), star_group(v["star"]), v["level"], v["hit"], v["height"])
    return m


_REASON = {"high": "off-plane", "low": "near plane", "known": "in a DB", "checked": "in no DB",
           "unchecked": "not checked", "inhabited": "inhabited", "named": "named", "rest": "other star"}


def reason(pred: Dict[str, Any]) -> str:
    """FX5: the cell that decided a prediction in a few words (English, for
    the in-game overlay; the FIS builds its own text from the fields):
    "off-plane, mc b, M star" - or "no own data yet" for the prior."""
    why = str(pred.get("why") or "prior").split("/")
    if why == ["prior"]:
        return "no own data yet"
    parts = []
    for i, w in enumerate(why[1:], 1):
        if w == "?":
            continue
        if i == 2 and w != "named":
            parts.append("mc %s" % w)
        elif i == 3 and w not in _REASON:
            parts.append("%s star" % w)
        else:
            parts.append(_REASON.get(w, w))
    return ", ".join(parts) or "all own visits"


def band(p: float) -> int:
    """The calibration band of a predicted chance (BANDS)."""
    return sum(1 for e in BANDS if p >= e)


def calibration(query: Query) -> Dict[str, Any]:
    """
    V0: the kept predictions (find_log) against what the scans showed. Per
    band of the predicted chance: n, the mean prediction, the hits, the
    observed rate with its 95 % range. Also how many predictions wait for
    their outcome and what the model has learnt from.
    """
    try:
        logged = list(query("SELECT fid, sys_id64, p FROM find_log", ()))
    except Exception:
        logged = []
    vs = visits(query)
    settled = {(v["fid"], v["sys_id64"]): v["hit"] for v in vs}
    cells = [[0, 0, 0.0] for _ in range(len(BANDS) + 1)]
    waiting = 0
    for fid, sid, p in logged:
        hit = settled.get((fid, sid))
        if hit is None:
            waiting += 1
            continue
        c = cells[band(float(p or 0.0))]
        c[0] += 1 if hit else 0
        c[1] += 1
        c[2] += float(p or 0.0)
    out = []
    for i, (h, n, sp) in enumerate(cells):
        lo, hi = _wilson(h, n) if n else (None, None)
        out.append({"band": i, "from": BANDS[i - 1] if i else 0.0,
                    "to": BANDS[i] if i < len(BANDS) else None, "n": n, "hits": h,
                    "predicted": (sp / n) if n else None, "rate": (h / n) if n else None,
                    "low": lo, "high": hi, "thin": n < WEIGHT})
    m = FindOdds((kind_of(v["name"]), star_group(v["star"]), v["level"], v["hit"], v["height"]) for v in vs)
    base = {k[0]: {"n": c[1], "hits": c[0]} for k, c in m.cells.items() if len(k) == 1}
    return {"bands": out, "logged": len(logged), "waiting": waiting,
            "learnt": m.n, "base": base}
