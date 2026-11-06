"""
The carrier as Frontier's Companion API sees it: the file the plugin writes
when EDMC hands over /fleetcarrier (capi_fleetcarrier.json next to the
plugin database, at most every 15 minutes, only while EDMC runs with a
Frontier login).

Only what the journal cannot say: the hold per good - above all the
tritium in it. Everything is read tolerantly; a missing or odd field leaves
the journal's numbers in place.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

FILE = "capi_fleetcarrier.json"


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(path: Optional[str], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """{saved, age_s, callsign, system, fuel, hold: [...], tritium} or None."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    d = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        return None
    now = time.time() if now is None else now
    saved = _num(payload.get("saved"))
    goods: Dict[str, Dict[str, Any]] = {}
    for c in d.get("cargo") or []:
        if not isinstance(c, dict):
            continue
        key = str(c.get("commodity") or "").strip().lower()
        if not key:
            continue
        g = goods.setdefault(key, {"key": key, "name": c.get("locName") or c.get("commodity"),
                                   "qty": 0, "value": 0, "stolen": 0, "mission": 0})
        q = int(_num(c.get("qty")) or 0)
        g["qty"] += q
        g["value"] += int(_num(c.get("value")) or 0)
        if c.get("stolen"):
            g["stolen"] += q
        if c.get("mission"):
            g["mission"] += q
    hold: List[Dict[str, Any]] = sorted(goods.values(), key=lambda g: -g["qty"])
    name = d.get("name") if isinstance(d.get("name"), dict) else {}
    return {"saved": saved, "age_s": round(now - saved) if saved else None,
            "callsign": name.get("callsign"), "system": d.get("currentStarSystem"),
            "fuel": _num(d.get("fuel")), "hold": hold,
            "hold_total": sum(g["qty"] for g in hold),
            "tritium": goods.get("tritium", {}).get("qty", 0)}


def path_for(plugin_dir: Optional[str]) -> Optional[str]:
    return os.path.join(plugin_dir, FILE) if plugin_dir else None
