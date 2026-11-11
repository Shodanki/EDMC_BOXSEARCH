# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Builds the JSON snapshots the web interface draws.

All maths that already exists in the plugin is imported, not re-written:
sysroute (Kepler positions, route order), biopredict (genus forecast),
deepspace (fuel model, scoopable), procgen (boxel names).
"""

from __future__ import annotations

import calendar
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .data import MAIN, Database, _json

G0 = 9.80665
ATM = 101325.0
LS_PER_M = 1.0 / 299792458.0

_plugin = None   # lazily imported plugin modules


def plugin():
    """The plugin's pure modules. Imported late so config can set sys.path."""
    global _plugin
    if _plugin is None:
        import sys
        # the plugin folder is read-only for us: no __pycache__ written there
        keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
        try:
            import biopredict  # type: ignore
            import deepspace  # type: ignore
            import procgen  # type: ignore
            import sysroute  # type: ignore
            try:
                import surfacenav  # type: ignore   # plugin 4.5+
            except ImportError:
                surfacenav = None
            try:
                import shells  # type: ignore   # plugin 4.6+, info levels 4.7+
                if not hasattr(shells, "info_level"):
                    shells = None
            except ImportError:
                shells = None
        finally:
            sys.dont_write_bytecode = keep

        class _P:
            pass
        p = _P()
        p.sysroute, p.biopredict, p.deepspace, p.procgen = \
            sysroute, biopredict, deepspace, procgen
        p.surfacenav = surfacenav
        p.shells = shells
        _plugin = p
    return _plugin


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

Q_ESTIMATE = 10      # sysdb: a position derived from name/id64 (boxel centre)


def info_level(row: Any, regions: Optional[Dict[str, list]]) -> Tuple[str, List[str]]:
    """I1 information level of a system row: known / inhabited / checked
    (asked, nobody has it = 'in no database') / unchecked (nobody asked).
    Same rule as the plugin briefing (shells.info_level)."""
    if row is None:
        return "unchecked", []
    srcs = set((row["sources"] or "").split(","))
    pos = None
    q = row["quality"] if "quality" in row.keys() else None
    if row["x"] is not None and (q is None or q > Q_ESTIMATE):
        pos = (row["x"], row["y"], row["z"])
    sh = plugin().shells
    if sh is None:                         # older plugin: the old rule
        return ("known" if Database.known_sources(row) else "checked"), []
    return sh.info_level(srcs, pos, regions or {})

def _r(v: Optional[float], nd: int = 2) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _dist3(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def body_class(row) -> str:
    """Display class: planet class, star type or 'Belt' / 'Barycentre'."""
    if row["kind"] == "Star":
        return row["star_type"] or "Star"
    return row["planet_class"] or row["kind"] or "?"


# Colour category for the 3D view and the legend - kept rule based and small
def colour_key(row) -> str:
    if row["kind"] == "Star":
        st = (row["star_type"] or "?").upper()
        if st.startswith(("D", "N", "H")) or st in ("SUPERMASSIVEBLACKHOLE",):
            return "star-remnant"
        return "star-" + (st[:1] if st[:1] in "OBAFGKMLTY" else "x").lower()
    pc = (row["planet_class"] or "").lower()
    if "earthlike" in pc:
        return "elw"
    if "water world" in pc:
        return "water"
    if "ammonia" in pc:
        return "ammonia"
    if "gas giant" in pc:
        return "gas"
    if "icy" in pc:
        return "icy"
    if "metal" in pc:
        return "metal"
    if "rocky ice" in pc:
        return "rockyice"
    if "rocky" in pc:
        return "rocky"
    return "other"


def is_scoopable(star_type: Optional[str]) -> bool:
    return bool(plugin().deepspace.is_scoopable(star_type))


def boost_kind(star_type: Optional[str]) -> Optional[str]:
    """B8: a jet cone to supercharge the FSD - neutron star (x4) or white dwarf (x1.5)."""
    s = (star_type or "").strip()
    if s == "N":
        return "neutron"
    if s.startswith("D") and len(s) <= 3 and s[1:].isalpha() or s == "D":
        return "white_dwarf"
    return None


# ---------------------------------------------------------------------------
# system (TAKTIK)
# ---------------------------------------------------------------------------

def _orbit_points(row, parent_pos: Sequence[float], n: int = 72
                  ) -> Optional[List[List[float]]]:
    sma = row["sma"]
    if not sma:
        return None
    sr = plugin().sysroute
    pts = []
    for k in range(n + 1):
        x, y, z = sr.orbital_position(sma, row["ecc"] or 0.0, row["inc"] or 0.0,
                                      row["peri"] or 0.0, row["node"] or 0.0,
                                      360.0 * k / n)
        pts.append([round(parent_pos[0] + x, 3), round(parent_pos[1] + y, 3),
                    round(parent_pos[2] + z, 3)])
    return pts


def _rings(row, hotspots: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """Rings with class, width - and the hotspots you mapped in each (DSS)."""
    out = []
    for r in _json(row["rings_json"], []) or []:
        out.append({"name": r.get("name"), "cls": r.get("cls"),
                    "hotspots": (hotspots or {}).get(r.get("name") or "", []),
                    "mass": r.get("mass"),
                    "inner_km": _r((r.get("inner") or 0) / 1000.0, 0),
                    "outer_km": _r((r.get("outer") or 0) / 1000.0, 0),
                    "belt": "Belt" in (r.get("name") or "")})
    return out


# M10: what the FSS lists as a place to go - not the passing signal sources
POI_TYPES = {
    "FleetCarrier": "carrier", "SquadronCarrier": "carrier",
    "NavBeacon": "beacon", "ResourceExtraction": "extraction", "Titan": "station",
    "Outpost": "station", "Installation": "station", "Megaship": "station",
    "StationCoriolis": "station", "StationONeilCylinder": "station", "StationONeilOrbis": "station",
    "StationBernalSphere": "station", "StationMegaShip": "station", "StationAsteroid": "station",
    "Station": "station",
}
POI_ORDER = {"station": 0, "settlement": 1, "carrier": 2, "extraction": 3, "beacon": 4}


def nav_beacon(archive: Any, id64: int) -> Optional[Dict[str, Any]]:
    """The last NavBeaconScan in this system: every body is known from the
    beacon (data, but no discovery and no exploration data of your own)."""
    if archive is None:
        return None
    try:
        hit = None
        for e in archive.events():
            if e.get("event") == "NavBeaconScan" and e.get("SystemAddress") == id64:
                hit = e
    except Exception:
        return None
    if hit is None:
        return None
    return {"ts": hit.get("timestamp"), "bodies": hit.get("NumBodies")}


def system_poi(db: Database, id64: int, archive: Any = None) -> List[Dict[str, Any]]:
    """
    M10: points of interest of one system, from your own journals and the
    plugin database - stations, outposts, installations and megaships,
    settlements (with their body), fleet carriers seen there, nav beacons
    and extraction sites. Latest sighting per name; docking adds the
    distance from the arrival star.
    """
    pois: Dict[Tuple[str, str], Dict[str, Any]] = {}
    evs = []
    if archive is not None:
        try:
            archive.refresh()
            evs = [e for e in archive.events() if e.get("SystemAddress") == id64]
        except Exception:
            evs = []
    for e in evs:
        ev = e.get("event")
        if ev == "FSSSignalDiscovered":
            st = e.get("SignalType") or ""
            kind = POI_TYPES.get(st) or ("station" if e.get("IsStation") and st != "FleetCarrier" else None)
            if not kind:
                continue
            name = e.get("SignalName_Localised") or e.get("SignalName") or ""
            if not name or name.startswith("$"):
                continue
            p = pois.setdefault((kind, name), {"kind": kind, "type": st, "name": name})
            p["seen"] = max(p.get("seen") or "", e.get("timestamp") or "")
        elif ev == "Docked":
            name = e.get("StationName_Localised") or e.get("StationName") or ""
            st = e.get("StationType") or ""
            kind = POI_TYPES.get(st, "station")
            if not name:
                continue
            p = pois.setdefault((kind, name), {"kind": kind, "type": st, "name": name})
            p["seen"] = max(p.get("seen") or "", e.get("timestamp") or "")
            p["docked"] = True
            if e.get("DistFromStarLS") is not None:
                p["dist_ls"] = _r(e.get("DistFromStarLS"), 0)
    srow = db.system_by_id64(id64)
    sysname = srow["name"] if srow is not None else ""
    try:
        rows = db.settlements_of(id64)
    except Exception:
        rows = []
    for r in rows:
        body = r["body_name"] or ""
        short = body[len(sysname):].strip() if sysname and body.startswith(sysname) else body
        pois[("settlement", (r["label"] or "") + "@" + body)] = {
            "kind": "settlement", "type": "Settlement", "name": r["label"] or "?", "body": short,
            "body_name": body, "lat": _r(r["lat"], 4), "lon": _r(r["lon"], 4), "seen": r["ts"]}
    # a carrier seen in the FSS ("NAME K7Q-12Z") and docked at ("K7Q-12Z")
    # is one carrier: one line with name and callsign (11.11.)
    from .carriers import is_callsign, parse_signal
    merged: Dict[str, Dict[str, Any]] = {}
    for key in [k for k in pois if k[0] == "carrier"]:
        p = pois.pop(key)
        nm = p["name"]
        cs = nm if is_callsign(nm) else (parse_signal(nm) or {}).get("callsign")
        if not cs:
            pois[key] = p
            continue
        m = merged.get(cs)
        if m is None:
            merged[cs] = p
            continue
        for k, v in p.items():
            if k == "name":
                if len(v) > len(m["name"]):
                    m["name"] = v                      # the one with the name
            elif k == "seen":
                m["seen"] = max(m.get("seen") or "", v or "")
            elif m.get(k) is None:
                m[k] = v
    for cs, p in merged.items():
        pois[("carrier", cs)] = p
    out = list(pois.values())
    # by kind; carriers come and go - the latest sightings first
    carriers = sorted((p for p in out if p["kind"] == "carrier"),
                      key=lambda p: p.get("seen") or "", reverse=True)
    rest = sorted((p for p in out if p["kind"] != "carrier"),
                  key=lambda p: (POI_ORDER.get(p["kind"], 9), p["name"]))
    before = [p for p in rest if POI_ORDER.get(p["kind"], 9) < POI_ORDER["carrier"]]
    after = [p for p in rest if POI_ORDER.get(p["kind"], 9) > POI_ORDER["carrier"]]
    return before + carriers + after


def build_system(db: Database, id64: int, live: Optional[Dict[str, Any]] = None,
                 filters: Sequence[str] = ("todo",),
                 now: Optional[float] = None,
                 cost_model: Any = None,
                 order_model: Any = None,
                 skip_arrival: bool = False,
                 archive: Any = None,
                 fid: Optional[str] = None) -> Dict[str, Any]:
    """Everything TAKTIK needs: bodies at Kepler positions, orbits, route, fix.

    fid (C1): the commander playing - scans, maps, first discoveries and
    species are his own, what is known about the bodies is shared."""
    p = plugin()
    sr = p.sysroute
    now = time.time() if now is None else now
    srow = db.system_for(db.system_by_id64(id64), fid)
    rows = db.bodies_for(id64, fid)
    name = srow["name"] if srow is not None else None
    if not name and rows:
        # derive system name from the main star's name
        star = min(rows, key=lambda r: r["body_id"])
        name = star["name"]
    out: Dict[str, Any] = {
        "id64": id64, "name": name, "known": srow is not None,
        "star_class": srow["star_class"] if srow is not None else None,
        "pos": [srow["x"], srow["y"], srow["z"]] if srow is not None and srow["x"] is not None else None,
        "body_count": srow["body_count"] if srow is not None else None,
        "fss_complete": bool(srow["fss_complete"]) if srow is not None else False,
        "visited": bool(srow["visited"]) if srow is not None else False,
        "known_sources": Database.known_sources(srow),
        "info_level": info_level(srow, db.shell_regions())[0],
        "bodies": [], "route": None, "fix": None, "generated": now,
        # C1: other commanders on this PC who have been here
        "also_by": db.explorers(id64, but=fid) if fid else [],
    }
    if not rows:
        out["fix"] = _fix(out, {}, live, now)
        return out

    # ring hotspots by ring name (the journal knows no position in the ring)
    hs_by_ring: Dict[str, List[Dict[str, Any]]] = {}
    try:
        for h in db.hotspots_of(id64):
            hs_by_ring.setdefault(h["body_name"] or "", []).append(
                {"material": h["label"] or h["material"], "count": h["count"]})
    except Exception:
        hs_by_ring = {}
    bodies = sr.bodies_from_rows(rows, now=now)
    for b in bodies.values():
        b.short = sr.shorten(b.name, name or "")
    by_row = {r["body_id"]: r for r in rows}
    for bid, b in bodies.items():
        b.rings = bool(by_row[bid]["ring_classes"] or by_row[bid]["rings_json"])

    # bio hints exactly as the plugin builds them
    model = None
    try:
        model = p.biopredict.BioModel.learn(db.bio_training_rows())
        for b in bodies.values():
            b.bio_hint = model.hint(by_row[b.body_id])
    except Exception:
        model = None

    # route in the plugin's order (plan_route resolves positions as well)
    flist = list(filters) or ["todo"]
    # order with the model the plugin uses, times with the measured one
    cm = cost_model or sr.DEFAULT_MODEL
    om = order_model or cm
    # R3: arrived on board a carrier in a system you had not explored - the
    # route of this visit starts at the carrier's body, the arrival star left
    # out (the plugin decided it at the arrival; same rule, same data)
    start, route_from = (0.0, 0.0, 0.0), None
    r3 = db.route_start(fid, id64) if fid else None
    if r3 and hasattr(sr, "start_at_body"):
        at = sr.start_at_body(bodies, r3[0])
        if at:
            start, skip_arrival = at, True
            route_from = {"body_id": r3[0], "name": r3[1],
                          "short": sr.shorten(r3[1], name or "") if r3[1] else None}
    route = sr.plan_route(name or "", bodies, model=om, filters=flist,
                          skip_arrival=skip_arrival, start=start)
    full = False
    if not route.stops and "all" not in flist:
        route = sr.plan_route(name or "", bodies, model=om, filters=["all"],
                              skip_arrival=skip_arrival, start=start)
    if om is not cm:
        _recost(route, cm)
        full = True
    if not any(b.pos for b in bodies.values()):
        sr.resolve_positions(bodies)

    for bid, b in sorted(bodies.items()):
        r = by_row[bid]
        pos = list(b.pos or (0.0, 0.0, 0.0))
        parent = bodies.get(b.parent_id) if b.parent_id is not None else None
        if parent is not None and parent.pos is not None:
            ppos = parent.pos
        else:
            ppos = (pos[0] - b.rel[0], pos[1] - b.rel[1], pos[2] - b.rel[2])
        radius = r["radius"]
        out["bodies"].append({
            "body_id": bid, "name": b.name, "short": b.short,
            "kind": r["kind"], "cls": body_class(r), "colour": colour_key(r),
            "parent_id": b.parent_id,
            "pos": [round(v, 3) for v in pos],
            # where the orbit is centred (parent body or unscanned barycentre)
            "ppos": [round(v, 3) for v in ppos],
            "orbit": _orbit_points(r, ppos) if r["kind"] != "Ring" else None,
            "radius_km": _r(radius / 1000.0, 1) if radius else None,
            "radius_ls": (radius * LS_PER_M) if radius else None,
            "arrival_ls": _r(r["arrival_ls"], 1),
            "landable": bool(r["landable"]),
            "terraform": r["terraform"] or "",
            "rings": _rings(r, hs_by_ring),
            "group": sr.group_label(b), "moon": sr.is_moon(b),
            "flags": {
                "first": r["was_discovered"] == 0,
                "first_map": r["was_mapped"] == 0 and r["kind"] == "Planet",
                "mapped": bool(r["mapped"]),
                "footfall": r["was_footfalled"] == 0 and bool(r["landable"]),
                "bio": int(r["sig_bio"] or 0),
                "geo": int(r["sig_geo"] or 0),
                "organics": int(r["organics"] or 0),
                "valuable": (r["planet_class"] in sr.VALUABLE
                             or (r["terraform"] or "") == "Terraformable"),
                "wants_dss": b.wants_dss, "wants_bio": b.wants_bio,
            },
            "bio_hint": b.bio_hint,
        })

    out["bio"] = bio_list(db, id64, rows, out["bodies"])
    # M10: stations, settlements, carriers, beacons - and a mark on the body
    try:
        out["poi"] = system_poi(db, id64, archive)
    except Exception:
        out["poi"] = []
    out["nav_beacon"] = nav_beacon(archive, id64)
    by_body = {}
    for p in out["poi"]:
        if p["kind"] == "settlement":
            by_body[p["body_name"]] = by_body.get(p["body_name"], 0) + 1
    if by_body:
        for b in out["bodies"]:
            n = by_body.get(b.get("name"))
            if n:
                b["flags"]["settlement"] = n
    from . import science
    try:
        out["report"] = science.system_report([dict(r) for r in rows], out)
    except Exception:                       # a report must never cost the map
        out["report"] = []

    done_ids = {r["body_id"] for r in rows if r["route_done"]}
    legs = []
    next_idx = None
    prev = start
    for i, s in enumerate(route.stops, 1):
        b = s.body
        done = b.body_id in done_ids        # the plugin's own route ticks
        if not done and next_idx is None and not full:
            next_idx = i
        legs.append({
            "n": i, "body_id": b.body_id, "short": b.short,
            "from": [round(v, 3) for v in prev], "to": [round(v, 3) for v in b.pos],
            "leg_ls": round(s.leg_ls, 1), "leg_min": round(s.leg_s / 60.0, 1),
            "cum_min": round(s.cum_s / 60.0, 1),
            "work": (s.work + (" | " + b.bio_hint if b.bio_hint and b.wants_bio else "")),
            "group": s.group, "group_start": s.group_start, "moon": s.is_moon,
            "done": done,
            "label": "LEG %d · %.0f LS · ~%.0f min" % (i, s.leg_ls, max(1.0, s.leg_s / 60.0)),
        })
        prev = b.pos
    out["route"] = {
        "filters": flist, "full_tour": full, "legs": legs, "next": next_idx,
        "start": route_from,
        "summary": route.summary(), "total_ls": round(route.total_ls, 0),
        "total_min": round(route.total_s / 60.0, 1), "skipped": route.skipped,
        "cost_model": cm.as_dict(),
        "calibrated": cm is not sr.DEFAULT_MODEL,
    }
    out["fix"] = _fix(out, by_row, live, now)
    return out


def bio_list(db: Database, id64: int, rows, bodies: List[Dict[str, Any]]
             ) -> List[Dict[str, Any]]:
    """
    TAKTIK: every body of the system with biology - analysed species (from
    the ScanOrganic history), species being sampled (samples taken, from
    the surface marks), genera the DSS named but nobody has started, and
    the forecast for bodies only the FSS has counted.
    """
    import json as _json
    p = plugin()
    short = {b["body_id"]: b for b in bodies}
    out: List[Dict[str, Any]] = []
    def col(r, k):
        try:
            return r[k]
        except (IndexError, KeyError):       # older plugin database
            return None

    for r in sorted(rows, key=lambda r: col(r, "arrival_ls") or 0.0):
        sig = int(col(r, "sig_bio") or 0)
        try:
            analysed = _json.loads(col(r, "bio_species") or "[]")
        except (TypeError, ValueError):
            analysed = []
        genera = [g for g in (col(r, "genuses") or "").split(",") if g]
        if not sig and not analysed and not genera:
            continue
        species: List[Dict[str, Any]] = []
        done = set()
        for a in analysed:
            nm = a.get("species") or "?"
            if nm not in done:
                done.add(nm)
                species.append({"species": nm, "genus": a.get("genus"), "state": "done",
                                "samples": 3})
        if p.surfacenav and r["name"]:
            st = p.surfacenav.body_state([dict(m) for m in db.surface_marks(id64, r["name"])])
            for s in st["species"]:
                if not s["analysed"] and s["species"] not in done:
                    species.append({"species": s["species"], "genus": s["genus"],
                                    "state": "open", "samples": s["samples"]})
        started = {s["genus"] for s in species if s["genus"]}
        b = short.get(r["body_id"]) or {}
        out.append({
            "body_id": r["body_id"], "short": b.get("short") or r["name"],
            "arrival_ls": _r(col(r, "arrival_ls"), 0), "signals": sig,
            "species": species,
            "missing": [g for g in genera if g not in started],
            "hint": None if genera else b.get("bio_hint"),
        })
    return out


def _recost(route: Any, cm: Any) -> None:
    """Re-time the legs of a planned route with another cost model."""
    cum = 0.0
    for s in route.stops:
        s.leg_s = cm.hop(s.leg_ls)
        s.work_s = cm.work(s.body)
        cum += s.leg_s + s.work_s
        s.cum_s = cum
    route.model = cm


_FIX_EVENTS = ("ApproachBody", "SupercruiseExit", "Touchdown", "Liftoff",
               "SAAScanComplete", "ScanOrganic", "Disembark", "Embark",
               "ApproachSettlement", "Status", "FSDJump", "Location", "CarrierJump")


def _fix(system: Dict[str, Any], by_row: Dict[int, Any],
         live: Optional[Dict[str, Any]], now: float) -> Optional[Dict[str, Any]]:
    """The last known reference point - never an exact ship position."""
    if not live:
        return None
    cur = (live.get("system") or {})
    if cur.get("id64") != system.get("id64"):
        return None
    fx = live.get("last_fix") or {}
    body_id = fx.get("body_id")
    body_name = fx.get("body")
    if fx.get("system_id64") not in (None, system.get("id64")):
        body_id, body_name = None, None
    if body_id is None and body_name:
        # Status.json names the body but carries no BodyID
        for b in system["bodies"]:
            if b["name"] == body_name:
                body_id = b["body_id"]
                break
    if body_id is None:
        # after a jump: the arrival star
        star = None
        for b in system["bodies"]:
            if b["kind"] == "Star" and (b["arrival_ls"] or 0) <= 0.01:
                star = b
                break
        if star is None and system["bodies"]:
            star = min(system["bodies"], key=lambda b: b["body_id"])
        if star is not None:
            body_id, body_name = star["body_id"], star["name"]
        event = fx.get("event") or "FSDJump"
    else:
        event = fx.get("event")
    pos = None
    short = body_name
    for b in system["bodies"]:
        if b["body_id"] == body_id:
            pos, short = b["pos"], b["short"]
            break
    ts = fx.get("ts") or (cur.get("ts"))
    age = (now - ts) / 60.0 if ts else None
    # English label for API users; the browser builds its own in the
    # display language from short + age_min
    label = "LAST FIX · %s" % (short or "?")
    if age is not None:
        label += " · %d min ago" % max(0, int(age))
    return {"body_id": body_id, "body": body_name, "short": short, "event": event,
            "pos": pos, "ts": ts, "age_min": _r(age, 1), "label": label,
            "lat": fx.get("lat"), "lon": fx.get("lon"), "alt": fx.get("alt"),
            "exact": False}


# ---------------------------------------------------------------------------
# body (PLANET)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ATLAS (plugin 4.3): signals on bodies, materials picked up
# ---------------------------------------------------------------------------

def sig_label(kind: str, label: Optional[str]) -> str:
    if kind == "genus:Brain Trees":
        return "Brain Trees"
    if kind == "mining_location":
        return "Planetary Mining Location"
    if kind.startswith("genus:"):
        return "Bio: " + (label or kind[6:])
    if kind.startswith("codex:"):
        return "Codex: " + (label or kind[6:])
    return label or kind


def sig_tone(kind: str) -> str:
    if kind in ("site:nonhuman", "thargoid", "uss:nonhuman"):
        return "violet"
    if kind in ("site:guardian", "guardian"):
        return "cyan"
    if kind == "genus:Brain Trees" or kind == "mining_location":
        return "amber"
    return "green"


# genera are shown in the bio block already; Brain Trees stay - engineering
_SIG_SKIP = ("biological", "geological")


def body_signals(rows) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        k = r["kind"]
        if k in _SIG_SKIP or (k.startswith("genus:") and k != "genus:Brain Trees"):
            continue
        out.append({"kind": k, "label": sig_label(k, r["label"]), "count": r["count"],
                    "tone": sig_tone(k)})
    out.sort(key=lambda x: (x["tone"] != "violet", -(x["count"] or 0)))
    return out


def system_signals(rows) -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = r["kind"]
        if k.startswith("genus:") and k != "genus:Brain Trees":
            continue
        a = agg.setdefault(k, {"kind": k, "label": sig_label(k, r["label"]), "bodies": 0,
                               "total": 0, "tone": sig_tone(k)})
        a["bodies"] += 1
        a["total"] += int(r["count"] or 1)
    return sorted(agg.values(), key=lambda x: (x["tone"] != "violet", -x["total"]))


ATLAS_VIEWS = ("rings", "signals", "materials", "finds", "bio", "systems")
SYSTEM_STATES = ("unvisited", "visited", "surveyed", "only_us", "absent")


def survey_rows(db: Database) -> Dict[str, Any]:
    """
    M6/M14: every system of the active survey sphere with its state - known
    to the online sources but not visited yet, visited, surveyed (FSS
    complete) - plus the names checked in the galaxy map and found not to
    exist. "only_us": no online source knows the system. Read only, from
    the plugin database.
    """
    s = db.survey()
    out: Dict[str, Any] = {"survey": None, "systems": []}
    if s is None or s["cx"] is None:
        return out
    c = (s["cx"], s["cy"], s["cz"])
    out["survey"] = {"start_system": s["start_system"], "center": list(c), "radius": s["radius"],
                     "active": bool(s["active"]), "started": s["started"]}
    regions = db.shell_regions()
    for r in db.systems_in_sphere(c[0], c[1], c[2], s["radius"] or 0.0):
        srcs = Database.known_sources(r)
        state = "surveyed" if r["fss_complete"] else "visited" if r["visited"] else "unvisited"
        level = info_level(r, regions)[0]
        out["systems"].append({
            "name": r["name"], "id64": r["id64"], "x": r["x"], "y": r["y"], "z": r["z"],
            "from_centre_ly": _r(math.dist((r["x"], r["y"], r["z"]), c), 2),
            # I1: "known to no online source" only where they were asked
            "state": state, "only_us": level == "checked", "level": level, "sources": srcs,
            "bodies": r["body_count"]})
    for r in db.absent_all():
        out["systems"].append({"name": r["name"], "id64": None, "x": None, "y": None, "z": None,
                               "from_centre_ly": None, "state": "absent", "only_us": False,
                               "sources": [], "bodies": None, "checked": r["ts"]})
    return out


def _atlas_systems(db: Database, kind: Optional[str], near: Optional[Sequence[float]],
                   limit: int, q: Optional[str], max_ly: Optional[float]) -> Dict[str, Any]:
    """ATLAS SYSTEMS (M6): the survey sphere's systems, nearest first."""
    text = (q or "").strip().lower()
    items = []
    for r in survey_rows(db)["systems"]:
        if kind == "only_us" and not r["only_us"]:
            continue
        if kind and kind != "only_us" and r["state"] != kind:
            continue
        if text and text not in r["name"].lower():
            continue
        it: Dict[str, Any] = {"system": r["name"], "id64": r["id64"], "body": None, "count": None,
                              "key": r["state"], "only_us": r["only_us"], "sources": r["sources"],
                              "bodies": r["bodies"], "dist_ly": None, "rel": None}
        if near and r["x"] is not None:
            dx, dy, dz = r["x"] - near[0], r["y"] - near[1], r["z"] - near[2]
            it["dist_ly"] = _r(math.sqrt(dx * dx + dy * dy + dz * dz), 1)
            it["rel"] = [_r(dx, 2), _r(dy, 2), _r(dz, 2)]
        if max_ly and near and (it["dist_ly"] is None or it["dist_ly"] > max_ly):
            continue
        items.append(it)
    items.sort(key=lambda x: (x["dist_ly"] if x["dist_ly"] is not None else 1e9, x["system"]))
    for it in items:
        it["body_short"] = ""
    return {"view": "systems", "kind": kind, "q": q or "", "max_ly": max_ly,
            "total": len(items), "items": items[:limit]}


def survey_export(db: Database, fmt: str) -> Any:
    """M14: the survey sphere as CSV (text) or JSON (dict)."""
    data = survey_rows(db)
    if fmt == "json":
        return data
    import csv
    import io as _io
    buf = _io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["name", "id64", "x", "y", "z", "from_centre_ly", "state", "only_us",
                "sources", "bodies"])
    for r in data["systems"]:
        w.writerow([r["name"], r["id64"] or "", r["x"] if r["x"] is not None else "",
                    r["y"] if r["y"] is not None else "", r["z"] if r["z"] is not None else "",
                    r["from_centre_ly"] if r["from_centre_ly"] is not None else "", r["state"],
                    "1" if r["only_us"] else "0", "|".join(r["sources"]),
                    r["bodies"] if r["bodies"] is not None else ""])
    return buf.getvalue()
# M1: Horizons-era organics are logged with the composition scanner (codex)
# only - the genetic sampler never analyses them, so a body whose only open
# signals are these counts as done. Assumption, to confirm in game.
CODEX_ONLY_GENERA = {"Brain Trees", "Anemone", "Bark Mounds", "Crystalline Shards",
                     "Sinuous Tubers", "Amphora Plant"}


def _bio_item(r) -> Dict[str, Any]:
    """open/done of one body's bio signals (ATLAS BIOLOGY, M1)."""
    sig, done_n = int(r["sig_bio"] or 0), int(r["organics"] or 0)
    analysed = [a for a in (_json(r["bio_species"], []) or []) if isinstance(a, dict)]
    got = {a.get("genus") for a in analysed if a.get("genus")}
    genera = [g.strip() for g in (r["genuses"] or "").split(",") if g.strip()]
    missing = [g for g in genera if g not in got]
    codex_only = [g for g in missing if g in CODEX_ONLY_GENERA]
    open_n = max(0, sig - done_n - len(codex_only))
    return {"key": "open" if open_n else "done", "signals": sig,
            "analysed": min(done_n, sig), "open": open_n,
            "missing": [g for g in missing if g not in CODEX_ONLY_GENERA],
            "codex_only": codex_only,
            "species": sorted({a.get("species") for a in analysed if a.get("species")})}


def _ring_class(v: Optional[str]) -> str:
    return (v or "").replace("eRingClass_", "")


def build_atlas(db: Database, view: str, kind: Optional[str],
                near: Optional[Sequence[float]], limit: int = 40,
                q: Optional[str] = None, max_ly: Optional[float] = None) -> Dict[str, Any]:
    """
    ATLAS: everything found of one kind, nearest system first.

    rings     ring hotspots (material, count, ring class)
    signals   body signals, DSS genera, codex and pickup-marked sites
    materials materials picked up, per body
    finds     ground finds with latitude/longitude (codex, analysed species,
              settlements, screenshots)

    `q` filters on system, body and label; `max_ly` drops everything farther
    away (far from the bubble, finds 2000 ly back would swamp list and map;
    places without coordinates stay out too then). Every item carries id64 and, when
    the body is known, body_id - the browser opens PLANET with them - and
    `rel` (ly from you: x, z in the galactic plane, y up) for the small map.
    """
    view = view if view in ATLAS_VIEWS else "signals"
    if view == "systems":
        return _atlas_systems(db, kind, near, limit, q, max_ly)
    rows = {"rings": db.atlas_rings, "materials": db.atlas_materials,
            "finds": db.atlas_finds, "bio": db.atlas_bio}.get(view, db.atlas_signals)(kind)
    need = text = None
    if q:
        text = q.strip().lower()
    items = []
    for r in rows:
        keys = r.keys()
        sysname = r["sys_name"] or str(r["sys_id64"])
        body = r["body_name"] if "body_name" in keys else None
        it: Dict[str, Any] = {"system": sysname, "id64": r["sys_id64"], "body": body,
                              "count": r["count"], "dist_ly": None, "rel": None}
        if view == "materials":
            it.update(key=r["material"], label=r["label"], category=r["category"],
                      last=(r["last"] or "")[:10])
        elif view == "rings":
            it.update(key=r["material"], label=r["label"] or r["material"],
                      ring_class=_ring_class(r["ring_class"]))
            if r["body_id"] is not None:
                it["body_id"] = r["body_id"]
        elif view == "bio":
            it.update(_bio_item(r), label=None, count=None, body_id=r["body_id"])
            if kind in ("open", "done") and it["key"] != kind:
                continue
        elif view == "finds":
            it.update(key=r["kind"], label=r["label"], detail=r["detail"],
                      lat=_r(r["lat"], 4), lon=_r(r["lon"], 4), last=(r["last"] or "")[:10])
        else:
            it.update(key=r["kind"], label=sig_label(r["kind"], r["label"]))
            if r["body_id"] is not None and r["body_id"] >= 0:
                it["body_id"] = r["body_id"]
        if text and not any(text in str(v or "").lower()
                            for v in (sysname, body, it.get("label"), it.get("detail"))):
            continue
        if near and r["x"] is not None:
            dx, dy, dz = r["x"] - near[0], r["y"] - near[1], r["z"] - near[2]
            it["dist_ly"] = _r(math.sqrt(dx * dx + dy * dy + dz * dz), 1)
            it["rel"] = [_r(dx, 2), _r(dy, 2), _r(dz, 2)]
        if max_ly and near and (it["dist_ly"] is None or it["dist_ly"] > max_ly):
            continue
        items.append(it)
    items.sort(key=lambda x: (x["dist_ly"] if x["dist_ly"] is not None else 1e9,
                              -(x["count"] or 0)))
    totals = None
    if view == "bio":
        # M1: the sums over everything matching (not just the shown page)
        totals = {"bodies": len(items),
                  "bodies_open": sum(1 for it in items if it["open"]),
                  "signals": sum(it["signals"] for it in items),
                  "analysed": sum(it["analysed"] for it in items),
                  "open": sum(it["open"] for it in items)}
    out = items[:limit]
    # body names -> body_id, so a click can open the datasheet
    need = [it for it in out if "body_id" not in it and it.get("body")]
    if need:
        ids = db.body_ids(it["id64"] for it in need)
        for it in need:
            bid = ids.get((it["id64"], it["body"]))
            if bid is not None:
                it["body_id"] = bid
    for it in out:
        sysn = it["system"] or ""
        b = it.get("body") or ""
        it["body_short"] = b[len(sysn):].strip() if sysn and b.startswith(sysn) else b
    res = {"view": view, "kind": kind, "q": q or "", "max_ly": max_ly,
           "total": len(items), "items": out}
    if totals is not None:
        res["totals"] = totals
    return res


def build_atlas_kinds(db: Database, view: str) -> List[Dict[str, Any]]:
    """The second picker: what kinds exist in one atlas view, with counts."""
    out = []
    if view == "systems":
        rows = survey_rows(db)["systems"]
        n = {k: 0 for k in SYSTEM_STATES}
        for r in rows:
            n[r["state"]] += 1
            n["only_us"] += 1 if r["only_us"] else 0
        return [{"key": k, "label": k, "count": n[k]} for k in SYSTEM_STATES if n[k]]
    if view == "bio":
        n = {"open": 0, "done": 0}
        for r in db.atlas_bio():
            n[_bio_item(r)["key"]] += 1
        return [{"key": k, "label": k, "count": n[k]} for k in ("open", "done") if n[k]]
    for r in db.atlas_kinds(view):
        label = r["label"] or r["key"]
        if view == "signals":
            label = sig_label(r["key"], r["label"])
        elif view == "materials" and r["category"]:
            label = "%s · %s" % (r["category"], label)
        out.append({"key": r["key"], "label": label, "count": r["n"]})
    return out


_PROSPECTS: Dict[str, Any] = {"key": None, "pros": {}}


def _ring_prospects(archive: Any) -> Dict[str, Dict[str, Any]]:
    """Prospecting per ring from the journals of EVERY commander (the
    knowledge is shared, only the exploration is per commander), computed
    once per archive change."""
    if archive is None:
        return {}
    from . import prospect
    from .fleet import ALL_COMMANDERS
    try:
        key = (id(archive), getattr(archive, "rev", None))
    except Exception:
        key = None
    if key is None or _PROSPECTS["key"] != key:
        _PROSPECTS["pros"] = prospect.ring_prospects(archive.events(ALL_COMMANDERS))
        _PROSPECTS["key"] = key
    return _PROSPECTS["pros"]


def _ring_mining(db: Database, rings: List[Dict[str, Any]], archive: Any) -> None:
    """
    Under each ring: what the rocks there held (your prospecting) and, for
    each of its hotspots, what the rocks of rings of this class with such a
    hotspot held - the materials to expect next to it.
    """
    from . import learn, prospect
    pros = _ring_prospects(archive)
    # L3: your mining runs (t/h) - every commander's, like the prospecting
    try:
        runs = learn.runs_of(archive)
    except Exception:
        runs = []
    if not pros and not runs:
        return
    ring_hs: Dict[str, Any] = {}
    try:
        for h in db.query("SELECT body_name, material, ring_class FROM hotspots"):
            cls, keys = ring_hs.get(h["body_name"], (prospect.ring_class(h["ring_class"]), []))
            keys.append(prospect._key(h["material"]))
            ring_hs[h["body_name"]] = (cls, keys)
    except Exception:
        return
    pool = prospect.expectations(pros, ring_hs) if pros else {}
    rates = learn.ring_rates(runs, learn.ring_classes(db)) if runs else {}
    for g in rings:
        name = g.get("name") or ""
        g["prospect"] = prospect.summary(pros.get(name))
        cls = prospect.ring_class(g.get("cls")) or ring_hs.get(name, ("", []))[0]
        # L3: your tonnes per hour in this very ring, per material
        own = [dict(a, mat=m) for (rn, m), a in (rates.get("ring") or {}).items() if rn == name]
        g["rates"] = sorted(own, key=lambda a: -(a["t_h"] or 0))
        exp = []
        for h in g.get("hotspots") or []:
            k = prospect._key(h.get("key") or h["material"])
            e = prospect.expected_for(pool, cls, k, skip_ring=name) if pool else None
            rate = learn.expected_rate(rates, name, cls, k) if rates else None
            if e or rate:
                item = dict(e or {}, hotspot=h["material"])
                if rate:
                    item["rate"] = rate
                exp.append(item)
        g["expected"] = exp


def _ground_mining(db: Database, body_name: str, planet_class: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Ground mining (Rhino rigs) on this body - tonnes per material and the
    rigs collected - and what rigs on other bodies of this planet class
    yielded: what to expect here. From the plugin's "refined" marks (one
    per tonne, written where the rig was collected).
    """
    if not db.has_table("surface_marks"):
        return None
    rows = db.query("SELECT m.body_name, m.label, m.ts, m.lat, m.lon, b.planet_class "
                    "FROM surface_marks m LEFT JOIN bodies b ON b.name = m.body_name "
                    "WHERE m.kind = 'refined'")
    if not rows:
        return None
    here: Dict[str, int] = {}
    pool: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        typ = (r["label"] or "?").split("#")[0]
        if r["body_name"] == body_name:
            here[typ] = here.get(typ, 0) + 1
        elif planet_class and r["planet_class"] == planet_class:
            p = pool.setdefault(typ, {"t": 0, "bodies": set()})
            p["t"] += 1
            p["bodies"].add(r["body_name"])
    out: Dict[str, Any] = {}
    if here:
        rigs = 0
        try:
            nav = plugin().surfacenav
            marks = [dict(m) for m in db.query("SELECT * FROM surface_marks WHERE body_name = ?",
                                               (body_name,))]
            rigs = len(nav.body_state(marks)["rigs"]) if nav else 0
        except Exception:
            rigs = 0
        out["here"] = {"rigs": rigs, "tonnes": sum(here.values()),
                       "mats": [{"name": k, "t": v} for k, v in sorted(here.items(), key=lambda kv: -kv[1])]}
    try:
        # L3: rigs on bodies of this class - tonnes per rig, rigs per hour
        from . import learn
        rr = learn.rig_rates_db(db).get(planet_class or "?") if planet_class else None
        if rr:
            out["rate"] = dict(rr, cls=planet_class)
    except Exception:
        pass
    if pool:
        out["expected"] = {"cls": planet_class, "bodies": len(set().union(*(p["bodies"] for p in pool.values()))),
                           "mats": [{"name": k, "t": p["t"], "bodies": len(p["bodies"])}
                                    for k, p in sorted(pool.items(), key=lambda kv: -kv[1]["t"])]}
    return out or None


def build_body(db: Database, id64: int, body_id: int, archive: Any = None) -> Optional[Dict[str, Any]]:
    r = db.body(id64, body_id)
    if r is None:
        return None
    p = plugin()
    srow = db.system_by_id64(id64)
    sysname = srow["name"] if srow is not None else ""
    comp = _json(r["atmo_comp"], {}) or {}
    mats = _json(r["materials"], {}) or {}
    solid = _json(r["composition"], {}) or {}
    species = _json(r["bio_species"], []) or []
    # ring hotspots: the journal gives each ring its own BodyID, so they are
    # found by the ring names of this body (or by body_id when it is a ring
    # itself) - by the planet's body_id there are none (F4)
    ring_names = {g.get("name") for g in (_json(r["rings_json"], []) or []) if g.get("name")}
    hotspots = [{"material": h["label"] or h["material"], "count": h["count"],
                 "ring": h["body_name"], "key": h["material"]} for h in db.hotspots_of(id64)
                if h["body_name"] in ring_names or h["body_id"] == body_id]
    hs_by_ring: Dict[str, List[Dict[str, Any]]] = {}
    for h in hotspots:
        # the label for the view ("Void Opal"), the game's material ("Opal")
        # to match the prospector reports and mining runs
        hs_by_ring.setdefault(h["ring"] or "", []).append(
            {"material": h["material"], "count": h["count"], "key": h.pop("key")})
    out: Dict[str, Any] = {
        "id64": id64, "body_id": body_id, "system": sysname,
        "name": r["name"], "short": p.sysroute.shorten(r["name"] or "", sysname),
        "kind": r["kind"], "cls": body_class(r), "colour": colour_key(r),
        "terraform": r["terraform"] or "", "landable": bool(r["landable"]),
        "arrival_ls": _r(r["arrival_ls"], 1),
        "radius_km": _r((r["radius"] or 0) / 1000.0, 1) if r["radius"] else None,
        "mass_em": _r(r["mass_em"], 4),
        "gravity_g": _r(r["gravity"] / G0, 3) if r["gravity"] is not None else None,
        "temp_k": _r(r["temp_k"], 0),
        "pressure_atm": _r(r["pressure"] / ATM, 4) if r["pressure"] is not None else None,
        "pressure_pa": _r(r["pressure"], 0),
        "atmosphere": r["atmosphere"] or "",
        "atmo_type": r["atmo_type"] or "",
        "atmo_comp": sorted(([k, _r(v, 2)] for k, v in comp.items()),
                            key=lambda kv: -(kv[1] or 0)),
        "volcanism": r["volcanism"] or "",
        "composition": sorted(([k, _r(100.0 * v, 1)] for k, v in solid.items()),
                              key=lambda kv: -(kv[1] or 0)),
        "materials": sorted(([k, _r(v, 2)] for k, v in mats.items()),
                            key=lambda kv: -(kv[1] or 0)),
        "rotation_d": _r(r["rotation"] / 86400.0, 3) if r["rotation"] else None,
        "tidal_lock": bool(r["tidal_lock"]),
        "axial_tilt_deg": _r(math.degrees(r["axial_tilt"]), 2) if r["axial_tilt"] is not None else None,
        "orbit": {
            "sma_ls": _r((r["sma"] or 0) * LS_PER_M, 2) if r["sma"] else None,
            "ecc": _r(r["ecc"], 4), "inc_deg": _r(r["inc"], 2),
            "period_d": _r(r["period"] / 86400.0, 2) if r["period"] else None,
            "peri_deg": _r(r["peri"], 1), "node_deg": _r(r["node"], 1),
        },
        "was_discovered": (None if r["was_discovered"] is None else bool(r["was_discovered"])),
        "reserve": (r["reserve"] or "").replace("Resources", "").strip() or None,
        "rings": _rings(r, hs_by_ring),
        "flags": {
            "first": r["was_discovered"] == 0,
            "first_map": r["was_mapped"] == 0 and r["kind"] == "Planet",
            "mapped": bool(r["mapped"]), "scanned": bool(r["scanned"]),
            "footfall": r["was_footfalled"] == 0 and bool(r["landable"]),
        },
        "bio": {
            "signals": int(r["sig_bio"] or 0), "geo": int(r["sig_geo"] or 0),
            "analysed": int(r["organics"] or 0),
            "genera": [g.strip() for g in (r["genuses"] or "").split(",") if g.strip()],
            "species": [{"species": s.get("species"), "variant": s.get("variant"),
                         "genus": s.get("genus"), "date": (s.get("ts") or "")[:10]} for s in species],
            "prediction": [],
        },
        "hotspots": hotspots,
        "signals": body_signals(db.signals_of(id64, body_id)),
        "materials_found": [{"label": m["label"], "category": m["category"],
                             "count": m["count"], "last": (m["last"] or "")[:10]}
                            for m in db.materials_at(id64, r["name"])],
    }
    if r["kind"] == "Star":
        out["star"] = {
            "type": r["star_type"], "subclass": r["subclass"],
            "luminosity": r["luminosity"], "mass_sol": _r(r["stellar_mass"], 4),
            "abs_mag": _r(r["abs_mag"], 3), "age_my": r["age_my"],
            "scoopable": is_scoopable(r["star_type"]),
        }
    # what it orbits (a barycentre stands for a pair of bodies)
    if r["parent_id"] is not None:
        par = db.body(id64, r["parent_id"])
        if par is not None and par["name"]:
            out["parent"] = p.sysroute.shorten(par["name"], sysname)
        elif par is not None:
            # a barycentre: name the partner(s) sharing it
            mates = [p.sysroute.shorten(x["name"] or "", sysname) for x in db.bodies_of(id64)
                     if x["parent_id"] == r["parent_id"] and x["body_id"] != body_id and x["name"]]
            out["parent"] = "barycentre" + (" + " + ", ".join(mates[:3]) if mates else "")
    # your own visits to the surface
    if r["name"]:
        marks = db.surface_marks(id64, r["name"])
        landings = [m for m in marks if m["kind"] == "touchdown"]
        if landings or marks:
            out["visits"] = {"landings": len(landings), "marks": len(marks),
                             "last": (max(m["ts"] for m in marks) or "")[:10] if marks else None}
    if archive is not None:
        try:
            out["dss"] = archive.dss(id64, body_id)
            values = archive.organic_values()
            for s in out["bio"]["species"]:
                v = values.get(s.get("species") or "")
                if v:
                    s["value"], s["bonus"] = v["value"], v["bonus"]
        except Exception:  # pragma: no cover - journals are best effort
            pass
    if (r["sig_bio"] or 0) > 0 or r["landable"]:
        try:
            model = p.biopredict.BioModel.learn(db.bio_training_rows())
            out["bio"]["prediction"] = [
                {"genus": g, "score": round(s, 2), "finds": n}
                for g, s, n in model.predict(r, limit=6)]
            out["bio"]["model"] = model.summary()
        except Exception as exc:  # pragma: no cover - model is best effort
            out["bio"]["model"] = "forecast not available: %s" % exc
    from . import science
    try:
        _ring_mining(db, out["rings"], archive)    # rocks per ring, what to expect at a hotspot
    except Exception:
        pass
    try:
        out["ground"] = _ground_mining(db, r["name"] or "", r["planet_class"])
    except Exception:
        out["ground"] = None
    out["report"] = science.body_report(out)
    out["report_level"] = science.worst(out["report"])
    return out


# ---------------------------------------------------------------------------
# SURFACE: track, marks, exobiology colony circles
# ---------------------------------------------------------------------------



def _iso_epoch(ts: Optional[str]) -> Optional[float]:
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def _local_xy(lat: float, lon: float, lat0: float, lon0: float, radius: float):
    """Equirectangular projection around (lat0, lon0) in metres - fine for the
    few kilometres around a landing site."""
    dlon = (lon - lon0 + 540.0) % 360.0 - 180.0
    x = radius * math.cos(math.radians(lat0)) * math.radians(dlon)
    y = radius * math.radians(lat - lat0)
    return x, y


# Status.json Flags2 (on foot)
F2_ON_FOOT, F2_LOW_O2, F2_LOW_HEALTH, F2_COLD, F2_HOT, F2_VERY_COLD, F2_VERY_HOT, F2_BREATHABLE = (
    0, 6, 7, 8, 9, 10, 11, 16)


def life_support(st: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """B5: suit oxygen, health and temperature while on foot - None otherwise."""
    f2 = int(st.get("flags2") or 0)
    if not f2 & (1 << F2_ON_FOOT):
        return None
    bit = lambda n: bool(f2 & (1 << n))      # noqa: E731
    return {"oxygen": st.get("oxygen"), "health": st.get("health"), "temp_k": st.get("temp_k"),
            "gravity": st.get("gravity"), "breathable": bit(F2_BREATHABLE),
            "low_oxygen": bit(F2_LOW_O2), "low_health": bit(F2_LOW_HEALTH),
            "cold": bit(F2_COLD), "hot": bit(F2_HOT), "very_cold": bit(F2_VERY_COLD), "very_hot": bit(F2_VERY_HOT)}


def build_surface(db: Database, live: Optional[Dict[str, Any]],
                  id64: Optional[int] = None, body: Optional[str] = None) -> Dict[str, Any]:
    out = _build_surface(db, live, id64, body)
    life = life_support((live or {}).get("status") or {})
    if life:
        out = dict(out, life=life, suit=(live or {}).get("suit"))
    from .mining import rhino_hold
    rh = rhino_hold(live)
    if rh:
        out = dict(out, rhino=rh)
    return out


def backpack(journal_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    """M5: what you carry on foot (Backpack.json): consumables by name,
    goods / components / data as counts."""
    if not journal_dir:
        return None
    import json as _j
    import os as _os
    try:
        with open(_os.path.join(journal_dir, "Backpack.json"), encoding="utf-8") as fh:
            bp = _j.load(fh)
    except (OSError, ValueError):
        return None
    count = lambda k: sum(int(i.get("Count") or 0) for i in bp.get(k) or [])   # noqa: E731
    return {"consumables": [{"name": i.get("Name_Localised") or i.get("Name"), "count": int(i.get("Count") or 0)}
                            for i in bp.get("Consumables") or []],
            "items": count("Items"), "components": count("Components"), "data": count("Data"),
            "ts": bp.get("timestamp")}


def _build_surface(db: Database, live: Optional[Dict[str, Any]],
                   id64: Optional[int] = None, body: Optional[str] = None) -> Dict[str, Any]:
    live = live or {}
    st = live.get("status") or {}
    here = bool(st.get("body_name") and st.get("lat") is not None)
    if not body:
        if here:
            body = st.get("body_name")
            id64 = id64 or (live.get("system") or {}).get("id64")
        else:
            last = db.surface_last_body()
            if last is not None:
                id64, body = last["sys_id64"], last["body_name"]
    out: Dict[str, Any] = {"body": body, "id64": id64, "here": False, "track": [],
                           "marks": [], "bio": [], "me": None, "active": None}
    if not body or not id64:
        return out
    p = plugin()
    srow = db.system_by_id64(id64)
    sysname = srow["name"] if srow is not None else ""
    out["system"] = sysname
    out["short"] = p.sysroute.shorten(body, sysname) if sysname else body
    brow = db.body_by_name(id64, body)
    radius = (float(st["radius"]) if here and st.get("body_name") == body and st.get("radius")
              else (float(brow["radius"]) if brow is not None and brow["radius"] else None))
    track = db.surface_track(id64, body)
    marks = db.surface_marks(id64, body)
    out["radius_m"] = _r(radius, 0)
    if brow is not None:
        out["gravity_g"] = _r(brow["gravity"] / G0, 3) if brow["gravity"] is not None else None
        out["body_id"] = brow["body_id"]
    is_here = here and st.get("body_name") == body
    out["here"] = is_here
    # centre: where you are, else the last positioned mark, else the track
    if is_here:
        lat0, lon0 = float(st["lat"]), float(st["lon"])
    else:
        pos = [m for m in marks if m["lat"] is not None] or list(track)
        if not pos or not radius:
            out["marks"] = [{"kind": m["kind"], 
                             "label": m["label"], "ts": m["ts"], "x": None, "y": None}
                            for m in marks if m["kind"] != "refined"]
            return out
        lat0, lon0 = float(pos[-1]["lat"]), float(pos[-1]["lon"])
    if not radius:
        return out
    out["center"] = {"lat": lat0, "lon": lon0}
    # track as segments of one mode; thinned to at most ~4000 points
    step = max(1, len(track) // 4000)
    seg: Optional[Dict[str, Any]] = None
    for i, r in enumerate(track):
        if i % step and i != len(track) - 1:
            continue
        x, y = _local_xy(r["lat"], r["lon"], lat0, lon0, radius)
        if seg is None or seg["mode"] != r["mode"]:
            seg = {"mode": r["mode"] or "ship", "pts": []}
            out["track"].append(seg)
        seg["pts"].append([round(x, 1), round(y, 1)])
    me_xy = (0.0, 0.0) if is_here else None
    for m in marks:
        if m["kind"] == "refined":
            continue                 # one per tonne - shown as rigs below
        item = {"kind": m["kind"], 
                "label": m["label"], "detail": m["detail"], "ts": m["ts"], "x": None, "y": None}
        if m["lat"] is not None:
            x, y = _local_xy(m["lat"], m["lon"], lat0, lon0, radius)
            item["x"], item["y"] = round(x, 1), round(y, 1)
            if me_xy is not None:
                item["dist_m"] = round(math.hypot(x, y), 0)
                item["bearing"] = round((math.degrees(math.atan2(x, y)) + 360.0) % 360.0, 0)
        out["marks"].append(item)
    # where the SRV / the ship stand - the points to get back to
    nav = p.surfacenav.body_state([dict(m) for m in marks], radius) if p.surfacenav else None
    # Rhino rigs, where they were collected - numbered per launch, in time order
    for r in (nav or {}).get("rigs") or []:
        x, y = _local_xy(r["lat"], r["lon"], lat0, lon0, radius)
        item = {"kind": "rig", "label": "Rig %d · %d t %s" % (r["n"], r["tonnes"], r["type"]),
                "detail": r["type"], "n": r["n"], "tonnes": r["tonnes"], "ts": r["ts"],
                "x": round(x, 1), "y": round(y, 1)}
        if me_xy is not None:
            item["dist_m"] = round(math.hypot(x, y), 0)
            item["bearing"] = round((math.degrees(math.atan2(x, y)) + 360.0) % 360.0, 0)
        out["marks"].append(item)
    out["marks"].sort(key=lambda m: m.get("ts") or "")
    for key in ("parked", "ship"):
        v = nav[key] if nav else None
        if v is None:
            continue
        x, y = _local_xy(v["lat"], v["lon"], lat0, lon0, radius)
        item = {"x": round(x, 1), "y": round(y, 1), "ts": v["ts"],
                "label": (v["detail"] or "SRV") if key == "parked" else "ship"}
        if key == "ship" and isinstance(v, dict) and v.get("hover"):
            item["hover"] = True     # dropped the Rhino in a hover - last known
        if me_xy is not None:
            item["dist_m"] = round(math.hypot(x, y), 0)
            item["bearing"] = round((math.degrees(math.atan2(x, y)) + 360.0) % 360.0, 0)
        out[key] = item
    # exobiology: samples per species with the colony range of the genus;
    # surfacenav restarts a species' count on a new Log like the game does
    ranges = getattr(p.biopredict, "COLONY_RANGE_M", {})
    groups: Dict[str, Dict[str, Any]] = {}
    if nav is not None:
        for s in nav["species"]:
            pts = [[round(v, 1) for v in _local_xy(la, lo, lat0, lon0, radius)]
                   for la, lo in s["points"]]
            groups[s["species"]] = {"species": s["species"], "genus": s["genus"],
                                    "range_m": ranges.get(s["genus"] or ""), "points": pts,
                                    "done": s["analysed"], "samples": s["samples"]}
    for m in out["marks"]:
        if nav is not None or not m["kind"].startswith("bio_") or m["x"] is None:
            continue
        g = groups.setdefault(m["label"], {"species": m["label"], "genus": m["detail"],
                                           "range_m": ranges.get(m["detail"] or ""),
                                           "points": [], "done": False})
        if m["kind"] == "bio_analyse":
            g["done"] = True
        else:
            g["points"].append([m["x"], m["y"]])
    for g in groups.values():
        if me_xy is not None and g["points"] and not g["done"]:
            g["nearest_m"] = round(min(math.hypot(px, py) for px, py in g["points"]), 0)
            g["ok"] = g["range_m"] is not None and g["nearest_m"] >= g["range_m"]
    # E10: the species being worked on = the unfinished one with the newest
    # log/sample mark; the map draws it bright and dims the others
    newest: Dict[str, str] = {}
    for m in out["marks"]:
        if m["kind"] in ("bio_log", "bio_sample") and m["label"] and m["ts"]:
            newest[m["label"]] = max(newest.get(m["label"], ""), str(m["ts"]))
    open_ = [g for g in groups.values() if not g["done"] and g["species"] in newest]
    active = max(open_, key=lambda g: newest[g["species"]]) if open_ else None
    for g in groups.values():
        g["active"] = g is active
    out["active"] = ({"species": active["species"], "genus": active["genus"]}
                     if active is not None else None)
    out["bio"] = list(groups.values())
    # initial framing: the latest visit only (3 h before the last activity);
    # older visits to the same body may lie hundreds of km away
    stamps = [(r["ts"], r["lat"], r["lon"]) for r in track]
    stamps += [(_iso_epoch(m["ts"]), m["lat"], m["lon"]) for m in marks if m["lat"] is not None]
    stamps = [t for t in stamps if t[0] is not None]
    if stamps:
        last = max(t[0] for t in stamps)
        pts = [_local_xy(la, lo, lat0, lon0, radius) for t, la, lo in stamps if t >= last - 3 * 3600]
        if is_here:
            pts.append((0.0, 0.0))
        out["focus"] = {"minX": min(p[0] for p in pts), "maxX": max(p[0] for p in pts),
                        "minY": min(p[1] for p in pts), "maxY": max(p[1] for p in pts)}
    if is_here:
        out["me"] = {"x": 0.0, "y": 0.0, "heading": st.get("heading"), "alt": st.get("alt"),
                     "mode": ("foot" if (st.get("flags2") or 0) & 1 else
                              "srv" if (st.get("flags") or 0) & (1 << 26) else "ship")}
        if out["me"]["mode"] == "srv":
            out["me"]["vehicle"] = live.get("vehicle")      # "SRV Rhino", "Nomad" (M2)
    return out


# ---------------------------------------------------------------------------
# BRIEFING
# ---------------------------------------------------------------------------

def _fuel_state(live: Dict[str, Any]):
    ds = plugin().deepspace
    ship = live.get("ship") or {}
    fuel = live.get("fuel") or {}
    return ds.FuelState(capacity=float(ship.get("fuel_capacity") or 0.0),
                        level=float(fuel.get("main") or 0.0),
                        max_jump=float(ship.get("max_jump") or 0.0),
                        jumps=[tuple(j) for j in live.get("jumps") or []])


def boxel_info(db: Database, name: str) -> Optional[Dict[str, Any]]:
    """What our database knows about the boxel a procgen name sits in."""
    pg = plugin().procgen
    pn = pg.parse_name(name or "")
    if pn is None:
        return None
    key = pn.boxel_key
    row = db.boxel(key)
    known = [s for s in db.systems_with_prefix(pn.prefix)
             if (pg.parse_name(s["name"]) or pn).boxel_key == key
             and pg.parse_name(s["name"]) is not None]
    absent = db.absent_in(key)
    n2_max = row["n2_max"] if row is not None else None
    counts = [s["body_count"] for s in known if s["body_count"]]
    visited = [s for s in known if s["visited"]]
    bio_sys = 0
    for s in visited:
        if s["id64"] and db.one("SELECT 1 FROM bodies WHERE sys_id64=? AND sig_bio>0 LIMIT 1",
                                (s["id64"],)):
            bio_sys += 1
    open_n = None
    if n2_max is not None:
        seen = {pg.parse_name(s["name"]).n2 for s in known} | {a["n2"] for a in absent}
        open_n = sum(1 for n in range(0, n2_max + 1) if n not in seen)
    return {
        "key": key, "mc": pn.mc, "size_ly": pn.size, "n2": pn.n2,
        "complete": bool(row["complete"]) if row is not None else False,
        "n2_max": n2_max, "known": len(known), "visited": len(visited),
        "absent": len(absent), "candidates_open": open_n,
        "avg_bodies": round(sum(counts) / len(counts), 1) if counts else None,
        "bio_systems": bio_sys,
    }


def current_target(live: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """FSDTarget beats NavRoute's next hop beats Status.json Destination."""
    t = live.get("target")
    if t and t.get("name"):
        return dict(t)
    route = live.get("navroute") or []
    cur = (live.get("system") or {}).get("name")
    # NavRoute.json starts with the system it was plotted from; only trust it
    # while we are on it, and never point back at a hop already flown
    names = [h.get("name") for h in route]
    if cur in names:
        i = len(names) - 1 - names[::-1].index(cur)
        if i + 1 < len(route):
            return dict(route[i + 1], source="NavRoute")
    dest = ((live.get("status") or {}).get("destination") or {})
    if dest.get("system") and dest.get("system") != (live.get("system") or {}).get("id64"):
        return {"name": dest.get("name"), "id64": dest.get("system"),
                "source": "Status"}
    return None


def _navpoints(db: Database, live: Dict[str, Any], limit: int = 14) -> List[Dict[str, Any]]:
    """The plotted route after the current system, with what we know of each hop."""
    route = live.get("navroute") or []
    cur = (live.get("system") or {}).get("name")
    regions = db.shell_regions()
    start = 0
    for i, h in enumerate(route):
        if h.get("name") == cur:
            start = i + 1
    out = []
    prev = (live.get("system") or {}).get("pos")
    for n, h in enumerate(route[start:start + limit], start):
        row = db.system_by_id64(h["id64"]) if h.get("id64") else None
        pos = h.get("pos")
        out.append({"n": n, "name": h.get("name"), "id64": h.get("id64"),
                    "star_class": h.get("star_class"),
                    "scoopable": is_scoopable(h.get("star_class")) if h.get("star_class") else None,
                    "boost": boost_kind(h.get("star_class")),
                    "jump_ly": _r(_dist3(prev, pos), 2) if prev and pos else None,
                    "known_sources": Database.known_sources(row),
                    "level": info_level(row, regions)[0],
                    "visited": bool(row["visited"]) if row is not None else False})
        prev = pos
    return out


def _navpoints_for(db: Database, live: Dict[str, Any], fid: Optional[str]) -> List[Dict[str, Any]]:
    """_navpoints with 'visited' as this commander's own (C1)."""
    pts = _navpoints(db, live)
    if not fid or not db.cmdr_ready():
        return pts
    ids = [p["id64"] for p in pts if p.get("id64")]
    rows = db.with_visits([{"id64": i, "visited": 0, "fss_complete": 0} for i in ids], fid)
    seen = {r["id64"]: bool(r["visited"]) for r in rows}
    for p in pts:
        p["visited"] = seen.get(p.get("id64"), False)
    return pts


def _sphere_of(db: Database, pos: Optional[Sequence[float]]) -> Optional[Dict[str, Any]]:
    """Where the target lies relative to the active survey sphere."""
    if not pos:
        return None
    try:
        s = db.survey()
    except Exception:
        return None
    if s is None or s["cx"] is None or not s["radius"]:
        return None
    d = _dist3(pos, (s["cx"], s["cy"], s["cz"]))
    return {"name": s["start_system"], "radius": _r(s["radius"], 1),
            "from_centre_ly": _r(d, 1), "inside": d <= s["radius"],
            "active": bool(s["active"])}


FIND_KINDS = ("codex", "settlement", "screenshot", "material")


def approach_info(db: Database, live: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Near a body (Status.json names it, orbital cruise or landed): what you
    already know there - finds, species not finished, where the SRV waits,
    the body's signals and gravity."""
    st = live.get("status") or {}
    body = st.get("body_name")
    sid = (live.get("system") or {}).get("id64")
    if not body or not sid:
        return None
    marks = [dict(m) for m in db.surface_marks(sid, body)]
    finds: List[Dict[str, Any]] = []
    seen = set()
    for m in reversed(marks):
        if m["kind"] in FIND_KINDS and (m["kind"], m["label"]) not in seen:
            seen.add((m["kind"], m["label"]))
            finds.append({"kind": m["kind"], "label": m["label"]})
    p = plugin()
    nav = p.surfacenav.body_state(marks) if getattr(p, "surfacenav", None) and marks else None
    species = [{"species": s["species"], "samples": s["samples"]} for s in (nav or {}).get("species", [])
               if not s["analysed"]]
    row = db.one("SELECT sig_bio, sig_geo, organics, gravity, landable FROM bodies WHERE sys_id64=? AND name=?",
                 (int(sid), body))
    out = {"body": body, "short": p.sysroute.shorten(body, (live.get("system") or {}).get("name") or ""),
           "finds": finds[:8], "species": species, "parked": bool(nav and nav.get("parked")),
           "bio": int(row["sig_bio"] or 0) if row else 0, "geo": int(row["sig_geo"] or 0) if row else 0,
           "analysed": int(row["organics"] or 0) if row else 0,
           "gravity_g": _r((row["gravity"] or 0) / 9.80665, 2) if row and row["gravity"] else None,
           "landable": bool(row["landable"]) if row else None}
    if not (finds or species or out["parked"] or out["bio"] or out["geo"]):
        return None
    return out


def build_briefing(db: Database, live: Optional[Dict[str, Any]],
                   fid: Optional[str] = None) -> Dict[str, Any]:
    live = live or {}
    tgt = current_target(live)
    out: Dict[str, Any] = {"target": None, "generated": time.time(),
                           "navroute": _navpoints_for(db, live, fid)}
    try:
        out["approach"] = approach_info(db, live)
    except Exception:                     # never cost the briefing
        out["approach"] = None
    if not tgt:
        return out
    name, id64 = tgt.get("name"), tgt.get("id64")
    row = (db.system_by_id64(id64) if id64 else None) or (db.system_by_name(name) if name else None)
    shared = row
    row = db.system_for(row, fid) if fid else row       # C1: visited = by you
    star = tgt.get("star_class") or (row["star_class"] if row is not None else None)
    tpos = tgt.get("pos") or ([row["x"], row["y"], row["z"]] if row is not None and row["x"] is not None else None)
    cpos = (live.get("system") or {}).get("pos")
    dist = _r(_dist3(cpos, tpos), 2) if cpos and tpos else None
    known = Database.known_sources(row)
    level, checked_by = info_level(row, db.shell_regions())
    route = live.get("navroute") or []
    idx = next((i for i, h in enumerate(route) if h.get("name") == name), None)
    out["target"] = {
        "name": name, "id64": id64, "source": tgt.get("source"),
        "star_class": star, "scoopable": is_scoopable(star) if star else None,
        "boost": boost_kind(star),
        "distance_ly": dist, "in_db": row is not None,
        "visited": bool(row["visited"]) if row is not None else False,
        "known_sources": known, "in_no_database": level == "checked",
        "level": level, "checked_by": checked_by,
        "body_count": row["body_count"] if row is not None else None,
        "remaining_jumps": tgt.get("remaining_jumps"),
        "navpoint": [idx, len(route) - 1] if idx is not None and len(route) > 1 else None,
        "also_by": (db.explorers(shared["id64"], but=fid)
                    if fid and shared is not None and shared["id64"] else []),
    }
    out["boxel"] = boxel_info(db, name) if name else None
    out["sphere"] = _sphere_of(db, tpos)
    sid = id64 or (row["id64"] if row is not None else None)
    out["signals"] = system_signals(db.signals_of(sid)) if sid else []
    out["materials_found"] = ([{"label": m["label"], "count": m["count"],
                                "body": m["body_name"]} for m in db.materials_at(sid)][:6]
                              if sid else [])
    if live.get("ship"):
        fs = _fuel_state(live)
        f = {"level": _r(fs.level, 1), "capacity": _r(fs.capacity, 0),
             "jumps_left": fs.jumps_left, "warning": fs.warning()}
        if dist and fs.max_jump and dist > fs.max_jump * 1.02:
            # beyond one jump: the game will route it, a per-jump forecast lies
            f["beyond_range"] = True
        elif dist:
            cost = fs.cost_of(dist)
            if cost is not None:
                after = max(0.0, fs.level - cost)
                f["cost_t"] = _r(cost, 2)
                f["after_t"] = _r(after, 1)
                fs2 = _fuel_state(live)
                fs2.level = after
                f["jumps_after"] = fs2.jumps_left
        # a scoopable target: you refuel where you arrive - no fuel warning
        # as long as the jump itself is covered (11.11.: a G star, 5+ jumps)
        if f.get("warning") and out["target"]["scoopable"] and not f.get("beyond_range")                 and (f.get("cost_t") is None or fs.level > f["cost_t"]):
            f["warning"] = None
            f["scoop_at_target"] = True
        out["fuel"] = f
    # expectation text, rule based
    exp = []
    bx = out["boxel"]
    if bx and bx["avg_bodies"]:
        exp.append({"key": "avg_bodies", "n": round(bx["avg_bodies"]), "of": bx["known"]})
    if bx and bx["visited"]:
        exp.append({"key": "bio_neighbours", "n": bx["bio_systems"], "of": bx["visited"]})
    # data, not sentences: the browser words them in the display language
    out["expectation"] = exp
    if not known and level == "inhabited":
        out["status"] = "inhabited"         # population/station: surely known
    elif not known and level == "unchecked":
        out["status"] = "unchecked"         # I1: nobody asked - never "unknown"
    elif not known and row is not None and row["visited"]:
        out["status"] = "only_us"           # visited, but in no external database
    elif not known:
        out["status"] = "unknown"           # first discovery possible
    elif row is not None and row["visited"]:
        out["status"] = "visited"
    else:
        out["status"] = "known"
    return out


# ---------------------------------------------------------------------------
# SHIP
# ---------------------------------------------------------------------------

FLAGS = {
    0: "docked", 1: "landed", 2: "gear", 3: "shields", 4: "supercruise",
    5: "fa_off", 6: "hardpoints", 7: "in_wing", 8: "lights", 9: "cargo_scoop",
    10: "silent", 11: "scooping", 16: "fsd_mass_locked", 17: "fsd_charging",
    18: "fsd_cooldown", 19: "low_fuel", 20: "overheating", 21: "has_latlong",
    22: "in_danger", 23: "interdicted", 24: "in_ship", 25: "in_fighter",
    26: "in_srv", 27: "hud_analysis", 28: "night_vision", 30: "fsd_jump",
}

GUI_FOCUS = {0: "NONE", 1: "INTERNAL", 2: "EXTERNAL", 3: "COMMS", 4: "ROLE",
             5: "STATION", 6: "GALAXY MAP", 7: "SYSTEM MAP", 8: "ORRERY",
             9: "FSS", 10: "SAA", 11: "CODEX"}


def decode_flags(flags: int) -> List[str]:
    return [n for bit, n in FLAGS.items() if flags & (1 << bit)]


def build_ship(live: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    live = live or {}
    st = live.get("status") or {}
    ship = live.get("ship") or {}
    fuel = live.get("fuel") or {}
    out: Dict[str, Any] = {
        "ship": ship, "system": live.get("system"),
        "fuel": {"main": _r(fuel.get("main"), 2), "reservoir": _r(fuel.get("reservoir"), 2),
                 "capacity": ship.get("fuel_capacity")},
        "flags": decode_flags(int(st.get("flags") or 0)),
        "gui_focus": st.get("gui_focus"),
        "gui_focus_name": GUI_FOCUS.get(st.get("gui_focus") or 0, "?"),
        "target": current_target(live), "destination": st.get("destination"),
        "jumping": live.get("jumping"),
        "status_ts": st.get("ts"),
    }
    from .combat import combat_state
    out["combat"] = combat_state(live, time.time())          # M8
    if ship.get("fuel_capacity"):
        fs = _fuel_state(live)
        out["fuel"].update(pct=_r(fs.pct, 1), jumps_left=fs.jumps_left,
                           range_ly=_r(fs.range_left, 0), warning=fs.warning(),
                           summary=fs.summary(), samples=fs.samples)
    return out


# ---------------------------------------------------------------------------
# SURVEY (sphere progress)
# ---------------------------------------------------------------------------

def build_survey(db: Database) -> Dict[str, Any]:
    s = db.survey()
    meta = db.meta()
    out: Dict[str, Any] = {"active": False, "spheres": [], "boxels": db.boxel_counts()}
    if meta.get("carrier_system"):
        out["carrier"] = {"name": meta.get("carrier_name"), "callsign": meta.get("carrier_callsign"),
                          "system": meta.get("carrier_system"), "updated": meta.get("carrier_updated")}
    for sp in db.spheres():
        out["spheres"].append({"id": sp["id"], "label": sp["label"], "center": [sp["cx"], sp["cy"], sp["cz"]],
                               "radius": sp["radius"], "origin": sp["origin"],
                               "started": sp["started"], "closed": sp["closed"]})
    if s is None or s["cx"] is None:
        return out
    out.update(active=bool(s["active"]), start_system=s["start_system"],
               center=[s["cx"], s["cy"], s["cz"]], radius=s["radius"],
               masscodes=s["masscodes"], started=s["started"], updated=s["updated"])
    rows = db.systems_in_sphere(s["cx"], s["cy"], s["cz"], s["radius"] or 0.0)
    visited = [r for r in rows if r["visited"]]
    regions = db.shell_regions()
    only_us = [r for r in visited if info_level(r, regions)[0] == "checked"]
    # C1: the survey counts for the main commander; the others are named
    main = db.view_fid(MAIN)
    if main:
        out["commander"] = db.commander_name(main) or main
        also = []
        for c in db.commanders():
            if c["fid"] == main:
                continue
            n = sum(1 for r in db.with_visits(rows, c["fid"]) if r["visited"])
            if n:
                also.append({"name": c["name"] or c["fid"], "visited": n})
        out["also_by"] = also
    out["systems"] = {
        "known": len(rows), "visited": len(visited),
        "fss_complete": sum(1 for r in rows if r["fss_complete"]),
        "only_us": len(only_us),
        "pct_visited": _r(100.0 * len(visited) / len(rows), 1) if rows else None,
    }
    return out
