# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
REALITY CHECK (V0, 5.0, user 18.11.2026): every learning model against
your own journals and scans, one error value each - the permanent tool
behind "~". Each check predicts something that already happened from what
was known before it, and counts how far off it was:

* Kepler positions - each scanned body at its scan time against the
  game's DistanceFromArrivalLS (share within 1 % of its own orbit; SK1);
* fuel - each jump's fuel predicted from the jumps before it (SK2, the
  current ship; median and 90 % of the error);
* route minutes - your time in a system against the route's estimate
  kept at the first complete FSS (own-4; median ratio);
* surface scan / bio sample times - the model's value against the median
  of what was measured (SK3);
* exploration value - sales against the formula (B6; the factor's range);
* chance of a find - predicted at arrival against what the scans showed
  (FX3; mean gap per band, weighted by n);
* bio prediction - leave one body out, are its genera in the top three
  (biopredict.validate).

Pure: reads what the FIS has already loaded (database, archive, models);
shown in STATISTICS > LEARNING STATUS. No AI, no network.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = ["fuel", "kepler", "finds", "build", "MIN_FUEL"]

MIN_FUEL = 4          # jumps a fuel prediction needs before it
KEPLER_BAR = 0.01     # within 1 % of the body's own orbit counts as right


def _pct(xs: Sequence[float], q: float) -> Optional[float]:
    v = sorted(xs)
    if not v:
        return None
    return v[min(len(v) - 1, int(q * len(v)))]


def fuel(jumps: Sequence[Tuple[float, ...]],
         make_state: Callable[[List[Tuple[float, ...]]], Any]) -> Optional[Dict[str, Any]]:
    """Each jump's fuel predicted from the ones before it (at its own
    distance and mass): median and 90 % of |error| in percent, and n."""
    errs: List[float] = []
    js = [tuple(j) for j in jumps if len(j) > 1 and j[0] and j[1] and j[1] > 0]
    for i in range(MIN_FUEL, len(js)):
        fs = make_state(js[:i])
        mass = js[i][2] if len(js[i]) > 2 else None
        try:
            c = fs.cost_of(js[i][0], mass)
        except Exception:
            c = None
        if c:
            errs.append(100.0 * abs(c - js[i][1]) / js[i][1])
    if not errs:
        return None
    return {"median_pct": round(_pct(errs, 0.5), 1), "p90_pct": round(_pct(errs, 0.9), 1), "n": len(errs)}


def kepler(systems: Sequence[Any], summary_of: Callable[[Any], Optional[Dict[str, int]]]) -> Optional[Dict[str, Any]]:
    """The Kepler watch over every system: of the bodies checked at their
    scan, the share within KEPLER_BAR of their own orbit."""
    checked = ok = trusted = n_sys = 0
    for s in systems:
        try:
            k = summary_of(s)
        except Exception:
            k = None
        if not k or not k.get("checked"):
            continue
        n_sys += 1
        checked += k["checked"]
        ok += k["ok"]
        trusted += k.get("trusted", 0)
    if not checked:
        return None
    return {"ok_pct": round(100.0 * ok / checked, 1), "checked": checked, "systems": n_sys,
            "trusted": trusted}


def finds(cal: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """FX3: the mean gap between predicted and found share over the bands,
    weighted by their n."""
    bands = [b for b in (cal or {}).get("bands") or [] if b.get("n") and b.get("predicted") is not None
             and b.get("rate") is not None]
    n = sum(b["n"] for b in bands)
    if not n:
        return None
    gap = sum(abs(b["predicted"] - b["rate"]) * b["n"] for b in bands) / n
    return {"gap_pp": round(100.0 * gap, 1), "n": n}


def _row(key: str, label: str, value: Optional[str], n: Optional[int], good: Optional[bool]) -> Dict[str, Any]:
    return {"key": key, "label": label, "value": value, "n": n, "good": good}


def build(parts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per model from the measured parts: key, label (English; the
    FIS translates), value text, n, and good (True / False / None = thin)."""
    rows: List[Dict[str, Any]] = []
    k = parts.get("kepler")
    rows.append(_row("kepler", "Kepler positions", k and "%.1f %% within 1 %% of the orbit · %d systems"
                     % (k["ok_pct"], k["systems"]), k and k["checked"], k and k["ok_pct"] >= 90.0))
    f = parts.get("fuel")
    rows.append(_row("fuel", "Fuel per jump", f and "median %.1f %% off · 90 %% within %.1f %%"
                     % (f["median_pct"], f["p90_pct"]), f and f["n"],
                     (f["median_pct"] <= 3.0) if f and f["n"] >= 10 else None))
    r = parts.get("route")
    rows.append(_row("route", "Time per system vs. route estimate", r and r.get("ratio") is not None
                     and "median × %.2f" % r["ratio"], r and r.get("ratio_n"),
                     (r.get("ratio") is not None and 0.67 <= r["ratio"] <= 1.5)
                     if r and r.get("ratio_n") else None))
    w = parts.get("work") or {}
    if w.get("dss_n"):
        rows.append(_row("work", "Surface scan / bio sample", "~%s s · ~%s s" % (
            _n(w.get("dss_s")), _n(w.get("bio_s"))), (w.get("dss_n") or 0) + (w.get("bio_n") or 0),
            w.get("dss_n", 0) >= 3 and w.get("bio_n", 0) >= 3))
    v = parts.get("value")
    rows.append(_row("value", "Exploration value vs. sales", v and v.get("factor") is not None
                     and "× %.2f (%.2f–%.2f)" % (v["factor"], v["lo"], v["hi"]), v and v.get("n"),
                     (abs(v["factor"] - 1.0) <= 0.25) if v and v.get("factor") is not None else None))
    fd = parts.get("finds")
    rows.append(_row("finds", "Chance of a find vs. scans", fd and "%.1f points off per band" % fd["gap_pp"],
                     fd and fd["n"], (fd["gap_pp"] <= 5.0) if fd and fd["n"] >= 30 else None))
    b = parts.get("bio")
    rows.append(_row("bio", "Bio prediction (genera in top 3)", b and b.get("bodies")
                     and "%.0f %% · first right %.0f %%" % (100.0 * b["recall_top3"], 100.0 * b["top1_right"]),
                     b and b.get("bodies"),
                     (b["recall_top3"] >= 0.6) if b and b.get("bodies", 0) >= 10 else None))
    for row in rows:
        if not row["value"]:
            row["value"], row["good"] = None, None
    return rows


def _n(v: Any) -> str:
    return "–" if v is None else "%.0f" % float(v)
