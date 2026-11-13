# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The survey itself: start, stop, targets and queues.

Starting and stopping a survey, restoring the session at EDMC start,
the current flight and probe targets, the galaxy map checks (absent,
list end, skip), copying names to the clipboard, and keeping the queues
sorted and pruned. Also the measured work model (DSS, sampling times).
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from . import journalscan
from .boxelplan import K_BIO, K_DSS, K_NEW, K_SCAN, Target, bundled_probe_prefix, set_origin
from .deepspace import best_staging, staging_lines
from .procgen import boxel_prefix
from .sysdb import PLAN
from .sysroute import (bodies_from_rows, calibrate_from_journal, calibrate_work_from_journal,
                       leg_distance_ls, plan_route, resolve_positions, shorten)
from .state import CFG, ST, cfg_bool, get_masscodes, logger
from . import maintenance
from . import panel
from . import planning
from . import probewin
from . import routewin
from . import uithread
from . import updater


def _measure_work(ev: str, entry: Dict[str, Any]) -> None:
    """
    Time the work at a body as it happens (journalscan.WorkMeter, the same
    code as the replay at start). A surface scan is bracketed by the arrival
    and SAAScanComplete, a sample by its own Log and Analyse; nothing can
    stretch them except the commander pausing, which the trimmed median
    then discards. Fed with every event, so it knows arrivals and jumps.
    """
    try:
        got = ST.work_meter.feed(entry, time.time())
        if not got:
            return
        (ST.work_dss if got[0] == "dss" else ST.work_bio).append(got[1])
        total = len(ST.work_dss) + len(ST.work_bio)
        if total and total % 5 == 0:
            ST.cost_model = calibrate_work_from_journal(
                ST.work_dss, ST.work_bio, ST.work_approach, ST.cost_model)
            logger.info("work model recalibrated: %s", ST.cost_model.as_dict())
    except Exception:
        logger.exception("work measurement failed")


def _bootstrap_work_model() -> None:
    """Measure the work constants once from the existing journals."""
    d = maintenance._journal_dir()
    if not d:
        return
    m = journalscan.replay_work(journalscan.journal_files(d, 30))
    dss, bio, sc_legs = m.dss, m.bio, m.sc_legs
    ST.work_dss, ST.work_bio = dss, bio
    before = ST.cost_model.as_dict()
    ST.cost_model = calibrate_work_from_journal(dss, bio, [], ST.cost_model)
    logger.info("work model from %d DSS and %d bio measurements: %s",
                len(dss), len(bio), ST.cost_model.as_dict())
    # travel: body -> body legs, distance from the orbits at flight time
    segs: List[Tuple[float, float]] = []
    if sc_legs and ST.db:
        rows_of: Dict[int, List[Any]] = {}
        for sys_id, a, b, t0, secs in sc_legs:
            if sys_id not in rows_of:
                with ST.lock:
                    rows_of[sys_id] = ST.db.bodies_of(sys_id)
            d = leg_distance_ls(rows_of[sys_id], a, b, at=t0)
            if d and d > 1.0:
                segs.append((d, secs))
    if segs:
        ST.sc_segments = segs[-200:]
        before = ST.cost_model
        ST.cost_model = calibrate_from_journal(ST.sc_segments, ST.cost_model)
        if ST.cost_model is before:
            logger.info("supercruise model unchanged: %d body-to-body legs "
                        "measured, not enough clean ones to fit yet "
                        "(%.0f s + %.1f * sqrt(LS) kept)", len(segs),
                        before.entry, before.k)
        else:
            logger.info("supercruise model from %d body-to-body legs: "
                        "%.0f s + %.1f * sqrt(LS) (%d used)", len(segs),
                        ST.cost_model.entry, ST.cost_model.k,
                        ST.cost_model.samples)
    if before == ST.cost_model.as_dict():
        logger.info("work model unchanged - too few measurements yet")


def _bootstrap_session() -> None:
    """Establish fuel, work timings and last position from the journals."""
    try:
        _bootstrap_fuel()
    except Exception:
        logger.exception("fuel bootstrap failed")
    try:
        _bootstrap_work_model()
    except Exception:
        logger.exception("work model bootstrap failed")
    try:
        _bootstrap_last_body()
    except Exception:
        logger.exception("last position bootstrap failed")
    try:
        updater._check_for_update()
    except Exception:
        logger.exception("update check failed")
    uithread._ui(panel._refresh)


def _bootstrap_last_body() -> None:
    """Recover the last body we were at (journalscan.last_body)."""
    d = maintenance._journal_dir()
    if not d:
        return
    lb = journalscan.last_body(d)
    if lb:
        ST.last_body_id = lb["body_id"]
        ST.last_body_name = lb["name"]
        ST.last_body_sys = lb["sys"]
        logger.info("last known position: %s (body %d)",
                    ST.last_body_name or "?", ST.last_body_id)
        return
    logger.info("last position unknown - no body approach in recent journals")


def _bootstrap_fuel() -> None:
    """Read ship fuel figures out of the recent journals."""
    d = maintenance._journal_dir()
    if not d:
        return
    journalscan.replay_fuel(journalscan.journal_files(d, 6), ST.fuel)
    logger.info("fuel | %s", ST.fuel.summary())


def _plan_staging() -> None:
    """Work out where the carrier should go next, tritium permitting."""
    if not (ST.db and ST.planner and ST.center):
        panel._set_status("no active sphere")
        return
    with ST.lock:
        rows = best_staging(ST.db, ST.planner, ST.center, ST.radius,
                            get_masscodes())
    ST.staging = rows
    for line in staging_lines(rows):
        logger.info("carrier | %s", line)
    if rows:
        panel._set_status("next carrier spot: %s (%.0f ly, %d icy rings)"
                          % (rows[0]["name"], rows[0]["dist"], rows[0]["icy_rings"]))
    else:
        panel._set_status("no tritium system known far enough out yet")


def _recheck_route(reason: str) -> None:
    """
    After a pause, ask whether the planned order still holds.

    Bodies keep orbiting while the game is paused, landed or shut down. The
    effect is small over minutes - the worst case in the test data is 0.53 LS
    after 20 minutes - but it compounds: 3.2 LS after two hours and 15.2 LS
    after twelve, on a moon with a 32 hour period. Over an overnight break the
    near bodies of a tight system can genuinely reorder.

    So rather than rebuild blindly, the old and the new order are compared and
    the route is only replaced when it actually changed.
    """
    if not (ST.db and ST.cur_id64):
        return
    before = [s.body.body_id for s in ST.route.stops] if ST.route else []
    before_ls = ST.route.total_ls if ST.route else 0.0
    routewin._rebuild_route()
    after = [s.body.body_id for s in ST.route.stops] if ST.route else []
    if not before or not after:
        return
    if before == after:
        logger.info("route | %s: order still optimal (%.0f LS)",
                    reason, before_ls)
        return
    delta = (ST.route.total_ls - before_ls)
    logger.info("route | %s: order changed, %.0f LS -> %.0f LS (%+.0f)",
                reason, before_ls, ST.route.total_ls, delta)
    panel._set_status("route re-ordered after %s (%+.0f LS)" % (reason, delta))


def _route_review() -> None:
    """
    Compare what actually happened against what the route suggested.

    The journal records every body you approached (ApproachBody) and every
    drop-out (SupercruiseExit), in order and with timestamps. Replaying that
    for the current system gives the real order flown, the real distance
    covered and the real time taken - which can be measured against the
    planned tour. That is honest feedback: not "you did it wrong", but "this
    is what the detour cost".
    """
    uithread._run_async(_route_review_worker, label="review")


def _route_review_worker() -> None:
    if not (ST.db and ST.cur_id64 and ST.route and ST.route.stops):
        panel._set_status("no route to review")
        return
    visits = _actual_visits(ST.cur_id64)
    if not visits:
        logger.info("review | no approaches recorded for %s yet", ST.cur_system)
        panel._set_status("nothing flown here yet")
        return

    with ST.lock:
        rows = ST.db.bodies_of(ST.cur_id64)
    bodies = bodies_from_rows(rows)
    for b in bodies.values():
        b.short = shorten(b.name, ST.cur_system or "")
    resolve_positions(bodies)          # needed before any distance is measured
    by_name = {b.name: b for b in bodies.values()}

    # what was actually flown, in order, with real distances
    seq = [by_name[n] for n, _ in visits if n in by_name and by_name[n].pos]
    if len(seq) < 2:
        panel._set_status("only %d stop flown here so far" % len(seq))
        return
    actual_ls = 0.0
    prev = (0.0, 0.0, 0.0)
    for b in seq:
        actual_ls += math.dist(prev, b.pos)
        prev = b.pos
    actual_s = visits[-1][1] - visits[0][1]

    # the best possible tour over exactly those bodies
    subset = {b.body_id: b for b in seq}
    ideal = plan_route(ST.cur_system or "", subset, model=ST.cost_model,
                       only_work=False)
    ideal_ls = ideal.total_ls

    over = (100.0 * (actual_ls - ideal_ls) / ideal_ls) if ideal_ls > 1 else 0.0
    switches = _count_switches(seq, bodies)

    logger.info("review | %s: %d bodies flown", ST.cur_system, len(seq))
    logger.info("review | flown %.0f LS in %.0f min, %d planet changes",
                actual_ls, actual_s / 60.0, switches)
    logger.info("review | best possible over the same bodies %.0f LS (%+.0f%%)",
                ideal_ls, over)
    logger.info("review | order flown: %s",
                " -> ".join(b.short for b in seq[:12])
                + (" ..." if len(seq) > 12 else ""))
    if over > 25:
        logger.info("review | a shorter order existed: %s",
                    " -> ".join(s.body.short for s in ideal.stops[:12]))
        panel._set_status("review: %.0f LS flown, %.0f%% above the best order "
                          "(details in log)" % (actual_ls, over))
    else:
        panel._set_status("review: %.0f LS flown, within %.0f%% of the best order"
                          % (actual_ls, max(0.0, over)))


def _actual_visits(sys_id64: int) -> List[Tuple[str, float]]:
    """(body name, unix time) for every body approached in this system, in
    order, from the newest journals (journalscan.approached_bodies)."""
    return journalscan.approached_bodies(maintenance._journal_dir(), sys_id64, 8)


def _count_switches(seq, bodies) -> int:
    """How often the flown order moved from one planetary system to another."""
    from sysroute import group_label
    n = 0
    last = None
    for b in seq:
        g = group_label(b)
        if last is not None and g != last:
            n += 1
        last = g
    return n


def _start_survey() -> None:
    """
    Free start  - the sphere is centred on the current system.
    Carrier start - the sphere is centred on the remembered fleet carrier,
                    so it stays put while you range around it.
    """
    use_carrier = bool(panel._carrier_var.get()) if panel._carrier_var else False
    if use_carrier:
        if not (ST.carrier and ST.carrier.get("coords")):
            panel._set_status("no carrier position known - dock at it once")
            return
        center = tuple(ST.carrier["coords"])
        label = ST.carrier["system"]
        origin_kind = "carrier"
    else:
        if not ST.cur_pos:
            panel._set_status("position unknown - jump first")
            return
        center = ST.cur_pos
        label = ST.cur_system
        origin_kind = "free"

    if ST.active and ST.center and ST.center != center:
        logger.info("survey re-centred: %s -> %s", ST.start_system, label)

    radius = float(panel._radius_var.get()) if panel._radius_var else 50.0

    with ST.lock:
        ov = ST.db.sphere_overlap(center, radius)
    if ov["volume_pct"] > 0.5:
        msg = ("overlap %.0f%% with earlier spheres (worst %s at %.0f ly, %.0f%%); "
               "%d of %d known systems already visited"
               % (ov["volume_pct"], ov["worst_label"] or "-",
                  ov["worst_distance"] or 0.0, ov["worst_pct"],
                  ov["visited"], ov["known"]))
        logger.info(msg)
        panel._set_status("overlap %.0f%% | %d systems already visited | move %.0f ly for none"
                          % (ov["volume_pct"], ov["visited"], ov["clear_distance"]))
    else:
        logger.info("fresh sphere, no overlap with earlier work")

    ST.center = center
    ST.start_system = label
    ST.radius = radius
    ST.active = True
    ST.finished_announced = False
    with ST.lock:
        ST.sphere_id = ST.db.record_sphere(center, radius, label, origin_kind)
        ST.db.save_survey(True, label, center, radius, get_masscodes())
    uithread._run_async(_start_worker, label="starting survey")


def _start_worker() -> None:
    ST.horizon = 0.0
    ST.edd_asked = set()
    planning._fetch_local()
    planning._advance_horizon(allow_fetch=True)
    planning._rebuild_plan()


def _stop_survey() -> None:
    ST.active = False
    if ST.sphere_id and ST.stats.get("finished"):
        with ST.lock:
            ST.db.close_sphere(ST.sphere_id)
    with ST.lock:
        ST.db.save_survey(False, ST.start_system, ST.center, ST.radius, get_masscodes())
    ST.flight = []
    ST.probe = []
    panel._refresh()


# ============================================================================
# Target logic
# ============================================================================

def current_flight() -> Optional[Target]:
    return ST.flight[0] if ST.flight else None


def current_probe() -> Optional[Target]:
    return ST.probe[0] if ST.probe else None


def _probe_absent() -> None:
    """
    Button: the candidate does not exist according to the galaxy map.

    Because n2 runs contiguously from 0, a miss at -n proves that -n, -n-1,
    -n-2 ... do not exist either. The whole boxel is closed at once and every
    queued candidate above that number is dropped immediately.
    """
    t = current_probe()
    if not t:
        return
    with ST.lock:
        closes = ST.db.mark_absent(t.name)
    if not closes:
        # 4.10: below the highest known number the slot exists - under
        # another name (a catalogue star: "Synuefe RH-U c19-0" is HIP 33254)
        ST.probe = [q for q in ST.probe if q.name != t.name]
        logger.info("%s not in the galaxy map - slot %s exists under another name "
                    "(catalogue star), boxel %s stays open", t.name, t.n2, t.boxel_key)
        panel._set_status("%s: no system of this name - slot %s has another name "
                          "(catalogue star); the boxel stays open" % (t.name, t.n2))
        panel._refresh()
        _copy_probe()
        return
    dropped = 0
    if t.boxel_key is not None and t.n2 is not None:
        keep = []
        for q in ST.probe:
            if q.boxel_key == t.boxel_key and q.n2 is not None and q.n2 >= t.n2:
                dropped += 1
                continue
            keep.append(q)
        ST.probe = keep
    else:
        ST.probe.pop(0)
    logger.info("%s does not exist - boxel %s closed, %d further candidates dropped",
                t.name, t.boxel_key, max(0, dropped - 1))
    panel._set_status("%s does not exist - boxel closed (%d candidates dropped)"
                      % (t.name, max(0, dropped - 1)))
    panel._refresh()
    _copy_probe()


def _list_end() -> None:
    """
    "list ends at [n]" (4.10, replaces "boxel done"): the highest number the
    galaxy map lists under this prefix. The boxel ends there; every probe
    above it leaves the queue. Every slot up to it exists - a number missing
    from the list is a catalogue star -, so the numbers nobody knows yet stay
    as certain gaps: pick one in the map's list and it is confirmed and the
    next one comes up. The field starts with the highest number the plugin
    knows; a smaller number is refused (the list was cut off).
    """
    t = current_probe()
    if not t or not t.boxel_key:
        return
    key = t.boxel_key
    _prune_known_probes()          # names known meanwhile are no gaps any more
    raw = (probewin._list_end_var.get() if probewin._list_end_var is not None else "").strip()
    raw = raw.rsplit("-", 1)[-1].strip()       # "Synuefe RH-U c19-21" works too
    try:
        last = int(raw)
    except ValueError:
        panel._set_status("type the highest number the galaxy map lists for %s"
                          % boxel_prefix(key))
        return
    with ST.lock:
        top = ST.db.boxel_known_max(key)
        end = ST.db.close_boxel(key, last)
    if end is None:
        panel._set_status("%s%d is known - the list goes at least that far; scroll the "
                          "galaxy map list to its end" % (boxel_prefix(key), top))
        return
    before = len(ST.probe)
    ST.probe = [q for q in ST.probe
                if not (q.boxel_key == key and q.n2 is not None and q.n2 > last)]
    dropped = before - len(ST.probe)
    left = sum(1 for q in ST.probe if q.boxel_key == key)
    logger.info("boxel %s: galaxy map list ends at %d (known to %s) - closed, %d "
                "candidates above dropped, %d gaps left", key, last,
                "-" if top is None else top, dropped, left)
    panel._set_status("%s ends at %d - %d dropped%s" % (
        boxel_prefix(key), last, dropped,
        (", %d in the list nobody knows: pick them in the map" % left) if left else ""))
    if top is None or last > top:
        # numbers above what was known exist: the plan gets them as gaps
        uithread._run_async(planning._rebuild_plan, label="replanning")
    panel._refresh()
    _copy_probe()


def _prune_known_probes() -> None:
    """Drop every probe candidate that is known now - not only the head of
    the queue: picking any name of the galaxy map's list confirms it."""
    if not ST.db or not ST.probe:
        return
    with ST.lock:
        keep = [q for q in ST.probe if ST.db.system(q.name) is None]
    if len(keep) != len(ST.probe):
        ST.probe = keep
        uithread._ui(panel._refresh)


def _copy_prefix() -> None:
    """Copy the boxel search prefix - one paste lists the whole boxel."""
    t = current_probe()
    if t and t.boxel_key:
        _copy(boxel_prefix(t.boxel_key))
    else:
        panel._set_status("no boxel prefix for this candidate")


def _copy_bundle() -> None:
    """Copy one prefix for several of the next probe boxels (same sector,
    letters and mass code) - one paste in the galaxy map lists them all."""
    prefix, keys = bundled_probe_prefix(ST.probe, 5)
    if not prefix:
        panel._set_status("no probe boxels to bundle")
        return
    _copy(prefix)
    if len(keys) > 1:
        tails = ", ".join(k[len(prefix):] or k.split()[-1] for k in keys)
        panel._set_status("'%s' lists the next %d probe boxels (%s) - and the other "
                          "boxels starting with it" % (prefix, len(keys), tails))
    else:
        panel._set_status("only one of the next boxels in this group - '%s' copied"
                          % prefix)


def _probe_skip() -> None:
    if ST.probe:
        ST.probe.append(ST.probe.pop(0))
    panel._refresh()
    _copy_probe()


def _flight_skip() -> None:
    if ST.flight:
        ST.flight.append(ST.flight.pop(0))
    panel._refresh()
    _copy_flight()


def _copy(text: str) -> None:
    if not panel._frame or not text:
        return
    try:
        panel._frame.clipboard_clear()
        panel._frame.clipboard_append(text)
        panel._frame.update_idletasks()
        panel._set_status("copied: %s" % text)
    except Exception as e:
        logger.warning("clipboard: %s", e)


def _copy_flight() -> None:
    if cfg_bool(CFG["autocopy"], True):
        t = current_flight()
        if t:
            _copy(t.name)


def _copy_carrier() -> None:
    """Put the carrier system on the clipboard - the way home."""
    if ST.carrier and ST.carrier.get("system"):
        _copy(ST.carrier["system"])
    else:
        panel._set_status("no carrier system remembered yet")


def _copy_probe() -> None:
    t = current_probe()
    if t:
        _copy(t.name)


def _resort_queues() -> None:
    """Re-rank both queues by distance from the commander's current position."""
    if not ST.cur_pos:
        return
    for q in (ST.flight, ST.probe):
        set_origin(q, ST.cur_pos)
        q.sort(key=lambda t: (int(t.dist_origin // 5), t.dist_origin))


def _prune_queues() -> None:
    """Drop completed targets from the head of both queues."""
    if not ST.db:
        return
    changed = False
    with ST.lock:
        while ST.flight:
            t = ST.flight[0]
            row = ST.db.system(t.name)
            done = False
            if t.kind == K_NEW:
                done = ST.db.is_visited(row, PLAN)
            elif row is not None and row["id64"]:
                p = ST.db.system_progress(row["id64"], PLAN)
                if t.kind == K_SCAN:
                    done = p["fss_complete"] or (
                        p["body_count"] and p["scanned"] >= p["body_count"])
                elif t.kind == K_DSS:
                    done = not p["dss_open"]
                elif t.kind == K_BIO:
                    done = not p["bio_open"]
            if not done:
                break
            ST.flight.pop(0)
            changed = True
        # every known name, not only the head: a plotted route or a pick
        # in the galaxy map's list can confirm any of them (4.10 fix - a
        # stale entry kept "1 gaps left" after "list end")
        keep = [q for q in ST.probe if ST.db.system(q.name) is None]
        if len(keep) != len(ST.probe):
            ST.probe = keep
            changed = True
    if changed:
        panel._refresh()
