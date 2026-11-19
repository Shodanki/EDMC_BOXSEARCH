# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
FORECASTS (5.0, B-24 of the inventory report, user 18.11.2026): what is
still ahead, from your own data only - each as "~" with a range and the n
it was learnt from, never a bare number:

* the rest of the sphere: open systems x your mean minutes per system
  (own-4) -> hours left; x your mean value per hour (RT1/FX0 sessions) ->
  value still to gather; x the share of systems with an undiscovered body
  (FX3) -> finds still to expect. A sum over many systems: the range is
  the 95 % interval of the mean (1.96 standard errors), not the spread of
  single systems - that would give 4 to 1,100 hours for one sphere;
* jumps until the tank is empty at the distance you fly lately (SK2 fuel
  model with mass, its scatter as the range);
* the chance that a landable planet carries life, by its atmosphere, else
  its planet class (BQ1 rates, 95 % Wilson interval).

Pure counting - no AI, no network. Read only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

__all__ = ["quartiles", "mean_ci", "sphere", "jumps", "bio_chance"]

MIN_N = 3            # fewer than this and a forecast says "thin"


def quartiles(xs: Sequence[float]) -> Optional[Dict[str, float]]:
    """Median and the two quartiles of xs (linear between ranks), or None."""
    v = sorted(float(x) for x in xs if x is not None)
    if not v:
        return None

    def q(p: float) -> float:
        i = p * (len(v) - 1)
        lo = int(i)
        hi = min(lo + 1, len(v) - 1)
        return v[lo] + (v[hi] - v[lo]) * (i - lo)
    return {"mid": q(0.5), "lo": q(0.25), "hi": q(0.75), "n": len(v)}


def mean_ci(xs: Sequence[float]) -> Optional[Dict[str, float]]:
    """The mean of xs and its 95 % interval (1.96 standard errors, never
    below 0), or None."""
    v = [float(x) for x in xs if x is not None]
    if not v:
        return None
    n = len(v)
    mu = sum(v) / n
    se = ((sum((x - mu) ** 2 for x in v) / (n - 1)) ** 0.5 / n ** 0.5) if n > 1 else mu
    return {"mid": mu, "lo": max(0.0, mu - 1.96 * se), "hi": mu + 1.96 * se, "n": n}


def sphere(systems: Optional[Dict[str, Any]], minutes: Sequence[float], value_h: Sequence[float],
           finds: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The rest of the active sphere: hours, value and finds still ahead.
    `systems`: build_survey's counts (known, visited); `minutes`: your
    minutes per system (systime rows); `value_h`: Cr per hour of your
    sessions; `finds`: FX3's base rates ({"pg": {"hits", "n"}})."""
    if not systems or not systems.get("known"):
        return None
    left = max(0, int(systems["known"]) - int(systems.get("visited") or 0))
    out: Dict[str, Any] = {"open": left}
    m = mean_ci(minutes)
    if m:
        out["hours"] = {k: round(left * m[k] / 60.0, 1) for k in ("mid", "lo", "hi")}
        out["hours"]["n"] = m["n"]
        out["min_per_system"] = round(m["mid"], 1)
    v = mean_ci(value_h)
    if m and v:
        out["value"] = {k: round(out["hours"][k] * v[k]) for k in ("mid", "lo", "hi")}
        out["value"]["n"] = v["n"]
        out["value_h"] = round(v["mid"])
    base = (finds or {}).get("base") or {}
    pg = base.get("pg") or {}
    if pg.get("n"):
        rate = float(pg.get("hits") or 0) / float(pg["n"])
        from .learn import wilson
        lo, hi = wilson(int(pg.get("hits") or 0), int(pg["n"]))
        out["finds"] = {"mid": round(left * rate, 1), "lo": round(left * (lo or 0) / 100.0, 1),
                        "hi": round(left * (hi or 0) / 100.0, 1), "n": int(pg["n"])}
    out["thin"] = not m or m["n"] < MIN_N
    return out


def jumps(fs: Any) -> Optional[Dict[str, Any]]:
    """Jumps until the tank is empty at the distance flown lately (SK2): the
    model's scatter widens the cost both ways. None without data."""
    try:
        dist = float(fs.typical_jump or 0.0)
        level = float(fs.level or 0.0)
        cost = fs.cost_of(dist) if dist > 0.5 else None
        learned = fs.learned()
    except Exception:
        return None
    if not cost or cost <= 0 or level <= 0:
        return None
    s = (learned.get("spread_pct") or 10.0) / 100.0      # no fit yet: a wide 10 %
    return {"mid": int(level / cost), "lo": int(level / (cost * (1.0 + s))),
            "hi": int(level / (cost * max(0.5, 1.0 - s))), "ly": round(dist, 1),
            "n": int(learned.get("n") or 0), "thin": learned.get("source") != "fit"}


def _group(rows: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    for g in rows or []:
        if g.get("key") == key:
            return g
    return None


def bio_chance(body: Dict[str, Any], rates: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The chance that a landable planet carries life (BQ1): by its
    atmosphere when that group has data, else by its planet class, else
    over all landable planets. None for a body that is not landable."""
    if not rates or not body or not body.get("landable"):
        return None
    atmo = body.get("atmo_type")
    atmo = atmo if atmo and atmo != "None" else "none"
    g = _group(rates.get("atmo"), atmo)
    basis = "atmosphere"
    if g is None:
        g, basis = _group(rates.get("pclass"), body.get("planet_class") or "?"), "planet class"
    if g is None:
        n, k = int(rates.get("planets") or 0), int(rates.get("with_bio") or 0)
        if not n:
            return None
        from .learn import wilson
        lo, hi = wilson(k, n)
        g, basis = {"key": "all", "n": n, "pct": round(100.0 * k / n, 1), "lo": lo, "hi": hi}, "all"
    return {"pct": g["pct"], "lo": g["lo"], "hi": g["hi"], "n": g["n"], "basis": basis, "key": g["key"]}
