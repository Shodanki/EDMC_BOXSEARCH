"""
GALAXY: where you have been, where you survey, what is still open.

Layers for the browser's top view (galactic x to the right, z up towards the
core, y as height):

  path       every hyperspace jump of the commander logged in, with time -
             from all journals, so it reaches back as far as they do
  carrier    the fleet carrier's jumps
  spheres    the survey spheres of the plugin; the active one highlighted
  boxels     for the active sphere and one mass code: every boxel that meets
             the sphere, as closed (all systems known), open (started) or
             never checked - the work list the plugin goes through
  systems    known systems with coordinates: visited, FSS complete, known
             to nobody else ("only us")
  finds      systems with Guardian / non-human sites, Brain Trees, codex sites
  navroute   the plotted route; you: the current position

Reads the plugin database and the journals only.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence

from . import fleet as fl
from .data import Database
from .live import parse_ts

FIND_KINDS = ("site:guardian", "site:nonhuman", "guardian", "thargoid", "genus:Brain Trees")
MAX_PATH = 20000


def _plugin():
    from .model import plugin
    return plugin()


def _r(v: Optional[float], nd: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), nd)


def flight_path(archive: fl.Archive, since: Optional[float] = None) -> List[Dict[str, Any]]:
    """Hyperspace jumps (and the first known position) of the commander in order."""
    out: List[Dict[str, Any]] = []
    for e in archive.events():
        if e["event"] not in ("FSDJump", "Location", "CarrierJump") or not e.get("StarPos"):
            continue
        ts = parse_ts(e.get("timestamp"))
        if since and ts and ts < since:
            continue
        x, y, z = e["StarPos"][:3]
        if out and out[-1]["name"] == e.get("StarSystem"):
            continue                                   # login in the same system
        out.append({"t": ts, "name": e.get("StarSystem"), "id64": e.get("SystemAddress"),
                    "x": _r(x), "y": _r(y), "z": _r(z),
                    "kind": {"FSDJump": "jump", "Location": "login", "CarrierJump": "carrier"}[e["event"]],
                    "ly": _r(e.get("JumpDist"), 1)})
    return out[-MAX_PATH:]


def carrier_path(archive: fl.Archive) -> List[Dict[str, Any]]:
    """Positions the carrier went through (systems with known coordinates)."""
    pos: Dict[str, Any] = {}
    seq: List[Dict[str, Any]] = []
    for e in archive.events():
        if e.get("StarPos") and e.get("StarSystem"):
            pos[e["StarSystem"]] = e["StarPos"]
        if e["event"] in ("CarrierJump", "CarrierLocation") and e.get("StarSystem"):
            if seq and seq[-1]["name"] == e["StarSystem"]:
                continue
            seq.append({"name": e["StarSystem"], "t": parse_ts(e.get("timestamp"))})
    out = []
    for s in seq:
        p = pos.get(s["name"])
        if p:
            out.append(dict(s, x=_r(p[0]), y=_r(p[1]), z=_r(p[2])))
    return out


def sphere_boxels(db: Database, center: Sequence[float], radius: float, mc: int
                  ) -> List[Dict[str, Any]]:
    """Every boxel of mass code `mc` meeting the sphere, with its survey status."""
    pg = _plugin().procgen
    size = pg.boxel_size(mc)
    # boxel key <-> global index, learnt from systems we know the position of
    known = db.query("SELECT name, x, y, z FROM systems WHERE x IS NOT NULL AND "
                     "x BETWEEN ? AND ? AND y BETWEEN ? AND ? AND z BETWEEN ? AND ?",
                     (center[0] - radius - size, center[0] + radius + size,
                      center[1] - radius - size, center[1] + radius + size,
                      center[2] - radius - size, center[2] + radius + size))
    key_of: Dict[tuple, str] = {}
    count: Dict[tuple, int] = {}
    for r in known:
        pn = pg.parse_name(r["name"] or "")
        if pn is None or pn.mc != mc:
            continue
        g = tuple(pg.boxel_index_of_coords(r["x"], r["y"], r["z"], mc))
        key_of[g] = pn.boxel_key
        count[g] = count.get(g, 0) + 1
    status = {r["key"]: r for r in db.query("SELECT key, complete, n2_max FROM boxels")}
    out = []
    for g in pg.boxels_in_sphere(mc, center, radius):
        c = pg.boxel_center(g, mc)
        key = key_of.get(tuple(g))
        row = status.get(key) if key else None
        st = ("closed" if row is not None and row["complete"] else
              "open" if row is not None or key else "unchecked")
        out.append({"x": _r(c[0], 1), "y": _r(c[1], 1), "z": _r(c[2], 1), "key": key,
                    "status": st, "known": count.get(tuple(g), 0),
                    "n2_max": row["n2_max"] if row is not None else None})
    return out


def _busiest_mc(db: Database, sp: Dict[str, Any], mcs: Sequence[int]) -> int:
    """The mass code you actually work in: most boxels of the survey table there."""
    pg = _plugin().procgen
    seen: Dict[int, int] = {}
    for r in db.query("SELECT key FROM boxels"):
        pn = pg.parse_boxel_key(r["key"]) if hasattr(pg, "parse_boxel_key") else None
        if pn is not None and pn.mc in mcs:
            seen[pn.mc] = seen.get(pn.mc, 0) + 1
    return max(seen, key=lambda k: seen[k]) if seen else mcs[0]


def build_galaxy(db: Database, archive: fl.Archive, live: Dict[str, Any],
                 mc: Optional[int] = None, days: Optional[float] = None,
                 now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    since = now - days * 86400 if days else None
    out: Dict[str, Any] = {"generated": now, "days": days}
    path = flight_path(archive, since)
    out["path"] = path
    out["carrier"] = carrier_path(archive)
    jumps = [p for p in path if p["kind"] == "jump"]
    out["stats"] = {"jumps": len(jumps), "ly": _r(sum(p["ly"] or 0 for p in jumps), 0),
                    "systems": len({p["name"] for p in path}),
                    "first": path[0]["t"] if path else None, "last": path[-1]["t"] if path else None}
    sysl = live.get("system") or {}
    pos = sysl.get("pos")
    out["you"] = {"name": sysl.get("name"), "x": _r(pos[0]), "y": _r(pos[1]), "z": _r(pos[2])} if pos else None
    out["navroute"] = [{"name": h.get("name"), "x": _r(h["pos"][0]), "y": _r(h["pos"][1]),
                        "z": _r(h["pos"][2])} for h in live.get("navroute") or [] if h.get("pos")]
    # survey spheres
    s = db.survey() if db.has_table("survey") else None
    spheres = []
    for sp in (db.spheres() if db.has_table("spheres") else []):
        spheres.append({"id": sp["id"], "label": sp["label"], "x": sp["cx"], "y": sp["cy"], "z": sp["cz"],
                        "r": sp["radius"], "closed": sp["closed"]})
    out["spheres"] = spheres
    active = None
    if s is not None and s["cx"] is not None:
        active = {"label": s["start_system"], "x": s["cx"], "y": s["cy"], "z": s["cz"],
                  "r": s["radius"] or 0.0, "active": bool(s["active"]),
                  "masscodes": [int(m) for m in str(s["masscodes"] or "").split(",") if m.strip().isdigit()]}
    out["active"] = active
    if active and active["r"]:
        mcs = active["masscodes"] or [1]
        use = mc if mc is not None and mc in range(8) else _busiest_mc(db, active, mcs)
        out["mc"] = use
        out["boxels"] = sphere_boxels(db, (active["x"], active["y"], active["z"]), active["r"], use)
        out["boxel_size"] = _plugin().procgen.boxel_size(use)
    else:
        out["boxels"] = []
    # known systems
    rows = db.query("SELECT name, id64, x, y, z, visited, fss_complete, sources FROM systems "
                    "WHERE x IS NOT NULL") if db.has_table("systems") else []
    out["systems"] = [{"n": r["name"], "id": r["id64"], "x": _r(r["x"]), "y": _r(r["y"]), "z": _r(r["z"]),
                       "v": 1 if r["visited"] else 0, "f": 1 if r["fss_complete"] else 0,
                       "u": 1 if (r["visited"] and not Database.known_sources(r)) else 0}
                      for r in rows]
    # finds worth a symbol
    finds: Dict[Any, Dict[str, Any]] = {}
    if db.has_table("signals"):
        for r in db.query("SELECT g.sys_id64, g.kind, s.name, s.x, s.y, s.z FROM signals g "
                          + Database._BEST_SYS + "g.sys_id64 WHERE g.kind IN (%s)"
                          % ",".join("?" * len(FIND_KINDS)), FIND_KINDS):
            if r["x"] is None:
                continue
            f = finds.setdefault(r["sys_id64"], {"name": r["name"], "id": r["sys_id64"], "x": _r(r["x"]),
                                                 "y": _r(r["y"]), "z": _r(r["z"]), "kinds": []})
            k = "brain" if "Brain" in r["kind"] else ("guardian" if "guardian" in r["kind"] else "nonhuman")
            if k not in f["kinds"]:
                f["kinds"].append(k)
    out["finds"] = list(finds.values())
    return out
