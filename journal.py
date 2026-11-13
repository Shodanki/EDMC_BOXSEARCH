# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""EDMC's journal and dashboard hooks.

``journal_entry`` sends each journal event to the code that handles it;
``dashboard_entry`` follows Status.json (surface position, compass,
sampling distance, mining). Both run on EDMC's main thread and hand slow
work to worker threads.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from . import miningstat
from . import surfacenav
from .biopredict import COLONY_RANGE_M, surface_distance_m
from .procgen import star_pos
from .sysdb import CURRENT
from .sysroute import calibrate_from_journal, leg_distance_ls
from .state import CFG, POSITION_EVENTS, ST, cfg_bool, logger
from . import cockpit
from . import panel
from . import planning
from . import routewin
from . import survey
from . import uithread


def journal_entry(cmdr: str, is_beta: bool, system: str, station: str,
                  entry: Dict[str, Any], state: Dict[str, Any]) -> None:
    """
    EDMC hook: one journal event, on the main thread. Keeps the commander
    (name and FID), stores the event, then hands it to the one handler for
    its name (_HANDLERS); long work goes to worker threads. Never raises -
    errors are logged.
    """
    if not ST.db:
        return
    ev = entry.get("event")
    _track_commander(cmdr, state)
    try:
        if not _before_ingest(ev, entry, state):
            return
        with ST.lock:
            ST.db.ingest_journal_event(entry)
        if ev == "NavRoute" and ST.active:
            # every hop of a plotted route is a confirmed system now
            survey._prune_queues()
        survey._measure_work(ev, entry)
        _supercruise_timing(ev, entry)
        _system_time(ev)
        _fuel_on_jump(ev, entry)
        handler = _HANDLERS.get(ev)
        if handler is not None:
            handler(ev, entry, cmdr, state)
    except Exception:
        logger.exception("journal_entry(%s) failed", ev)


def _track_commander(cmdr: str, state: Dict[str, Any]) -> None:
    """The commander of this event (name and FID); a switch resets what
    belongs to the previous one. Never raises."""
    try:
        if cmdr and cmdr != ST.cmdr:
            if ST.cmdr is not None:
                planning._commander_switched()
            ST.cmdr = cmdr
        fid = state.get("FID") if isinstance(state, dict) else None
        if fid and fid != ST.db.fid:
            with ST.lock:
                ST.db.set_commander(fid, cmdr)
            planning._apply_main_cmdr()
    except Exception:
        logger.exception("journal_entry: commander switch failed")


def _before_ingest(ev: str, entry: Dict[str, Any], state: Dict[str, Any]) -> bool:
    """What every event does before it is stored: the ship's position at a
    body, the mining overlay, the plotted route. False: do not store it (a
    NavRoute while harvesting plotted routes is switched off)."""
    # Before the handlers: any event naming a body updates where we are.
    # Inside the dispatch chain whichever branch matched first swallowed it,
    # and the marker stopped moving.
    if entry.get("BodyID") is not None and ev in POSITION_EVENTS:
        routewin._note_position(entry)
    _mining_event(ev, entry, state)
    # EDMC enriches NavRoute with the full Route array
    if ev == "NavRoute" and entry.get("Route"):
        cockpit._note_navroute(entry.get("Route"))
        try:
            cockpit._maybe_route_check(list(ST.navroute))
        except Exception:
            logger.debug("route check not started", exc_info=True)
    elif ev == "NavRouteClear":
        ST.navroute = []
    return not (ev == "NavRoute" and not cfg_bool(CFG["harvest_navroute"], True))


def _mining_event(ev: str, entry: Dict[str, Any], state: Dict[str, Any]) -> None:
    """Mining: rock, hold, rate, session and limpets on the overlay."""
    if ev in miningstat.EVENTS or ev in miningstat.PLACE or ev == "Cargo":
        try:
            cargo = state.get("Cargo") if isinstance(state, dict) else None
            changed = ST.mine.feed(entry, cargo=cargo)
            if changed or (ev == "Cargo" and ST.mine.active()):
                _mining_overlay(force=True)
        except Exception:
            logger.debug("mining overlay failed", exc_info=True)


def _supercruise_timing(ev: str, entry: Dict[str, Any]) -> None:
    """
    Supercruise timing, measured on the legs the route actually plans:
    body A -> body B inside one system. The distance comes from the
    orbital positions of both bodies at the moment of the flight.
    Up to 4.2.0 every SupercruiseEntry -> Exit was paired with the
    *arrival distance* of the target (its distance from the arrival
    star), which is not the distance flown, so the fit ended at the
    edge of its grid. The first leg after a jump is left out on purpose:
    it also holds what you do on arrival (honk, FSS), not just flying.
    """
    if ev == "SupercruiseEntry":
        if (ST.last_body_name and ST.cur_id64
                and ST.last_body_sys == ST.cur_id64):
            ST._sc_start = (time.time(), ST.last_body_name)
        else:
            ST._sc_start = None
    elif ev in ("FSDJump", "CarrierJump", "Shutdown", "LoadGame",
                "Died", "Resurrect"):
        ST._sc_start = None
    elif ev == "SupercruiseExit":
        start = ST._sc_start
        ST._sc_start = None
        dest = entry.get("Body")
        if start and ST.cur_id64 and dest and dest != start[1]:
            _supercruise_leg(start, dest, time.time() - start[0])


def _supercruise_leg(start, dest: str, dt: float) -> None:
    """One measured leg: keep it and recalibrate every 8 legs."""
    if not 5 < dt < 3600:
        return
    with ST.lock:
        rows = ST.db.bodies_of(ST.cur_id64)
    d = leg_distance_ls(rows, start[1], dest, at=time.time())
    if d and d > 1.0:
        ST.sc_segments.append((d, dt))
        if len(ST.sc_segments) % 8 == 0:
            ST.cost_model = calibrate_from_journal(
                ST.sc_segments[-200:], ST.cost_model)
            logger.info("supercruise model recalibrated: %s",
                        ST.cost_model.as_dict())


def _system_time(ev: str) -> None:
    """Minutes spent per system, from jump to jump."""
    if ev in ("FSDJump", "CarrierJump"):
        if ST._sys_enter is not None:
            spent = (time.time() - ST._sys_enter) / 60.0
            if 0.5 < spent < 180.0:      # ignore pauses and instant hops
                ST.sys_minutes.append(spent)
                del ST.sys_minutes[:-60]
        ST._sys_enter = time.time()


def _fuel_on_jump(ev: str, entry: Dict[str, Any]) -> None:
    """Fuel used per jump, the level after it, and a warning when low."""
    if ev == "FSDJump" and entry.get("FuelUsed") is not None:
        try:
            ST.fuel.add_jump(entry.get("JumpDist"),
                             entry.get("FuelUsed"))
            if entry.get("FuelLevel") is not None:
                ST.fuel.level = float(entry["FuelLevel"])
            w = ST.fuel.warning()
            if w:
                logger.info("fuel | %s", w)
        except (TypeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# One handler per event name. Each event reaches at most one of them (as in
# the if/elif chain they replace); all take (ev, entry, cmdr, state).
# ---------------------------------------------------------------------------

def _on_arrival(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """FSDJump, Location, CarrierJump: a new current system."""
    ST.awaiting_position = False
    if entry.get("SystemAddress") != ST.cur_id64:
        ST.route_done.clear()
        ST.route_started = None
        ST.route_feedback = ""
    if entry.get("SystemAddress") != ST.last_body_sys:
        ST.last_body_id = None
        ST.last_body_sys = None
        ST.last_body_name = ""
    ST.cur_system = entry.get("StarSystem")
    ST.cur_id64 = entry.get("SystemAddress")
    pos = star_pos(entry.get("StarPos"))
    if pos:
        ST.cur_pos = pos
    if ST.active:
        survey._prune_queues()
        survey._resort_queues()
        uithread._ui(survey._copy_flight)
    if ev == "FSDJump":
        cockpit._overlay_briefing("arrival", ST.cur_system, ST.cur_id64,
                                  entry.get("StarClass") or None)
        if ST.active:
            threading.Thread(target=planning._update_route_targets, daemon=True,
                             name="SHBOX-navroute").start()
            planning._maybe_extend()
    if ev == "CarrierJump":
        # the carrier moved with us: its position is the new system
        with ST.lock:
            ST.carrier = ST.db.get_carrier()
    planning._request_route()
    uithread._ui(panel._refresh)


def _on_carrier(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """CarrierLocation, CarrierStats: the own carrier's position."""
    with ST.lock:
        ST.carrier = ST.db.get_carrier()
    if ST.carrier:
        logger.info("fleet carrier now at %s", ST.carrier["system"])
        panel._set_status("carrier: %s" % ST.carrier["system"])
    uithread._ui(panel._refresh)


def _on_docked(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """Docked: only docking at a fleet carrier tells us something here."""
    if entry.get("StationType") == "FleetCarrier":
        _on_carrier(ev, entry, cmdr, state)


def _on_approach(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """ApproachBody, Touchdown: tick the body off the in-system route."""
    routewin._route_auto_tick(entry.get("Body") or entry.get("BodyName"),
                              "approach" if ev == "ApproachBody" else "landed")


def _on_loadout(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """Loadout: the ship, its jump range and tank."""
    if entry.get("ShipID") is not None:
        ST.fuel.set_ship((cmdr, entry.get("ShipID")))
    mj = entry.get("MaxJumpRange")
    if mj:
        ST.max_jump = float(mj)
        ST.fuel.max_jump = float(mj)
    cap = (entry.get("FuelCapacity") or {}).get("Main")
    if cap:
        ST.fuel.capacity = float(cap)


def _on_startup(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """StartUp (EDMC started with the game running): where we are, the
    plotted route, and a fresh look at the route's targets."""
    if entry.get("StarSystem"):
        ST.cur_system = entry["StarSystem"]
        ST.cur_id64 = entry.get("SystemAddress") or ST.cur_id64
        pos = star_pos(entry.get("StarPos"))
        if pos:
            ST.cur_pos = pos
        ST.awaiting_position = False
    if not ST.awaiting_position:
        uithread._run_async(survey._recheck_route, "game restart", label="route recheck")
    route = state.get("NavRoute") if state else None
    if route and route.get("Route"):
        cockpit._note_navroute(route.get("Route"))
    if route and cfg_bool(CFG["harvest_navroute"], True):
        with ST.lock:
            ST.db.ingest_journal_event({"event": "NavRoute",
                                        "Route": route.get("Route", [])})


def _on_liftoff(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """Liftoff: lifting off usually ends a pause spent on the surface."""
    uithread._run_async(survey._recheck_route, "lift-off", label="route recheck")


def _on_body_scan(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """Scans and signals of a body: queues, biology, route ticks."""
    if not ST.cur_id64 and entry.get("SystemAddress"):
        ST.cur_id64 = entry["SystemAddress"]
        ST.cur_system = (entry.get("StarSystem") or entry.get("SystemName")
                         or ST.cur_system)
    if ST.active:
        survey._prune_queues()
    if ev == "ScanOrganic":
        _bio_event(entry)
    if ev == "ScanOrganic" and entry.get("ScanType") == "Analyse":
        cockpit._bio_model_reset()          # one more find to learn from
    if ev in ("SAAScanComplete", "ScanOrganic"):
        routewin._route_auto_tick(entry.get("BodyName") or entry.get("Body"),
                                  "mapped" if ev == "SAAScanComplete" else "sampled")
    if ev in ("FSSAllBodiesFound", "SAAScanComplete", "ScanOrganic",
              "FSSBodySignals", "SAASignalsFound"):
        planning._request_route()
    uithread._ui(panel._refresh)


def _on_fsd_target(ev: str, entry: Dict[str, Any], cmdr: str, state: Dict[str, Any]) -> None:
    """FSDTarget: the briefing for the selected system; a probe target
    selected in the galaxy map is confirmed."""
    nm = entry.get("Name")
    cockpit._overlay_briefing("target", nm, entry.get("SystemAddress"),
                              entry.get("StarClass"))
    t = survey.current_probe()
    if t and nm == t.name:
        panel._set_status("confirmed: %s" % nm)
        if ST.active:
            survey._prune_queues()
    if ST.active:
        survey._prune_known_probes()
    uithread._ui(panel._refresh)


_HANDLERS = {
    "FSDJump": _on_arrival,
    "Location": _on_arrival,
    "CarrierJump": _on_arrival,      # also refreshes the carrier (see there)
    "CarrierLocation": _on_carrier,
    "CarrierStats": _on_carrier,
    "Docked": _on_docked,
    "ApproachBody": _on_approach,
    "Touchdown": _on_approach,
    "Loadout": _on_loadout,
    "StartUp": _on_startup,
    "Liftoff": _on_liftoff,
    "Scan": _on_body_scan,
    "SAAScanComplete": _on_body_scan,
    "SAASignalsFound": _on_body_scan,
    "FSSBodySignals": _on_body_scan,
    "FSSDiscoveryScan": _on_body_scan,
    "FSSAllBodiesFound": _on_body_scan,
    "ScanOrganic": _on_body_scan,
    "FSDTarget": _on_fsd_target,
}


TRACK_STEP_M = 25.0       # store a point after this much movement ...
TRACK_MIN_S = 10.0        # ... or after this long when moved at least 3 m
TRACK_MAX_ALT = 25000.0   # metres: higher than this is flying, not exploring


def _surface_status(entry: Dict[str, Any]) -> None:
    """
    Status.json on or near a body: extend the surface track and update the
    exobiology distance line. The track exists nowhere else - the journal
    has no position stream - so it only grows while the plugin runs.
    """
    if not ST.db or "Flags" not in entry:
        return
    with ST.lock:
        pos = ST.db.note_status(entry)
    if not pos or not ST.cur_id64:
        ST.last_track = None
        return
    radius = float(pos.get("radius") or 0.0)
    alt = pos.get("alt")
    low = pos["landed"] or pos["mode"] != "ship" or (alt is not None and alt < TRACK_MAX_ALT)
    now = time.time()
    if low and radius > 0:
        last = ST.last_track
        moved = (surface_distance_m(last["lat"], last["lon"], pos["lat"], pos["lon"], radius)
                 if last and last["body"] == pos["body"] else None)
        if (moved is None or moved >= TRACK_STEP_M or last["mode"] != pos["mode"]
                or (now - last["t"] >= TRACK_MIN_S and moved >= 3.0)):
            with ST.lock:
                ST.db.add_track_point(ST.cur_id64, pos, now)
            ST.last_track = dict(pos, t=now)
    _nav_overlay(pos, radius, now, low)
    _bio_distance_line(pos, radius, now)


NAV_EVERY_S = 1.0         # compass refresh while a position is reported
NAV_LOST_S = 30.0         # how often the compass looks at the loss marks again


def _nav_lost(sys_id64: int, body_id: Optional[int]) -> List[str]:
    """Loss marks of this body for the commander playing (caller holds ST.lock)."""
    try:
        return ST.db.lost_of_body(ST.db.view_fid(CURRENT), sys_id64, body_id)
    except Exception:
        logger.debug("nav: lost marks failed", exc_info=True)
        return []


def _nav_overlay(pos: Dict[str, Any], radius: float, now: float, low: bool) -> None:
    """
    Overlay compass: direction and distance to the parked SRV, the parked
    ship, unfinished species and earlier finds on this body. Status.json
    reports the position in orbital cruise as well, so on the way down the
    same block lists what is known on the body ("KNOWN POINTS").
    """
    ov = getattr(ST, "overlay", None)
    if (ov is None or not ov.enabled or radius <= 0 or not ST.cur_id64
            or not cfg_bool(CFG["overlay_nav"], True) or now - ST._nav_shown < NAV_EVERY_S):
        return
    ST._nav_shown = now
    # a crash writes no surface mark: look at the loss marks twice a minute
    key = (ST.cur_id64, pos["body"], ST.db.marks_rev, int(now // NAV_LOST_S))
    c = ST._nav_cache
    if c is None or c[0] != key:
        with ST.lock:
            marks = [dict(m) for m in ST.db.marks_of(ST.cur_id64, pos["body"])]
            r = ST.db.cx.execute("SELECT body_id, sig_bio, genuses FROM bodies WHERE "
                                 "sys_id64=? AND name=?", (ST.cur_id64, pos["body"])).fetchone()
            lost = _nav_lost(ST.cur_id64, r["body_id"] if r else None)
        genera = [g for g in ((r["genuses"] if r else None) or "").split(",") if g]
        c = ST._nav_cache = (key, marks, r["sig_bio"] if r else None, genera, lost)
        _bio_resume(pos["body"], marks)
    from overlay import COL
    lines = surfacenav.compass_lines(pos, c[1], radius, sig_bio=c[2], genera=c[3],
                                     colours=COL, orbit=not low, lost=c[4])
    if lines:
        ov.show_nav(lines, seconds=4)


MINE_EVERY_S = 5.0


def _mining_overlay(force: bool = False) -> None:
    """Overlay mining block (at most five lines) while you mine; gone ten
    minutes after the last mining event."""
    ov = getattr(ST, "overlay", None)
    if ov is None or not ov.enabled or not cfg_bool(CFG["overlay_mining"], True):
        return
    now = time.time()
    if not ST.mine.active(now):
        if ST._mine_drawn:
            ov.clear("mine")
            ST._mine_drawn = False
        ov.mute_route(False)                 # the route targets come back
        return
    ov.mute_route(True)                      # while mining they are no help
    if not force and now - ST._mine_shown < MINE_EVERY_S:
        return
    ST._mine_shown = now
    from overlay import COL
    if ov.show_mining(ST.mine.lines(now, COL), seconds=30):
        ST._mine_drawn = True


def _bio_resume(body: str, marks: List[Dict[str, Any]]) -> None:
    """After an EDMC restart mid-sampling: pick up the species in progress."""
    if ST.bio_active is not None:
        return
    todo = [s for s in surfacenav.body_state(marks)["species"]
            if not s["analysed"] and s["points"] and s["samples"] < 3]
    if todo:
        s = max(todo, key=lambda x: x["last"] or "")
        ST.bio_active = {"body": body, "species": s["species"], "genus": s["genus"],
                         "points": list(s["points"])}


def _bio_distance_line(pos: Dict[str, Any], radius: float, now: float) -> None:
    """Overlay: distance to the previous samples of the species in progress."""
    b = ST.bio_active
    if not b or b["body"] != pos["body"] or radius <= 0 or not b["points"]:
        return
    if now - ST._bio_shown < 1.0:
        return
    ST._bio_shown = now
    rng = COLONY_RANGE_M.get(b["genus"] or "")
    near = min(surface_distance_m(la, lo, pos["lat"], pos["lon"], radius)
               for la, lo in b["points"])
    ok = rng is not None and near >= rng
    from overlay import COL
    head = "BIO > %s  %d/3" % ((b["species"] or "?")[:30], len(b["points"]) + 1)
    if rng is None:
        line = ("%.0f m from nearest sample (range unknown)" % near, COL["dim"])
    else:
        line = ("%.0f m / %d m  %s" % (near, rng, "OK - sample here" if ok else "too close"),
                COL["data"] if ok else COL["warn"])
    ov = getattr(ST, "overlay", None)
    if ov is not None and ov.enabled:
        ov.show_bio([(head, COL["head"]), line], seconds=6)


def _bio_event(entry: Dict[str, Any]) -> None:
    """Follow Log -> Sample -> Analyse of one species for the distance line."""
    kind = entry.get("ScanType")
    pos = ST.db._pos if ST.db else None
    body = pos["body"] if pos else None
    species = entry.get("Species_Localised") or entry.get("Species")
    genus = entry.get("Genus_Localised") or entry.get("Genus")
    if kind == "Analyse":
        ST.bio_active = None
        ov = getattr(ST, "overlay", None)
        if ov is not None:
            from overlay import COL
            ov.show_bio([("BIO > %s analysed" % (species or "?")[:30], COL["data"])],
                        seconds=6)
        return
    if kind not in ("Log", "Sample") or not pos:
        return
    b = ST.bio_active
    if kind == "Log" or not b or b["species"] != species or b["body"] != body:
        b = ST.bio_active = {"body": body, "species": species, "genus": genus, "points": []}
    b["points"].append((pos["lat"], pos["lon"]))


def dashboard_entry(cmdr: str, is_beta: bool, entry: Dict[str, Any]) -> None:
    """EDMC hook: Status.json changed, on the main thread. Surface position,
    the overlay's focus, mining, fuel, and the selected destination (the
    Destination field carries the id64 of any selected target). Never raises."""
    try:
        _surface_status(entry)
    except Exception:
        logger.debug("surface status failed", exc_info=True)
    # Which game screen is in front - the overlay steps aside for the maps,
    # FSS, DSS, codex and station services. Before any other check: it must
    # work even with destination harvesting switched off.
    ov = getattr(ST, "overlay", None)
    if ov is not None and "Flags" in entry:
        try:
            ov.set_focus(entry.get("GuiFocus", 0))
        except Exception:
            logger.debug("overlay focus failed", exc_info=True)
    try:
        ST.mine.status(entry)                # target hotspot -> material
        _mining_overlay()                    # rate and ages move on; at most every 5 s
    except Exception:
        logger.debug("mining overlay failed", exc_info=True)
    if not ST.db or not cfg_bool(CFG["harvest_destination"], True):
        return
    try:
        _status_fuel(entry)
        _status_destination(entry)
    except Exception:
        logger.exception("dashboard_entry failed")


def _status_fuel(entry: Dict[str, Any]) -> None:
    """The main tank's level from Status.json."""
    fuel = entry.get("Fuel") or {}
    if fuel.get("FuelMain") is not None:
        try:
            ST.fuel.level = float(fuel["FuelMain"])
        except (TypeError, ValueError):
            pass


def _status_destination(entry: Dict[str, Any]) -> None:
    """A newly selected destination: a system selected in the galaxy map is
    confirmed to exist - store it, and drop it from the queues."""
    dest = entry.get("Destination")
    if not dest:
        return
    a = dest.get("System")
    if not a or a == ST.last_dest_id64:
        return
    ST.last_dest_id64 = a
    with ST.lock:
        new = ST.db.ingest_status_destination(dest)
    if new:
        logger.info("new system confirmed via target selection: %s", new)
        panel._set_status("confirmed: %s" % new)
        if ST.active:
            survey._prune_queues()
            survey._prune_known_probes()
    uithread._ui(panel._refresh)
