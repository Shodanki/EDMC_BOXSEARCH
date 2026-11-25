# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
4.12: the overlay's situation column, fed by EDMC.

journal() and dashboard() run on EDMC's main thread after the event is
stored; they put short items on the board (situation.Board), each for as
long as it matters. tick() runs every TICK_MS on the main thread and draws
the board in the corner opposite the other blocks. Work that reads many
rows (unsold data, a boxel's known systems) or the journal files (what
you were paid) runs in worker threads, which only touch the board - under
its lock, never Tk.

What it shows - each only when it helps (situation.py has the texts):
  warnings  the arrival star (neutron, white dwarf, black hole); unsold
            data at stake when in danger, interdicted, overheating,
            under attack or the hull is low
  places    the landing card on approach (gravity, temperature,
            atmosphere, open genera by what you were paid, finds); the
            system's value after the honk and while scanning; a ring's
            hotspots; a ring hotspot set as target: the chance of a good
            field and what you got there before (SP2); the boxel on
            arrival; fuel along a plotted route; your carrier's jump
            countdown
  session   what this session brought, after a sale or on docking
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Any, Dict, List, Optional

from . import bodyvalue
from . import journalscan
from . import maintenance
from . import miningfields
from . import situation
from .deepspace import scoop_line
from .procgen import parse_name
from .state import CFG, ST, cfg_bool, logger
from .sysdb import CURRENT
from . import cockpit
from . import panel
from . import uithread

TICK_MS = 5000
DRAW_TTL = 7              # s on screen; sent again every tick
RISK_KEEP_S = 25          # the risk line stays this long after the danger ends
UNSOLD_CACHE_S = 60
HULL_LOW = 0.6            # HullDamage Health below this: data at risk

BOARD = situation.Board()
SESSION = situation.Session()
PRICES = situation.Prices()
SCANS = situation.Scans()
CARRIER = situation.CarrierWatch()
FIELDS = miningfields.FieldBook()        # SP2: filled by survey._bootstrap_fields, fed live
_lock = threading.RLock()
_timer = False
_drawn = False
_danger: Optional[str] = None
_unsold: Optional[Dict[str, Any]] = None
_unsold_t = 0.0
_carrier_dist: Optional[float] = None    # ly from the carrier to its destination
_spot_dest: Optional[tuple] = None       # SP2: the ring hotspot last set as target

GROUPS = {"warn": ("journal", "hazard", "risk"),
          "place": ("landing", "system", "spot", "ring", "boxel", "route", "carrier"),
          "session": ("session",)}


def enabled_keys() -> List[str]:
    """The items the preferences switch on."""
    out: List[str] = []
    for grp, keys in GROUPS.items():
        if cfg_bool(CFG["overlay_info_%s" % grp], True):
            out += keys
    return out


def _put(key: str, lines: List[situation.Line], ttl: float) -> None:
    with _lock:
        BOARD.put(key, lines, ttl, time.time())


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------

def journal(ev: str, entry: Dict[str, Any]) -> None:
    """EDMC journal event (main thread, after it is stored). Never raises."""
    try:
        _learn(ev, entry)
        h = _ON.get(ev)
        if h is not None:
            h(entry)
    except Exception:
        logger.debug("situation | %s failed", ev, exc_info=True)


def _learn(ev: str, entry: Dict[str, Any]) -> None:
    """The plain models: session, prices, scans, the carrier."""
    global _carrier_dist
    FIELDS.add(entry)
    with _lock:
        got = SESSION.feed(entry)
        PRICES.feed(entry)
        SCANS.feed(entry)
        jump = CARRIER.feed(entry)
    if jump:
        _carrier_dist = _carrier_ly(CARRIER.dest)
        with _lock:
            _carrier_item(time.time(), fresh=True)
    if got:
        _put("session", situation.session_lines(SESSION.summary(), sold=got), 25)


def _on_start_jump(e: Dict[str, Any]) -> None:
    """Into hyperspace: warn of the star at the other end."""
    if e.get("JumpType") == "Hyperspace":
        _put("hazard", situation.hazard_lines(e.get("StarClass")), 45)


def _on_fsd_jump(e: Dict[str, Any]) -> None:
    """Arrived: the places of the last system are gone; the boxel."""
    with _lock:
        for k in ("landing", "system", "ring", "route"):
            BOARD.drop(k)
    if ST.active or ST.probe:
        uithread._run_async(_boxel_worker, e.get("StarSystem"), label="boxel")


def _on_discovery(e: Dict[str, Any]) -> None:
    """The honk, all bodies found, a map done: the system's value."""
    ttl = {"FSSDiscoveryScan": 30, "FSSAllBodiesFound": 40}.get(e.get("event"), 20)
    lines = _system_lines(e.get("SystemAddress") or ST.cur_id64)
    _put("system", lines, ttl)


def _on_scan(e: Dict[str, Any]) -> None:
    """A body scanned: the system's value moves on while it is on show."""
    with _lock:
        shown = BOARD.has("system")
    if shown:
        lines = _system_lines(e.get("SystemAddress") or ST.cur_id64)
        with _lock:
            BOARD.refresh("system", lines)


def _on_approach(e: Dict[str, Any]) -> None:
    """Approaching a body: the landing card."""
    lines = _landing_lines(e.get("SystemAddress") or ST.cur_id64, e.get("BodyID"), e.get("Body"))
    _put("landing", lines, 60)


def _on_touchdown(e: Dict[str, Any]) -> None:
    """Down (or away again): the landing card has done its job."""
    with _lock:
        BOARD.drop("landing")


def _on_supercruise_exit(e: Dict[str, Any]) -> None:
    """Dropped at a ring: its hotspots."""
    if e.get("BodyType") == "PlanetaryRing" and e.get("Body"):
        _ring(e.get("SystemAddress") or ST.cur_id64, e["Body"])


def _on_ring_signals(e: Dict[str, Any]) -> None:
    """A ring mapped: its hotspots."""
    nm = e.get("BodyName") or ""
    if nm.endswith("Ring"):
        _ring(e.get("SystemAddress") or ST.cur_id64, nm)


def _on_navroute(e: Dict[str, Any]) -> None:
    """A route plotted: the fuel along it."""
    hops = len(ST.navroute or []) - 1
    _put("route", situation.route_lines(hops, scoop_line(cockpit._scoop_plan())), 25)


def _on_navroute_clear(e: Dict[str, Any]) -> None:
    with _lock:
        BOARD.drop("route")


def _on_docked(e: Dict[str, Any]) -> None:
    """Docked: what this session brought."""
    with _lock:
        lines = situation.session_lines(SESSION.summary())
    _put("session", lines, 20)


def _on_risk_event(e: Dict[str, Any]) -> None:
    """Interdicted, under attack, hull low: unsold data at stake."""
    ev = e.get("event")
    if ev == "HullDamage":
        if not e.get("PlayerPilot", True) or e.get("Fighter") or float(e.get("Health") or 1) >= HULL_LOW:
            return
        why = "hull %d %%" % round(float(e["Health"]) * 100)
    elif ev == "UnderAttack":
        if e.get("Target") not in (None, "You"):
            return
        why = "under attack"
    else:
        why = "interdicted"
    _risk(why)


def _on_died(e: Dict[str, Any]) -> None:
    with _lock:
        BOARD.drop("risk")


_ON = {
    "StartJump": _on_start_jump,
    "FSDJump": _on_fsd_jump,
    "FSSDiscoveryScan": _on_discovery,
    "FSSAllBodiesFound": _on_discovery,
    "SAAScanComplete": _on_discovery,
    "Scan": _on_scan,
    "ApproachBody": _on_approach,
    "Touchdown": _on_touchdown,
    "LeaveBody": _on_touchdown,
    "SupercruiseExit": _on_supercruise_exit,
    "SAASignalsFound": _on_ring_signals,
    "NavRoute": _on_navroute,
    "NavRouteClear": _on_navroute_clear,
    "Docked": _on_docked,
    "Interdicted": _on_risk_event,
    "UnderAttack": _on_risk_event,
    "HullDamage": _on_risk_event,
    "Died": _on_died,
}


# ---------------------------------------------------------------------------
# the items that need the database
# ---------------------------------------------------------------------------

def _fid() -> Optional[str]:
    try:
        return ST.db.view_fid(CURRENT)
    except Exception:
        return None


def _system_lines(sys_id64: Any) -> List[situation.Line]:
    """SYSTEM / notable / DSS lines from the commander's own scans."""
    if not ST.db or not sys_id64:
        return []
    with ST.lock:
        rows = [dict(r) for r in ST.db.bodies_for(sys_id64, _fid())]
    with _lock:
        for r in rows:
            r.update({k: v for k, v in SCANS.of(sys_id64, r["body_id"]).items()
                      if k in ("mass_em", "stellar_mass") and v is not None})
        count = SCANS.body_count.get(sys_id64)
    return situation.system_lines(bodyvalue.system_summary(rows, count))


def _landing_lines(sys_id64: Any, body_id: Any, name: Optional[str]) -> List[situation.Line]:
    """The landing card of one body."""
    if not ST.db or not sys_id64 or body_id is None:
        return []
    with ST.lock:
        row = next((dict(r) for r in ST.db.bodies_for(sys_id64, _fid()) if r["body_id"] == body_id), None)
        finds = [dict(r) for r in ST.db.finds_of(sys_id64, body_id)]
    with _lock:
        sc = dict(SCANS.of(sys_id64, body_id))
    body: Dict[str, Any] = {"name": name, "gravity_g": sc.get("gravity_g"), "temp_k": sc.get("temp_k"),
                            "atmosphere": sc.get("atmosphere")}
    if row is not None:
        body["short"] = _short(row.get("name") or name or "", ST.cur_system)
        try:
            analysed = json.loads(row.get("bio_species") or "[]")
        except ValueError:
            analysed = []
        genera = [g.strip() for g in (row.get("genuses") or "").split(",") if g.strip()]
        with _lock:
            body["open_genera"] = [(g, PRICES.of_genus(g)) for g in situation.genus_open(genera, analysed)]
        body["bio_done"] = bool(row.get("sig_bio")) and not body["open_genera"] and bool(analysed)
        if row.get("sig_bio") and not genera:
            body["open_genera"] = [("%d signal%s - DSS for the genera" % (
                row["sig_bio"], "" if row["sig_bio"] == 1 else "s"), None)]
    body["finds"] = ["%s x%d" % (f["label"] or f["kind"], f["count"]) if f["count"] > 1
                     else (f["label"] or f["kind"]) for f in finds]
    return situation.landing_lines(body)


def _short(body: str, system: Optional[str]) -> str:
    """A body's name without its system's."""
    if system and body.startswith(system + " "):
        return body[len(system) + 1:]
    return body


def _ring(sys_id64: Any, ring: str) -> None:
    """RING item: hotspots and what you sold the materials for."""
    if not ST.db or not sys_id64:
        return
    with ST.lock:
        rows = [dict(r) for r in ST.db.hotspots_of(sys_id64, ring)]
    hs = [(r["label"] or r["material"], r["count"]) for r in rows]
    with _lock:
        prices = {(r["label"] or r["material"]).lower(): PRICES.market.get(r["material"].lower())
                  for r in rows if PRICES.market.get(r["material"].lower())}
    _put("ring", situation.ring_lines(_short(ring, ST.cur_system), hs, prices), 30)


def _boxel_worker(system: Optional[str]) -> None:
    """Worker: how much of the boxel you arrived in is known."""
    pn = parse_name(system or "")
    if pn is None or not ST.db:
        return
    key = pn.boxel_key
    with ST.lock:
        known = len(ST.db.known_n2(key))
        end = ST.db.boxel_end(key)
    probes = sum(1 for q in list(ST.probe or []) if q.boxel_key == key)
    _put("boxel", situation.boxel_lines(pn.prefix, known, end, probes), 25)


def _carrier_item(now: float, fresh: bool = False) -> None:
    """CARRIER item: the countdown; details for 30 s after the request and
    in the last two minutes (caller holds _lock)."""
    c = CARRIER
    if not c.pending(now):
        BOARD.drop("carrier")
        return
    left = c.departure - now
    detail = fresh or (c.requested is not None and now - c.requested < 30) or left < 120
    ly = _carrier_dist if detail else None
    tri = situation.tritium_t(ly, c.used) if ly else None
    lines = situation.carrier_lines(c.dest or "?", c.departure, now, ly=ly, tritium=tri,
                                    tank=c.fuel if detail else None)
    BOARD.put("carrier", lines if detail else lines[:1], max(10.0, left + 120), now)


def _carrier_ly(dest: Optional[str]) -> Optional[float]:
    """Distance of the carrier to its destination, when both are known."""
    car = getattr(ST, "carrier", None) or {}
    here = car.get("coords")
    if not here or not dest or not ST.db:
        return None
    try:
        with ST.lock:
            row = ST.db.system(dest)
        if row is None or row["x"] is None:
            return None
        return math.dist(here, (row["x"], row["y"], row["z"]))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# danger: unsold data at stake
# ---------------------------------------------------------------------------

def dashboard(entry: Dict[str, Any]) -> None:
    """Status.json (main thread): in danger, interdicted, overheating; a
    ring hotspot set as target."""
    global _danger
    _spot_check(entry)
    if "Flags" not in entry:
        return
    try:
        why = situation.danger_why(int(entry.get("Flags") or 0))
    except (TypeError, ValueError):
        return
    if why and why != _danger:
        _risk(why)
    elif why:
        with _lock:
            it = BOARD.items.get("risk")
            if it is not None:
                BOARD.put("risk", it[1], RISK_KEEP_S, time.time())
    _danger = why


def _spot_check(entry: Dict[str, Any]) -> None:
    """SP2: a ring hotspot newly set as target starts the SPOT item (a
    worker counts); another target or none drops it."""
    global _spot_dest
    dest = entry.get("Destination") if isinstance(entry.get("Destination"), dict) else None
    mat = miningfields.hotspot_material(dest.get("Name")) if dest else None
    key = (dest.get("System"), dest.get("Body"), mat) if dest and mat else None
    if key == _spot_dest:
        return
    _spot_dest = key
    if key is None:
        with _lock:
            BOARD.drop("spot")
        return
    name = (dest.get("Name_Localised") or mat).replace(" Hotspot", "").replace(" hotspot", "")
    uithread._run_async(_spot_worker, key, name, label="spot")


def _spot_worker(key: tuple, material: str) -> None:
    """Worker: the ring of the target hotspot, its chance and its record."""
    sys_id64, body_id, mat = key
    if not ST.db:
        return
    with ST.lock:
        row = ST.db.cx.execute("SELECT body_name FROM hotspots WHERE sys_id64=? AND body_id=? LIMIT 1",
                               (sys_id64, body_id)).fetchone()
        rf = miningfields.ring_features(lambda sql: ST.db.cx.execute(sql).fetchall())
    ring = row[0] if row else None
    if not ring:
        return
    rated = FIELDS.rated() if FIELDS.loaded else []
    m = miningfields.Odds.learn(miningfields.samples(rated, rf))
    odds = miningfields.odds_for(m, rf, ring, mat)
    lines = situation.spot_lines(_short(ring, ST.cur_system), material, odds,
                                 miningfields.field_of(rated, ring, mat), FIELDS.loaded)
    if _spot_dest == key:
        _put("spot", lines, 90)
    logger.info("spot | %s %s: chance %s from %d fields", ring, mat, odds and odds.get("p"), m.fields)


def _risk(why: str) -> None:
    """Show what is at stake; the sum comes from a worker (cached a minute)."""
    if _unsold is not None and time.time() - _unsold_t < UNSOLD_CACHE_S:
        _put("risk", situation.risk_lines(_unsold, why), RISK_KEEP_S)
        return
    uithread._run_async(_unsold_worker, why, label="unsold data")


def unsold_summary(rows: List[Any], species_value: Dict[str, int]) -> Dict[str, Any]:
    """Systems, bodies, first discoveries, species and their value from
    sysdb.unsold_rows (mass unknown there: typical masses)."""
    systems = set()
    value = bodies = first = species = 0
    for r in rows:
        r = dict(r)
        systems.add(r["sys_id64"])
        if r.get("scan_open") or r.get("map_open"):
            bodies += 1
            bv = bodyvalue.body_values(r)
            value += bv["now"]
            first += 1 if bv["first"] else 0
        try:
            sp = json.loads(r.get("bio_open") or "[]")
        except ValueError:
            sp = []
        species += len(sp)
        value += sum(species_value.get(s, 0) for s in sp)
    return {"systems": len(systems), "bodies": bodies, "first": first, "species": species, "value": value}


def _unsold_worker(why: str) -> None:
    """Worker: sum up what this commander carries unsold."""
    global _unsold, _unsold_t
    if not ST.db:
        return
    with ST.lock:
        ST.db.apply_sold_marks()                      # SM1: a sale marked in the FIS
        rows = ST.db.unsold_rows(_fid())
    with _lock:
        sv = dict(PRICES.species)
    _unsold, _unsold_t = unsold_summary(rows, sv), time.time()
    _put("risk", situation.risk_lines(_unsold, why), RISK_KEEP_S)


# ---------------------------------------------------------------------------
# drawing and the start
# ---------------------------------------------------------------------------

def tick_start() -> None:
    """Start the drawing loop (main thread, once the panel exists)."""
    global _timer
    if _timer or panel._frame is None:
        return
    _timer = True
    try:
        panel._frame.after(TICK_MS, _tick)
    except Exception:
        _timer = False


def _tick() -> None:
    global _timer
    _timer = False
    try:
        draw()
    except Exception:
        logger.debug("situation | draw failed", exc_info=True)
    tick_start()


def draw(now: Optional[float] = None) -> bool:
    """Draw the column (main thread); True when something is on screen."""
    global _drawn
    ov = getattr(ST, "overlay", None)
    if ov is None or not ov.enabled:
        return False
    now = time.time() if now is None else now
    with _lock:
        if CARRIER.departure is not None:
            _carrier_item(now)
        lines = [(t[:situation.LINE_MAX], c) for t, c in BOARD.lines(now, enabled_keys())]
    if not lines:
        if _drawn:
            ov.clear("info")
            _drawn = False
        return False
    _drawn = ov.show_info(lines, seconds=DRAW_TTL)
    return _drawn


def bootstrap() -> None:
    """Worker at the start: what you were paid (every journal), this
    session, the scans and your carrier (the newest journals). What came
    in live meanwhile wins."""
    global SESSION, CARRIER, _carrier_dist
    folder = maintenance._journal_dir()
    files = journalscan.journal_files(folder)
    if not files:
        return
    prices = situation.Prices()
    for e in journalscan.read_events_matching(files, ('"SellOrganicData"', '"MarketSell"')):
        prices.feed(e)
    session, scans, carrier = situation.Session(), situation.Scans(), situation.CarrierWatch()
    for e in journalscan.read_events(files[-3:]):
        session.feed(e)
        scans.feed(e)
        carrier.feed(e)
    with _lock:
        prices.genus.update(PRICES.genus)
        prices.species.update(PRICES.species)
        prices.market.update(PRICES.market)
        PRICES.genus, PRICES.species, PRICES.market = prices.genus, prices.species, prices.market
        for k, v in scans.bodies.items():
            SCANS.bodies.setdefault(k, v)
        for k, v in scans.body_count.items():
            SCANS.body_count.setdefault(k, v)
        if SESSION.jumps == SESSION.scanned == SESSION.earned == 0:
            SESSION = session
        if CARRIER.departure is None and carrier.pending(time.time()):
            CARRIER = carrier
        elif CARRIER.fuel is None:
            CARRIER.fuel, CARRIER.used = carrier.fuel, carrier.used
    if CARRIER.departure is not None and _carrier_dist is None:
        _carrier_dist = _carrier_ly(CARRIER.dest)
    logger.info("situation | read: %d genera and %d commodities you were paid for, %d bodies scanned "
                "in the last journals", len(prices.genus), len(prices.market), len(scans.bodies))


__all__ = ["journal", "dashboard", "draw", "tick_start", "bootstrap", "enabled_keys", "unsold_summary",
           "BOARD"]
