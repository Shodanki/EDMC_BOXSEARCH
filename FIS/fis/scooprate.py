# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Fuel scoop rate per star class (5.0, B-15), learnt from your own journals.

While scooping the game writes a FuelScoop event about every 5 t; two in a
row in the same system, at most GAP_S apart, give tonnes per second. The
star is the one the last hyperspace jump went to (StartJump names its
class). The rate depends on the scoop and how close you fly, so the figure
is what you got with your ships - median and middle half, "learnt from n".
The reality check (V0) judges each rate by the ones before it of the same
class.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .live import parse_ts

GAP_S = 30.0          # longer: scooping stopped in between
MIN_N = 5             # below: thin


def _q(xs: Sequence[float], q: float) -> float:
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def samples(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each measured rate in journal order: {"cls", "t_s", "ts"}."""
    out: List[Dict[str, Any]] = []
    next_cls: Optional[str] = None
    cls: Optional[str] = None
    last: Optional[float] = None
    for e in events:
        ev = e.get("event")
        if ev == "StartJump" and e.get("JumpType") == "Hyperspace":
            next_cls = e.get("StarClass")
        elif ev in ("FSDJump", "CarrierJump", "Location"):
            cls = next_cls if ev == "FSDJump" else None
            next_cls, last = None, None
        elif ev == "FuelScoop":
            ts = parse_ts(e.get("timestamp"))
            try:
                got = float(e.get("Scooped") or 0.0)
            except (TypeError, ValueError):
                got = 0.0
            if ts is not None and last is not None and cls and got > 0 and 0 < ts - last <= GAP_S:
                out.append({"cls": cls, "t_s": got / (ts - last), "ts": ts})
            last = ts
    return out


def rates(smp: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per star class: median tonnes per second, middle half, n, thin -
    most samples first."""
    by: Dict[str, List[float]] = {}
    for s in smp:
        by.setdefault(s["cls"], []).append(s["t_s"])
    out = [{"cls": c, "t_s": round(_q(xs, 0.5), 2), "lo": round(_q(xs, 0.25), 2), "hi": round(_q(xs, 0.75), 2),
            "n": len(xs), "thin": len(xs) < MIN_N} for c, xs in by.items()]
    out.sort(key=lambda r: (-r["n"], r["cls"]))
    return out


def reality(smp: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """V0: each rate against the median of the rates of the same class
    before it (from MIN_N on) - median and 90 % error in per cent."""
    seen: Dict[str, List[float]] = {}
    errs: List[float] = []
    for s in smp:
        xs = seen.setdefault(s["cls"], [])
        if len(xs) >= MIN_N:
            errs.append(100.0 * abs(_q(xs, 0.5) - s["t_s"]) / s["t_s"])
        xs.append(s["t_s"])
    if not errs:
        return None
    return {"median_pct": round(_q(errs, 0.5), 1), "p90_pct": round(_q(errs, 0.9), 1), "n": len(errs)}
