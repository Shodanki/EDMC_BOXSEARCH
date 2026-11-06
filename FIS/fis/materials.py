"""
JUMPONIUM: how many FSD injections the raw materials on board allow, what
limits them and where the missing ones were measured.

The stock is the last Materials event (written at every login) with what
happened since: collected, discarded, synthesised, crafted, traded, given to
a technology broker or for research, mission rewards. The bodies come from
the plugin database (Scan: materials in percent), nearest first.

Reads the journal and the plugin database only.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional

from .science import JUMPONIUM

GRADE = {"carbon": 1, "vanadium": 2, "germanium": 2, "arsenic": 2, "cadmium": 3, "niobium": 3,
         "yttrium": 4, "polonium": 4}
CAP = {1: 300, 2: 250, 3: 200, 4: 150, 5: 100}
BOOST = {"basic": 25, "standard": 50, "premium": 100}
SYNTH = {"fsd basic": "basic", "fsd standard": "standard", "fsd premium": "premium"}
EVENTS = ("Materials", "MaterialCollected", "MaterialDiscarded", "Synthesis", "EngineerCraft",
          "MaterialTrade", "TechnologyBroker", "MissionCompleted", "ScientificResearch")


def _k(name: Optional[str]) -> str:
    return (name or "").strip().lower()


def stock(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Raw materials on board: {name: count}, plus when the stock was read
    and the FSD injections synthesised since."""
    evs = [e for e in events if e["event"] in EVENTS]
    base = next((i for i in range(len(evs) - 1, -1, -1) if evs[i]["event"] == "Materials"), None)
    have: Dict[str, int] = {}
    synth: List[Dict[str, Any]] = []
    if base is not None:
        for m in evs[base].get("Raw") or []:
            have[_k(m.get("Name"))] = int(m.get("Count") or 0)
    start = base + 1 if base is not None else 0

    def add(name, n):
        k = _k(name)
        have[k] = max(0, have.get(k, 0) + int(n or 0))

    for e in evs[start:]:
        ev = e["event"]
        if ev == "MaterialCollected":
            add(e.get("Name"), e.get("Count") or 1)
        elif ev == "MaterialDiscarded":
            add(e.get("Name"), -(e.get("Count") or 1))
        elif ev == "Synthesis":
            for m in e.get("Materials") or []:
                add(m.get("Name"), -(m.get("Count") or 1))
            g = SYNTH.get(_k(e.get("Name")))
            if g:
                synth.append({"grade": g, "ts": e.get("timestamp")})
        elif ev == "EngineerCraft":
            for m in e.get("Ingredients") or []:
                add(m.get("Name"), -(m.get("Count") or 1))
        elif ev == "TechnologyBroker":
            for m in e.get("Materials") or []:
                add(m.get("Name"), -(m.get("Count") or 1))
        elif ev == "MaterialTrade":
            paid, got = e.get("Paid") or {}, e.get("Received") or {}
            add(paid.get("Material"), -(paid.get("Quantity") or 0))
            add(got.get("Material"), got.get("Quantity") or 0)
        elif ev == "MissionCompleted":
            for m in e.get("MaterialsReward") or []:
                add(m.get("Name"), m.get("Count") or 1)
        elif ev == "ScientificResearch":
            add(e.get("Name"), -(e.get("Count") or 1))
    return {"have": have, "base_ts": evs[base].get("timestamp") if base is not None else None,
            "synthesised": synth}


def readiness(have: Dict[str, int]) -> List[Dict[str, Any]]:
    out = []
    for grade in ("basic", "standard", "premium"):
        recipe = JUMPONIUM[grade]
        n = min(have.get(m, 0) for m in recipe)
        low = min(recipe, key=lambda m: (have.get(m, 0), m))
        out.append({"grade": grade, "boost": BOOST[grade], "can": n,
                    "missing": [m for m in recipe if not have.get(m)], "limit": low,
                    "recipe": list(recipe)})
    return out


def sources(db: Any, wanted: Iterable[str], pos, per: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    """Nearest landable bodies with each material, from your own scans."""
    wanted = [w for w in wanted]
    out: Dict[str, List[Dict[str, Any]]] = {w: [] for w in wanted}
    if db is None or not wanted:
        return out
    try:
        rows = db.query("SELECT b.name, b.sys_id64, b.materials, s.name AS system, s.x, s.y, s.z FROM bodies b "
                        "JOIN systems s ON s.id64 = b.sys_id64 WHERE b.landable = 1 AND b.materials IS NOT NULL "
                        "AND b.materials <> '' AND s.x IS NOT NULL")
    except Exception:
        return out
    cand: Dict[str, List[Dict[str, Any]]] = {w: [] for w in wanted}
    for r in rows:
        try:
            mats = {_k(k): v for k, v in (json.loads(r["materials"]) or {}).items()}
        except (TypeError, ValueError):
            continue
        ly = math.dist(pos, (r["x"], r["y"], r["z"])) if pos else None
        for w in wanted:
            if mats.get(w):
                cand[w].append({"body": r["name"], "system": r["system"], "id": r["sys_id64"],
                                "pct": round(float(mats[w]), 1), "ly": round(ly, 1) if ly is not None else None})
    for w, lst in cand.items():
        lst.sort(key=lambda c: (c["ly"] is None, c["ly"] or 0, -c["pct"]))
        out[w] = lst[:per]
    return out


def build_jumponium(archive: Any, db: Any = None, pos=None) -> Dict[str, Any]:
    st = stock(archive.events())
    have = st["have"]
    ready = readiness(have)
    mats = [{"key": m, "count": have.get(m, 0), "grade": g, "cap": CAP[g]} for m, g in GRADE.items()]
    # sources for what limits premium and standard, and anything missing
    want = sorted({r["limit"] for r in ready} | {m for r in ready for m in r["missing"]})
    return {"materials": mats, "ready": ready, "base_ts": st["base_ts"],
            "synthesised": st["synthesised"][-10:], "sources": sources(db, want, pos)}
