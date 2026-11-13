# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Survey planning and the local-first data flow.

Fills the database from the local sources first (journal, EDDiscovery's
file) and asks the online sources only shell by shell (``_advance_horizon``),
through netgate's gateway. Builds the plan of flight and probe targets,
handles a commander switch and requests the in-system route. Runs mostly
in worker threads; the panel is updated through ``uithread._ui``.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import journalscan
from . import netgate
from . import shells
from .boxelplan import K_EMPTY, K_PROBE, Planner, Target, corridor_targets
from .deepspace import tritium_systems
from .sysdb import CURRENT, Q_EXTERNAL, Q_JOURNAL, Q_UNKNOWN
from .state import CFG, ST, cfg_bool, cfg_int, cfg_str, get_masscodes, logger
from . import cockpit
from . import maintenance
from . import panel
from . import probewin
from . import routewin
from . import statswin
from . import survey
from . import uithread


def _flush_net_log() -> List[Tuple]:
    """Move the gateway's recorded requests into the database call log
    (on the caller's thread, under ST.lock). Returns the records."""
    rec = ST.net.drain()
    if rec:
        with ST.lock:
            if ST.db:
                try:
                    ST.db.log_external_calls(rec)
                except Exception:
                    logger.exception("could not store the external call log")
    return rec


def _log_net(rec: List[Tuple]) -> None:
    """One line per fetch in the EDMC log: requests per service."""
    if not rec:
        return
    per: Dict[str, List[int]] = {}
    for _ts, svc, _ep, _st, ok, ms in rec:
        c = per.setdefault(svc, [0, 0, 0])
        c[0] += 1
        c[1] += 0 if ok else 1
        c[2] += ms
    logger.info("external requests: %s", ", ".join(
        "%s %d (%d failed, %.1f s)" % (k, v[0], v[1], v[2] / 1000.0)
        for k, v in sorted(per.items())))


def _store_rows(rows: List[Dict]) -> int:
    with ST.lock:
        n = 0
        for r in rows:
            if ST.db.upsert(r.get("name"), r.get("x"), r.get("y"), r.get("z"),
                            id64=r.get("id64"), source=r.get("source", "external"),
                            commit=False):
                n += 1
            for extra in r.get("also") or []:
                ST.db.upsert(r.get("name"), source=extra, quality=Q_UNKNOWN,
                             commit=False)
        ST.db.cx.commit()
    return n


def _fetch_into_db(keys: List[str], r_min: float, r_max: float
                   ) -> Tuple[int, Dict[str, bool], Dict[str, int]]:
    """Fetch the shell r_min..r_max around the survey centre from the given
    sources and store it. Returns (new systems, complete per source,
    systems per source)."""
    if ST.cur_id64 and ST.cur_pos:
        ST.sources.set_reference(ST.cur_id64, ST.cur_pos)
    for name, ok, why in ST.sources.status():
        logger.info("  source %-12s %-3s %s", name, "ok" if ok else "no", why)
    logger.info("fetching %s for %.0f-%.0f ly around %s", keys, r_min, r_max,
                ST.start_system or ST.center)
    rows, used = ST.sources.fetch_all(ST.center, r_max, keys,
                                      progress=lambda m: panel._set_status(m), r_min=r_min)
    ok = dict(ST.sources.last_ok)
    cnt = dict(ST.sources.last_count)
    _log_net(_flush_net_log())
    n = _store_rows(rows)
    logger.info("shell %.0f-%.0f ly: %d rows from %s -> %d new systems",
                r_min, r_max, len(rows), ", ".join(used) or "none", n)
    return n, ok, cnt


def _fetch_local(r_min: float = 0.0, r_max: float = 0.0) -> bool:
    """EDDiscovery's file is local - the whole sphere at once (or one shell),
    no network. While EDD runs its file can be locked; then it is read again
    later (_edd_retry). True when EDD delivered."""
    if not (ST.center and cfg_bool(CFG["src_edd"], True)):
        return False
    _n, ok, _cnt = _fetch_into_db(["edd"], r_min, r_max or ST.radius)
    if ok.get("edd"):
        ST.edd_pending = False
        try:
            # I1: this region was checked against EDD's data - only then may
            # the briefing say "in no database" there
            with ST.lock:
                ST.db.record_shell("edd", ST.center, r_min, r_max or ST.radius,
                                   _cnt.get("edd", 0), shells.ttl_seconds())
                # 4.10: this reading carried the id64s (catalogue slots)
                ST.db.set_meta(EDD_ID64_META, str(int(time.time())))
        except Exception:
            logger.debug("EDD shell not recorded", exc_info=True)
        return True
    if not ST.edd_pending:
        logger.info("EDDiscovery not readable now (%s) - read again later, "
                    "no online request for it",
                    ST.sources.sources["edd"].available()[1])
    ST.edd_pending = True
    ST.edd_next_try = time.time() + 60.0
    return False


def _edd_holds(service: str) -> bool:
    """Is EDDiscovery's file current and built from this service's data?
    Then the same systems are not asked online again (user, 10.11.)."""
    if not cfg_bool(CFG["src_edd"], True) or ST.edd_pending:
        return False
    try:
        return ST.sources.sources["edd"].is_current(service)
    except Exception:
        logger.exception("EDD freshness check failed")
        return False


def _edd_retry() -> None:
    try:
        if _fetch_local():
            logger.info("EDDiscovery read after all - plan rebuilt")
            _rebuild_plan()
    finally:
        ST.edd_retrying = False


def _online_services() -> List[str]:
    """Online sources switched on and willing to answer right now."""
    out = []
    for key in ("spansh", "edsm"):
        if not cfg_bool(CFG["src_%s" % key], True):
            continue
        ok, why = ST.sources.sources[key].available()
        if ok:
            out.append(key)
        else:
            logger.info("source %s not asked: %s", key, why)
    return out


def _plan_radius() -> float:
    """The planner plans only where the online sources have been asked."""
    return min(ST.radius, ST.horizon)


def _advance_horizon(allow_fetch: bool = True, force_to: float = 0.0) -> bool:
    """
    Push the horizon out shell by shell (shells.py). Shells that every
    online source delivered within their validity cost nothing and are
    taken at once; the first shell that needs asking is fetched (only with
    allow_fetch), and then it stops - one shell per need. With force_to
    every shell up to that radius is asked again (the reload button).
    True when the horizon moved.
    """
    if not (ST.active and ST.center):
        return False
    if not ST.fetch_lock.acquire(blocking=False):
        return False
    try:
        center = ST.center
        moved = False
        services = _online_services()
        edd_spansh = "spansh" in services and _edd_holds("spansh")
        if edd_spansh:
            services = [k for k in services if k != "spansh"]
            logger.info("horizon: Spansh not asked - EDDiscovery is current and "
                        "holds Spansh's data")
        if not services:
            logger.info("horizon: no online source to ask - planning on local "
                        "data to %.0f ly", ST.radius)
        for a, b in shells.shells_for(ST.radius):
            if b <= ST.horizon + 1e-6:
                continue
            forced = b <= force_to + 1e-6
            if edd_spansh:
                # Spansh's systems come from EDD's file for this shell - local
                with ST.lock:
                    sp = ST.db.valid_shells("spansh")
                if forced or not shells.is_fresh(center, a, b, sp):
                    _fetch_local(a, b)
            if not services:
                ST.horizon = b
                moved = True
                continue
            with ST.lock:
                regions = {k: ST.db.valid_shells(k) for k in services}
            todo = [k for k in services
                    if forced or not shells.is_fresh(center, a, b, regions[k])]
            if not todo:
                ST.horizon = b
                moved = True
                logger.info("horizon: shell %.0f-%.0f ly fetched before and "
                            "still valid - no request", a, b)
                continue
            if not allow_fetch:
                break
            n, ok, cnt = _fetch_into_db(todo, a, b)
            if ST.center != center:            # a new survey started meanwhile
                return moved
            with ST.lock:
                for k in todo:
                    if ok.get(k):
                        ST.db.record_shell(k, center, a, b, cnt.get(k, 0),
                                           shells.ttl_seconds())
            missing = [k for k in todo if not ok.get(k)]
            if missing:
                logger.info("horizon: %s did not deliver %.0f-%.0f ly completely"
                            " - asked again when needed", ", ".join(missing), a, b)
            ST.horizon = b
            moved = True
            panel._set_status("online data to %.0f of %.0f ly | %d new systems"
                              % (b, ST.radius, n))
            if not forced or b >= force_to - 1e-6:
                break
        return moved
    finally:
        ST.fetch_lock.release()


def _external_today_line() -> str:
    """'external today: EDSM 2 of 50 · Spansh 3 of 50' (+ offline / EDD)."""
    if ST.net.offline:
        line = "external today: offline mode - nothing is sent"
    else:
        line = "external today: " + " · ".join(
            "%s %d of %d" % (name, ST.net.today(k), netgate.DAILY_CAP[k])
            for k, name in (("edsm", "EDSM"), ("spansh", "Spansh")))
    if ST.edd_pending:
        line += " | EDDiscovery busy - read again later"
    elif _edd_holds("spansh"):
        line += " | Spansh covered by EDDiscovery (current)"
    return line


def _maybe_extend() -> None:
    """Fetch the next shell when it is needed: nothing left to fly to inside
    the horizon, or the commander near its edge. Also reads a busy
    EDDiscovery file again (local, at most once a minute)."""
    if not (ST.active and ST.center):
        return
    if ST.edd_pending and not getattr(ST, "edd_retrying", False) \
            and time.time() >= ST.edd_next_try:
        ST.edd_retrying = True
        ST.edd_next_try = time.time() + 60.0
        uithread._run_async(_edd_retry, label="EDDiscovery")
    if ST.extending:
        return
    left = len(ST.flight) + len(ST.probe)
    if shells.needs_next(ST.horizon, ST.radius, ST.center, ST.cur_pos, left):
        ST.extending = True
        uithread._run_async(_extend_worker, label="next shell")


def _extend_worker() -> None:
    try:
        moved = _advance_horizon(True)
    finally:
        ST.extending = False
    if moved:
        _rebuild_plan()


def _resume_worker() -> None:
    """EDMC start with a running survey: no request on the way in - only
    shells still valid count; the plan asks for more when it needs it.

    EDDiscovery's file is local: it is read again for the sphere when its
    last reading has expired, or once after the update to 4.10 (the rows
    read before carry no id64, and the slots of catalogue stars count only
    with one). So a restored sphere plans on the same data as a new one."""
    ST.horizon = 0.0
    ST.edd_asked = set()
    _edd_refresh()
    _advance_horizon(allow_fetch=False)
    _rebuild_plan()


def _edd_refresh() -> None:
    if not (ST.center and cfg_bool(CFG["src_edd"], True)):
        return
    with ST.lock:
        regions = ST.db.valid_shells("edd")
        done = ST.db.get_meta(EDD_ID64_META)
    if done and shells.is_fresh(ST.center, 0.0, ST.radius, regions):
        return
    logger.info("EDDiscovery read again for the sphere (%s) - local, no network",
                "expired" if done else "once for 4.10: id64s and catalogue stars")
    _fetch_local()


def _reload_online() -> None:
    """Reload button: ask the sources again for every shell up to the
    current horizon, paced like always."""
    if not (ST.active and ST.center):
        panel._set_status("no active survey")
        return
    old = max(ST.horizon, shells.SHELL_STEP)
    ST.horizon = 0.0
    _fetch_local()
    _advance_horizon(True, force_to=old)
    _rebuild_plan()


def _update_route_targets() -> None:
    """
    Suggest where to plot a NavRoute so its hops cross unprobed boxels.

    The game's route plotter knows the real galaxy; every hop of a plotted
    route lands in the database with exact coordinates, also when no public
    database has the system. Plotting is the commander's own action.
    """
    try:
        origin = ST.cur_pos or ST.center
        if not (origin and ST.center):
            ST.route_targets = []
            return
        jr = ST.max_jump or ST.fuel.max_jump or 40.0
        empties = [(t.x, t.y, t.z, t.score) for t in ST.probe
                   if t.kind == K_EMPTY and t.x is not None]
        with ST.lock:
            rows = ST.db.sphere(ST.center, ST.radius * 1.5, min_quality=Q_EXTERNAL)
        cands = [{"name": r["name"], "x": r["x"], "y": r["y"], "z": r["z"]}
                 for r in rows if not r["name"].startswith("#")]
        ST.route_targets = corridor_targets(origin, cands, empties, jr)
        _store_corridor(origin, jr)
        for r in ST.route_targets:
            logger.info("navroute | plot to %s: %.0f ly, ~%d jumps, %d unprobed "
                        "boxels on the way", r["name"], r["dist"], r["jumps"],
                        r["boxels"])
        uithread._ui(probewin._probe_window_refresh)
    except Exception:
        logger.exception("route target suggestion failed")


def _store_corridor(origin: Sequence[float], jump_range: float) -> None:
    """H3 #2: the suggestion for SHBOX FIS GALAXY (it opens the database
    read-only and cannot run the planner) - meta "route_corridor"."""
    half = min(20.0, max(10.0, max(10.0, float(jump_range or 0.0)) * 0.5))   # as corridor_targets
    doc = {"ts": time.time(), "half": round(half, 1),
           "from": [round(float(v), 2) for v in origin[:3]],
           "targets": [{"name": t["name"], "x": round(t["pos"][0], 2), "y": round(t["pos"][1], 2),
                        "z": round(t["pos"][2], 2), "ly": round(float(t["dist"]), 1),
                        "jumps": int(t["jumps"]), "boxels": int(t["boxels"])}
                       for t in ST.route_targets]}
    with ST.lock:
        ST.db.set_meta(cockpit.CORRIDOR_META, json.dumps(doc))


def _copy_route_target() -> None:
    if ST.route_targets:
        t = ST.route_targets[0]
        survey._copy(t["name"])
        panel._set_status("plot an ECONOMICAL route to %s - %d unprobed boxels on "
                          "the way, every hop lands in the database" % (t["name"], t["boxels"]))
    else:
        panel._set_status("no route target yet - start a survey first")


EDD_ID64_META = "edd_id64_410"     # EDD read again with id64s (4.10)
EDD_FILL_ROUNDS = 3
EDD_WALK_MAX = 64          # numbers walked upwards per boxel in one lookup


def _plan_build() -> Dict[str, Any]:
    with ST.lock:
        return ST.planner.build(
            ST.center, _plan_radius(),
            masscodes=get_masscodes(),
            probe_depth=max(0, cfg_int(CFG["probe_depth"], 2)),
            include_empty=cfg_bool(CFG["include_empty"], True),
            include_tasks=cfg_bool(CFG["include_tasks"], True),
            origin=ST.cur_pos)


def _edd_fill(probe: Sequence[Target]) -> int:
    """
    4.10: look the probe candidates up in EDDiscovery's file by id64 - local,
    read only, no network. A boxel reaches beyond the sphere and so do its
    gaps; EDD is read only to the sphere's radius, so up to 4.10 most
    "gaps - in no database" were systems EDD knew (945 of 950 in the
    developer's sphere). What EDD has is stored with its position and the
    candidate is gone; a catalogue star found there fills its slot.

    Where EDD has a probe above a boxel's maximum (or the first number of an
    "empty" boxel), it is asked for the next number of that boxel too, and
    so on until it has none - one plan rebuild instead of one per number
    (4.10 fix: with three rebuilds, 12 probes EDD knew were still left).
    Returns the number of systems found.
    """
    if not cfg_bool(CFG["src_edd"], True) or ST.edd_pending or ST.sources is None:
        return 0
    ids = [t.id64 for t in probe if t.id64 and t.id64 not in ST.edd_asked]
    if not ids:
        return 0
    edd = ST.sources.sources.get("edd")
    look = getattr(edd, "lookup_id64", None)
    if look is None:
        return 0
    try:
        if not edd.available()[0]:
            return 0
        rows = look(ids)
    except Exception:                           # never let it stop the plan
        logger.exception("EDD lookup by id64 failed")
        return 0
    if rows is None:
        return 0                                # busy: asked again next time
    ST.edd_asked.update(ids)
    if not rows:
        return 0
    asked = len(ids)
    upward = {t.id64 for t in probe if t.id64 and t.kind in (K_PROBE, K_EMPTY)}
    found = list(rows)
    frontier = [r["id64"] for r in rows if r["id64"] in upward]
    for _step in range(EDD_WALK_MAX):
        nxt = [i + (1 << (44 - 3 * (i & 7))) for i in frontier]
        nxt = [i for i in nxt if i not in ST.edd_asked]
        if not nxt:
            break
        try:
            more = look(nxt)
        except Exception:
            logger.exception("EDD lookup by id64 failed")
            more = None
        if not more:                            # none there, or busy: stop here
            if more is not None:
                ST.edd_asked.update(nxt)
            break
        ST.edd_asked.update(nxt)
        asked += len(nxt)
        found += more
        frontier = [r["id64"] for r in more]
    for r in found:
        r["source"] = edd.name
    _store_rows(found)
    logger.info("EDD by id64: %d of %d probe candidates are in EDDiscovery's file "
                "(beyond the radius it was read to; %d more above them) - stored, "
                "plan rebuilt", len(rows), len(ids), len(found) - len(rows))
    return len(found)


def _rebuild_plan() -> None:
    if not (ST.center and ST.planner):
        return
    if ST.active and ST.horizon <= 0.0:
        # nothing asked yet (new survey, or every shell expired): no plan
        # rather than one from nothing - the first shell is fetched now
        ST.flight, ST.probe, ST.plan_counts = [], [], {}
        ST.plan_info = "online data not asked yet - fetching the first shell"
        ST.stats_lines = ["online data: not asked yet - the first shell "
                          "(0-%.0f ly) is being fetched"
                          % min(ST.radius, shells.SHELL_STEP)]
        logger.info("plan: %s", ST.plan_info)
        uithread._ui(statswin._stats_window_refresh)
        _maybe_extend()
        return
    plan = _plan_build()
    # filling gaps raises a boxel's maximum, which brings new probes above
    # it - those are looked up too, a few rounds at most
    for _round in range(EDD_FILL_ROUNDS):
        if not _edd_fill(plan["probe"]):
            break
        plan = _plan_build()
    with ST.lock:
        ST.stats = ST.planner.statistics(plan)
    ST.flight = plan["flight"]
    ST.probe = plan["probe"]
    ST.plan_counts = plan["counts"]
    ST.plan_info = Planner.summary(plan)
    ST.stats_lines = Planner.stats_lines(ST.stats)
    uithread._ui(statswin._stats_window_refresh)
    try:
        with ST.lock:
            tri = tritium_systems(ST.db, ST.center, ST.radius)
        if tri:
            ST.stats_lines.append(
                "tritium: %d system%s with icy rings here (nearest %s at %.0f ly)"
                % (len(tri), "" if len(tri) == 1 else "s",
                   tri[0]["name"], min(t["dist"] for t in tri)))
        else:
            ST.stats_lines.append("tritium: none found in this sphere yet")
    except Exception:
        logger.exception("tritium summary failed")
    if ST.fuel.capacity:
        ST.stats_lines.append(ST.fuel.summary())
    if ST.horizon < ST.radius - 1e-6:
        ST.stats_lines.append("online data: asked to %.0f of %.0f ly - the next "
                              "shell is fetched when needed" % (ST.horizon, ST.radius))
    else:
        ST.stats_lines.append("online data: whole sphere (%.0f ly) asked" % ST.radius)
    ST.stats_lines.append(_external_today_line())
    for line in ST.stats_lines:
        logger.info("stats | %s", line)
    if ST.stats.get("finished") and not ST.finished_announced \
            and ST.horizon >= ST.radius - 1e-6:
        ST.finished_announced = True
        logger.info("AREA COMPLETE: sphere r=%.0f ly around %s is exhausted",
                    ST.radius, ST.start_system)
        panel._set_status("AREA COMPLETE - move on, next sphere >= %.0f ly away"
                          % (ST.radius * 2.0))
    logger.info("plan rebuilt: %d flight targets, %d probes | %s",
                len(ST.flight), len(ST.probe), ST.plan_counts)
    _update_route_targets()
    _maybe_extend()


def _current_system_from_journal() -> Optional[Tuple[str, int, Tuple[float, float, float]]]:
    """The current system out of the newest journal (journalscan.newest_location)."""
    return journalscan.newest_location(maintenance._journal_dir())


def _lost_here() -> str:
    """Route window: what of this system went down with the ship and is not
    redone yet - also when no stop is left (a lost scan is FSS work)."""
    if not (ST.db and ST.cur_id64):
        return ""
    try:
        with ST.lock:
            fid = ST.db.view_fid(CURRENT)
            mine = [d for d in ST.db.lost_summary(fid) if d["id64"] == ST.cur_id64]
    except Exception:
        logger.debug("lost summary failed", exc_info=True)
        return ""
    if not mine:
        return ""
    d = mine[0]
    bits = []
    if d["scan"]:
        bits.append("%d scan%s (FSS / honk again)" % (d["scan"], "" if d["scan"] == 1 else "s"))
    if d["map"]:
        bits.append("%d map%s" % (d["map"], "" if d["map"] == 1 else "s"))
    if d["bio"]:
        bits.append("bio: " + ", ".join(sorted(set(d["bio"]))))
    return "LOST in the crash %s: %s - redo" % ((d["ts"] or "")[:10], ", ".join(bits))


def _main_cmdr_choices() -> List[Tuple[str, str]]:
    """(label, FID) for the main-commander setting; '' = the suggestion."""
    if not ST.db:
        return []
    with ST.lock:
        cmdrs = ST.db.commanders()
        best = ST.db.suggest_main()
    name = {c["fid"]: c["name"] or c["fid"] for c in cmdrs}
    out = [("automatic (%s)" % name.get(best, "-"), "")]
    for c in sorted(cmdrs, key=lambda c: (c["name"] or c["fid"]).lower()):
        tag = "carrier" if c["carrier"] else "%d sessions" % c["logins"]
        out.append(("%s (%s)" % (name[c["fid"]], tag), c["fid"]))
    return out


def _apply_main_cmdr() -> None:
    """C1: the survey plan and statistics follow the main commander -
    the one chosen in the settings, else the suggestion (own carrier,
    then most sessions)."""
    if not ST.db:
        return
    try:
        with ST.lock:
            use = ST.db.set_main_commander(cfg_str(CFG["main_cmdr"], "") or None)
        logger.debug("main commander: %s", use)
    except Exception:
        logger.exception("could not set the main commander")


def _commander_switched() -> None:
    """
    Another commander logged in on this PC (two accounts share one journal
    folder and this database). Everything that belongs to where the last
    one was - system, route, ticks, last body - is dropped, and nothing is
    guessed from older journals (they are the other commander's): the new
    commander's Location, FSDJump or CarrierJump sets the system again.
    Before, the route was built for the previous commander's system for a
    while (10.11.: ~16 s, two rebuilds in parallel).
    """
    ST.awaiting_position = True
    ST.cur_system = None
    ST.cur_id64 = None
    ST.cur_pos = None
    ST.route = None
    ST.route_lines = []
    ST.route_done = set()
    ST.route_started = None
    ST.route_legs = []
    ST.route_feedback = ""
    ST.last_body_id = None
    ST.last_body_sys = None
    ST.last_body_name = ""
    logger.info("commander changed - waiting for the new commander's position")
    uithread._ui(routewin._route_window_refresh)
    uithread._ui(panel._refresh)


def _resolve_current_system() -> None:
    """Establish the current system if no jump has been seen this session."""
    if ST.cur_id64 or not ST.db or ST.awaiting_position:
        return
    found = _current_system_from_journal()
    if found:
        ST.cur_system, ST.cur_id64, ST.cur_pos = found
        logger.info("current system read from journal: %s", ST.cur_system)
        with ST.lock:
            ST.db.upsert(ST.cur_system, ST.cur_pos[0], ST.cur_pos[1],
                         ST.cur_pos[2], id64=ST.cur_id64, quality=Q_JOURNAL,
                         source="journal", visited=True)
        return
    with ST.lock:
        row = ST.db.cx.execute(
            "SELECT name, id64, x, y, z FROM systems WHERE visited=1 "
            "AND id64 IS NOT NULL ORDER BY visited_ts DESC LIMIT 1").fetchone()
    if row:
        ST.cur_system = row["name"]
        ST.cur_id64 = row["id64"]
        if row["x"] is not None:
            ST.cur_pos = (row["x"], row["y"], row["z"])
        logger.info("current system assumed from history: %s", ST.cur_system)


_route_lock = threading.Lock()
_route_last: List[float] = [0.0]
_route_pending = [False]


def _request_route(delay: float = 1.5) -> None:
    """
    Ask for a route rebuild, at most one at a time.

    A single arrival fires several events in quick succession - Location, the
    FSS sweep, then every SAAScanComplete - and each one used to trigger its
    own rebuild. The log showed four identical runs for one system. This
    collapses a burst into a single run shortly after it ends.
    """
    with _route_lock:
        if _route_pending[0]:
            _route_last[0] = time.time()
            return
        _route_pending[0] = True
        _route_last[0] = time.time()

    def waiter():
        while True:
            with _route_lock:
                quiet = time.time() - _route_last[0]
            if quiet >= delay:
                break
            time.sleep(0.25)
        with _route_lock:
            _route_pending[0] = False
        try:
            routewin._rebuild_route()
        except Exception:
            logger.exception("route rebuild failed")

    threading.Thread(target=waiter, daemon=True, name="SHBOX-route").start()
