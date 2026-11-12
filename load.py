# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SHBOXSEARCH v4.0 - systematic sphere survey for Elite Dangerous
===============================================================
EDMC plugin. Goal: fully explore and chart a radius around a start point,
deliberately hunting for systems that appear in no database at all.

Documentation: see README.md in the plugin folder.

Tested against EDMC 6.1.2 / Python 3.13.
Licence: MPL-2.0 (see LICENSE); 4.6 and earlier were released under MIT.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Dict, List, Optional, Sequence, Tuple

# EDMC API
import myNotebook as nb
from config import appname, config
from theme import theme

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.append(_PLUGIN_DIR)

from procgen import MASSCODES, boxel_prefix, parse_name        # noqa: E402
from sysdb import SystemDB, Q_ESTIMATE, Q_EXTERNAL, Q_JOURNAL, Q_UNKNOWN   # noqa: E402
from sysdb import CMDR_READY, CURRENT, LOSS_REPLAY, PLAN        # noqa: E402
from sources import SourceManager                              # noqa: E402
from netgate import Gateway                                    # noqa: E402
import netgate                                                 # noqa: E402
import shells                                                  # noqa: E402
from deepspace import (FuelState, best_staging, is_scoopable,   # noqa: E402
                       scoop_line, scoop_plan, staging_lines, tritium_systems)
from sysroute import (ALL_FILTERS, DEFAULT_MODEL, FILTER_LABEL,  # noqa: E402
                      F_ALL, F_OUTSTANDING, bodies_from_rows,
                      calibrate_from_journal, calibrate_work_from_journal,
                      leg_distance_ls, pace_ratio, spread_points,
                      plan_route, resolve_positions, shorten, start_at_body)
from boxelplan import bundled_probe_prefix                   # noqa: E402
from boxelplan import (K_BIO, K_CHECK, K_DSS, K_EMPTY, K_GAP,  # noqa: E402
                       K_NEW, K_PROBE, K_SCAN, LABEL, Planner, Target,
                       corridor_targets, set_origin)
from overlay import CockpitOverlay, POSITIONS as OVERLAY_POSITIONS  # noqa: E402
from biopredict import BioModel, COLONY_RANGE_M, surface_distance_m  # noqa: E402
import surfacenav  # noqa: E402
import miningstat  # noqa: E402

VERSION = "4.8.0"
PLUGIN_NAME = os.path.basename(_PLUGIN_DIR)
logger = logging.getLogger("%s.%s" % (appname, PLUGIN_NAME))

# sysdb and sources log through logging.getLogger(__name__), which sits
# outside EDMC's logger tree - their messages (database repair, EDD status,
# source warnings) never reached the EDMC log. Route them through ours.
import sysdb as _sysdb_mod      # noqa: E402
import sources as _sources_mod  # noqa: E402
_sysdb_mod.logger = logger
_sources_mod.logger = logger

DB_FILE = os.path.join(_PLUGIN_DIR, "shboxsearch.sqlite")

# ------------------------------------------------------------------- settings
CFG = {
    "radius": "%s_radius" % PLUGIN_NAME,
    "masscodes": "%s_masscodes" % PLUGIN_NAME,
    "probe_depth": "%s_probe_depth" % PLUGIN_NAME,
    "include_empty": "%s_include_empty" % PLUGIN_NAME,
    "include_tasks": "%s_include_tasks" % PLUGIN_NAME,
    "autocopy": "%s_autocopy" % PLUGIN_NAME,
    "src_edd": "%s_src_edd" % PLUGIN_NAME,
    "src_spansh": "%s_src_spansh" % PLUGIN_NAME,
    "src_edsm": "%s_src_edsm" % PLUGIN_NAME,
    "offline": "%s_offline" % PLUGIN_NAME,
    "edd_path": "%s_edd_path" % PLUGIN_NAME,
    "jump_range": "%s_jump_range" % PLUGIN_NAME,
    "harvest_navroute": "%s_harvest_navroute" % PLUGIN_NAME,
    "harvest_destination": "%s_harvest_dest" % PLUGIN_NAME,
    "debug": "%s_debug" % PLUGIN_NAME,
    "carrier_start": "%s_carrier_start" % PLUGIN_NAME,
    "show_stats": "%s_show_stats" % PLUGIN_NAME,
    "show_route": "%s_show_route" % PLUGIN_NAME,
    "route_all": "%s_route_all" % PLUGIN_NAME,
    "route_arrival": "%s_route_arrival" % PLUGIN_NAME,
    "route_top": "%s_route_top" % PLUGIN_NAME,
    "route_map": "%s_route_map" % PLUGIN_NAME,
    "filters": "%s_filters" % PLUGIN_NAME,
    "map_size": "%s_map_size" % PLUGIN_NAME,
    "panel_fuel": "%s_panel_fuel" % PLUGIN_NAME,
    "panel_queue": "%s_panel_queue" % PLUGIN_NAME,
    "mine_mat": "%s_mine_mat" % PLUGIN_NAME,
    "atlas_mode": "%s_atlas_mode" % PLUGIN_NAME,
    "atlas_sig": "%s_atlas_sig" % PLUGIN_NAME,
    "atlas_mat": "%s_atlas_mat" % PLUGIN_NAME,
    "atlas_find": "%s_atlas_find" % PLUGIN_NAME,
    "atlas_range": "%s_atlas_range" % PLUGIN_NAME,
    "check_updates": "%s_check_updates" % PLUGIN_NAME,
    "update_seen": "%s_update_seen" % PLUGIN_NAME,
    "update_checked": "%s_update_checked" % PLUGIN_NAME,
    "overlay": "%s_overlay" % PLUGIN_NAME,
    "overlay_pos": "%s_overlay_pos" % PLUGIN_NAME,
    "overlay_brief": "%s_overlay_brief" % PLUGIN_NAME,
    "overlay_nav": "%s_overlay_nav" % PLUGIN_NAME,
    "overlay_mining": "%s_overlay_mining" % PLUGIN_NAME,
    "fis_autostart": "%s_fis_autostart" % PLUGIN_NAME,
    "main_cmdr": "%s_main_cmdr" % PLUGIN_NAME,      # C1: FID, "" = suggestion
}

# Where releases live. A check is a single call to the GitHub releases API.
REPO_URL = "https://github.com/Shodanki/EDMC_BOXSEARCH"
RELEASES_API = "https://api.github.com/repos/Shodanki/EDMC_BOXSEARCH/releases/latest"
RELEASES_URL = REPO_URL + "/releases/latest"
RADIUS_CHOICES = ["50", "100", "150"]

# Events that tell us which body the ship is at. ApproachBody alone is far too
# rare - in a typical session it fires 11 times against 180 for the others.
POSITION_EVENTS = frozenset((
    "ApproachBody", "Touchdown", "Liftoff", "SupercruiseExit",
    "SAAScanComplete", "ScanOrganic", "SAASignalsFound",
))

KIND_SHORT = {K_SCAN: "FSS", K_DSS: "DSS", K_BIO: "BIO", K_NEW: "NEW",
              K_GAP: "GAP", K_PROBE: "PROBE", K_EMPTY: "EMPTY",
              K_CHECK: "CHECK"}


# ============================================================================
# State
# ============================================================================

class State:
    def __init__(self):
        self.db: Optional[SystemDB] = None
        self.lock = threading.RLock()
        # the plugin's one door to the internet - created once, so pacing
        # and rests survive a rebuilt SourceManager
        self.net = Gateway(VERSION)
        self.sources = SourceManager(gateway=self.net)
        # local-first (shells.py): how far out the online sources have been
        # asked for the running survey; the planner plans only inside it
        self.horizon = 0.0
        self.fetch_lock = threading.Lock()
        self.extending = False
        # EDDiscovery's file was busy (EDD running) - read it again later
        self.edd_pending = False
        self.edd_next_try = 0.0
        self.planner: Optional[Planner] = None

        self.active = False
        self.center: Optional[Tuple[float, float, float]] = None
        self.start_system: Optional[str] = None
        self.radius: float = 50.0

        self.flight: List[Target] = []
        self.probe: List[Target] = []
        self.plan_counts: Dict[str, int] = {}
        self.plan_info: str = ""

        self.cur_system: Optional[str] = None
        self.cmdr: Optional[str] = None          # commander of the last journal event
        self.awaiting_position = False           # commander switched: no system until Location
        self.cur_id64: Optional[int] = None
        self.cur_pos: Optional[Tuple[float, float, float]] = None
        self.max_jump: Optional[float] = None
        self.route_targets: List[Dict[str, Any]] = []   # NavRoute plot suggestions
        self.last_track: Optional[Dict[str, Any]] = None  # last stored surface point
        # species being sampled: {"body", "species", "genus", "points": [(lat, lon)]}
        self.bio_active: Optional[Dict[str, Any]] = None
        self._bio_shown = 0.0
        self._nav_shown = 0.0
        self.mine = miningstat.MiningTracker()          # overlay mining block
        self._mine_shown = 0.0
        self._mine_drawn = False
        self._nav_cache: Optional[Tuple[Any, ...]] = None   # (key, marks, sig_bio, genera, lost)
        self._route_checked: Optional[Tuple[str, ...]] = None  # I1: the route checked last
        self.last_dest_id64: Optional[int] = None

        self.sphere_id: Optional[int] = None
        self.stats: Dict[str, Any] = {}
        self.stats_lines: List[str] = []
        self.carrier: Optional[Dict[str, Any]] = None
        self.route = None
        self.route_lines: List[str] = []
        self.route_done: set = set()
        self.route_full = False
        self.route_from: Optional[str] = None    # R3: body of the carrier the route starts at
        # F1: the plotted route (NavRoute) - (system, star class, StarPos) per hop
        self.navroute: List[Tuple[str, Optional[str], Optional[Tuple[float, float, float]]]] = []
        self.route_start_pos: Optional[Tuple[float, float, float]] = None
        self.route_feedback = ""
        self.route_started: Optional[float] = None
        self.route_legs: List[Tuple[float, float]] = []   # R1: (planned s, actual s) per leg
        self.cost_model = DEFAULT_MODEL
        self.sc_segments: List[Tuple[float, float]] = []
        self.work_dss: List[float] = []
        self.work_bio: List[float] = []
        self.work_approach: List[float] = []
        self._arrive: Dict[str, float] = {}
        self._bio_log: Dict[Tuple, float] = {}
        self.sys_times: List[Tuple[str, float, int]] = []
        self.fuel = FuelState()
        self.staging: List[Dict[str, Any]] = []
        self.update_version: Optional[str] = None
        self.update_notes: str = ""
        self.last_body_id: Optional[int] = None
        self.last_body_name: str = ""
        self.last_body_sys: Optional[int] = None
        self.sys_minutes: List[float] = []
        self._sys_enter: Optional[float] = None
        self._sc_start: Optional[Tuple[float, float]] = None
        self.finished_announced = False

        self.busy = False
        self.status = "ready"


ST = State()

# UI references
_frame: Optional[tk.Frame] = None
_v_status: Optional[tk.StringVar] = None
_v_target: Optional[tk.StringVar] = None
_v_kind: Optional[tk.StringVar] = None
_v_sys: Optional[tk.StringVar] = None
_v_queue: Optional[tk.StringVar] = None
_v_probe: Optional[tk.StringVar] = None
_btn_start: Optional[tk.Button] = None
_btn_fc: Optional[tk.Button] = None
_btn_stats: Optional[tk.Button] = None
_btn_boxel: Optional[tk.Button] = None
_btn_prefix: Optional[tk.Button] = None
_btn_bundle: Optional[tk.Button] = None
_btn_next: Optional[tk.Button] = None
_lbl_stats = None
_v_stats: Optional[tk.StringVar] = None
_v_route: Optional[tk.StringVar] = None
_v_fuel: Optional[tk.StringVar] = None
_v_update: Optional[tk.StringVar] = None
_lbl_update = None
_lbl_fuel = None
_lbl_queue = None
_lbl_route = None
_btn_route: Optional[tk.Button] = None
_carrier_var: Optional[tk.IntVar] = None
_btn_absent: Optional[tk.Button] = None
_btn_skip: Optional[tk.Button] = None
_radius_var: Optional[tk.StringVar] = None


# ============================================================================
# Config helpers (robust across EDMC versions)
# ============================================================================

def cfg_bool(key: str, default: bool) -> bool:
    # The default has to go to EDMC itself: since EDMC 6 (config.toml) a key
    # that was never saved reads as False, not None, so a "True" default
    # applied afterwards never took effect. Up to 4.2.0 that silently
    # switched off the update check and the overlay for everyone who had not
    # opened and saved the preferences since those options existed.
    try:
        v = config.get_bool(key, default=default)
        return default if v is None else bool(v)
    except TypeError:
        pass                                   # very old EDMC: no default=
    except Exception:
        pass
    try:
        v = config.get(key)
    except Exception:
        v = None
    return default if v is None else str(v) not in ("0", "False", "false", "")


def cfg_int(key: str, default: int) -> int:
    try:
        v = config.get_int(key)
        return default if v in (None, 0) and default else (default if v is None else int(v))
    except Exception:
        try:
            return int(config.get(key))
        except Exception:
            return default


def cfg_str(key: str, default: str = "") -> str:
    try:
        v = config.get_str(key, default=default)
    except Exception:
        try:
            v = config.get(key)
        except Exception:
            v = None
    return default if v in (None, "") else str(v)


def cfg_set(key: str, value) -> None:
    try:
        config.set(key, value)
    except Exception as e:
        logger.warning("config.set(%s) fehlgeschlagen: %s", key, e)


def get_filters() -> List[str]:
    """Which bodies count as needing a visit. Empty means 'still outstanding'."""
    raw = cfg_str(CFG["filters"], F_OUTSTANDING)
    out = [f.strip() for f in raw.split(",") if f.strip() in ALL_FILTERS]
    return out or [F_OUTSTANDING]


def get_masscodes() -> List[int]:
    raw = cfg_str(CFG["masscodes"], "0,1,2,3")
    out = []
    for p in raw.split(","):
        p = p.strip()
        if p.isdigit() and 0 <= int(p) <= 7:
            out.append(int(p))
    return out or [0, 1, 2, 3]


# ============================================================================
# EDMC lifecycle
# ============================================================================

def plugin_start3(plugin_dir: str) -> str:
    global _MAP_W, _MAP_H
    logger.info("SHBOXSEARCH v%s starting", VERSION)
    _MAP_W = _MAP_H = _MAP_SIZES.get(cfg_str(CFG["map_size"], "medium"), 480)
    try:
        ST.db = SystemDB(DB_FILE)
        ST.planner = Planner(ST.db)
    except Exception:
        logger.exception("could not open database")
        return "SHBOXSEARCH"

    ST.sources = SourceManager(cfg_str(CFG["edd_path"]) or None, gateway=ST.net)
    ST.net.offline = cfg_bool(CFG["offline"], False)
    try:
        day0 = time.time() // 86400 * 86400
        ST.net.seed_today({k: ST.db.external_calls_since(day0, k)
                           for k in ("edsm", "spansh")})
    except Exception:
        logger.exception("could not read today's external calls")
    ST.overlay = CockpitOverlay(logger)
    _overlay_apply_settings()

    if not ST.db.get_meta("migrated"):
        _run_async(_first_run_migration, label="first-run import")
    elif any(not ST.db.get_meta(t) for t in REPLAY_TAGS):
        _run_async(_upgrade_replay, label="upgrade")

    _apply_main_cmdr()
    ST.carrier = ST.db.get_carrier()
    if ST.carrier:
        logger.info("fleet carrier remembered at %s", ST.carrier["system"])

    row = ST.db.load_survey()
    if row and row["active"] and row["cx"] is not None:
        ST.active = True
        ST.center = (row["cx"], row["cy"], row["cz"])
        ST.start_system = row["start_system"]
        ST.radius = row["radius"] or 50.0
        logger.info("restored running survey: %s r=%.0f ly",
                    ST.start_system, ST.radius)
        _run_async(_resume_worker, label="loading plan")
    # These read the journals to establish fuel, the work-time model and where
    # we last were. Without them the panel shows "fuel: unknown" and the map
    # has no "last here" marker until the first jump of the session.
    _run_async(_bootstrap_session, label="reading journals")
    _request_route(delay=2.5)
    return "SHBOXSEARCH"


# Frontier's /fleetcarrier answer, kept for SHBOX FIS (cargo per good - the
# tritium in the hold -, finances, itinerary). Local file next to the database.
CAPI_FC_FILE = os.path.join(_PLUGIN_DIR, "capi_fleetcarrier.json")


def capi_fleetcarrier(data: Any) -> Optional[str]:
    """EDMC hands over the Companion API's carrier data (after CarrierStats,
    at most every 15 minutes). Saved as it is, atomically; nothing else."""
    try:
        raw = getattr(data, "data", data)
        payload = {"saved": time.time(), "source_host": getattr(data, "source_host", None),
                   "data": dict(raw) if raw is not None else None}
        tmp = CAPI_FC_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, default=str)
        os.replace(tmp, CAPI_FC_FILE)
        logger.info("capi_fleetcarrier | saved for FIS")
    except Exception:  # noqa: BLE001 - never break EDMC over this
        logger.exception("capi_fleetcarrier | could not save")
    return None


def plugin_stop() -> None:
    ov = getattr(ST, "overlay", None)
    if ov is not None:
        ov.clear()
    _route_window_close()
    _stats_window_close()
    _probe_window_close()
    _mining_window_close()
    ST.net.stop()             # wake a waiting request; nothing more is sent
    _flush_net_log()
    with ST.lock:
        if ST.db:
            ST.db.close()
    logger.info("SHBOXSEARCH stopped")


# ============================================================================
# Background work
# ============================================================================

def _run_async(fn, *args, label: str = "working", **kw) -> None:
    def wrapper():
        ST.busy = True
        _set_status(label + " ...")
        try:
            fn(*args, **kw)
        except Exception:
            logger.exception("background task '%s' failed", label)
            _set_status("error - see log")
        finally:
            ST.busy = False
            _ui(_refresh)
    threading.Thread(target=wrapper, daemon=True, name="SHBOX-" + label).start()


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
                                      progress=lambda m: _set_status(m), r_min=r_min)
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
            _set_status("online data to %.0f of %.0f ly | %d new systems"
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
        _run_async(_edd_retry, label="EDDiscovery")
    if ST.extending:
        return
    left = len(ST.flight) + len(ST.probe)
    if shells.needs_next(ST.horizon, ST.radius, ST.center, ST.cur_pos, left):
        ST.extending = True
        _run_async(_extend_worker, label="next shell")


def _extend_worker() -> None:
    try:
        moved = _advance_horizon(True)
    finally:
        ST.extending = False
    if moved:
        _rebuild_plan()


def _resume_worker() -> None:
    """EDMC start with a running survey: no request on the way in - only
    shells still valid count; the plan asks for more when it needs it."""
    ST.horizon = 0.0
    _advance_horizon(allow_fetch=False)
    _rebuild_plan()


def _reload_online() -> None:
    """Reload button: ask the sources again for every shell up to the
    current horizon, paced like always."""
    if not (ST.active and ST.center):
        _set_status("no active survey")
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
        _ui(_probe_window_refresh)
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
        ST.db.set_meta(CORRIDOR_META, json.dumps(doc))


def _copy_route_target() -> None:
    if ST.route_targets:
        t = ST.route_targets[0]
        _copy(t["name"])
        _set_status("plot an ECONOMICAL route to %s - %d unprobed boxels on "
                    "the way, every hop lands in the database" % (t["name"], t["boxels"]))
    else:
        _set_status("no route target yet - start a survey first")


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
        _ui(_stats_window_refresh)
        _maybe_extend()
        return
    with ST.lock:
        plan = ST.planner.build(
            ST.center, _plan_radius(),
            masscodes=get_masscodes(),
            probe_depth=max(0, cfg_int(CFG["probe_depth"], 2)),
            include_empty=cfg_bool(CFG["include_empty"], True),
            include_tasks=cfg_bool(CFG["include_tasks"], True),
            origin=ST.cur_pos)
        ST.stats = ST.planner.statistics(plan)
    ST.flight = plan["flight"]
    ST.probe = plan["probe"]
    ST.plan_counts = plan["counts"]
    ST.plan_info = Planner.summary(plan)
    ST.stats_lines = Planner.stats_lines(ST.stats)
    _ui(_stats_window_refresh)
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
        _set_status("AREA COMPLETE - move on, next sphere >= %.0f ly away"
                    % (ST.radius * 2.0))
    logger.info("plan rebuilt: %d flight targets, %d probes | %s",
                len(ST.flight), len(ST.probe), ST.plan_counts)
    _update_route_targets()
    _maybe_extend()


def _current_system_from_journal() -> Optional[Tuple[str, int, Tuple[float, float, float]]]:
    """
    Read the current system straight out of the newest journal file.

    EDMC synthesises StartUp when the game is already running, so a session
    that begins parked in a system never sees FSDJump or Location and the
    plugin would otherwise have no idea where it is. Scanning the newest
    journal backwards for the last location event answers it exactly - name,
    id64 and coordinates, no guessing.
    """
    import glob
    d = _journal_dir()
    if not d:
        return None
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))
    for fn in reversed(files[-3:]):
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line or '"StarSystem"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") not in ("FSDJump", "Location", "CarrierJump"):
                continue
            pos = e.get("StarPos") or []
            if e.get("StarSystem") and e.get("SystemAddress") and len(pos) >= 3:
                return (e["StarSystem"], e["SystemAddress"],
                        (pos[0], pos[1], pos[2]))
    return None


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
    _ui(_route_window_refresh)
    _ui(_refresh)


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
            _rebuild_route()
        except Exception:
            logger.exception("route rebuild failed")

    threading.Thread(target=waiter, daemon=True, name="SHBOX-route").start()


# ---------------------------------------------------------------------------
# Cockpit overlay (EDMCModernOverlay) - display only, never required
# ---------------------------------------------------------------------------

_EXTERNAL_DBS = ("EDDiscovery", "Spansh", "EDSM")


def _overlay_apply_settings() -> None:
    ov = getattr(ST, "overlay", None)
    if ov is None:
        return
    ov.enabled = cfg_bool(CFG["overlay"], True)
    pos = cfg_str(CFG["overlay_pos"], "top-left")
    ov.position = pos if pos in OVERLAY_POSITIONS else "top-left"
    if not ov.enabled:
        ov.clear()


OVERLAY_KEEP_MS = 60_000      # look once a minute whether the targets block needs sending


def _overlay_keepalive() -> None:
    """Once a minute: keep the targets block on screen (it has a time to
    live and nothing else redraws it between route changes)."""
    try:
        ov = getattr(ST, "overlay", None)
        if ov is not None and ov.enabled:
            ov.keep_targets()
    except Exception:
        logger.debug("overlay keep-alive failed", exc_info=True)
    finally:
        if _frame is not None:
            try:
                _frame.after(OVERLAY_KEEP_MS, _overlay_keepalive)
            except Exception:
                pass                         # EDMC is closing


def _overlay_targets() -> None:
    ov = getattr(ST, "overlay", None)
    if ov is None or not ov.enabled:
        return
    try:
        ov.show_targets(ST.route, ST.route_done)
    except Exception:
        logger.debug("overlay targets failed", exc_info=True)


def _briefing_info(kind: str, name: Optional[str], id64: Optional[int],
                   star_class: Optional[str]) -> Dict[str, Any]:
    """What the briefing knows about a system, from our own database only."""
    info: Dict[str, Any] = {"kind": kind, "name": name, "star_class": star_class}
    if star_class:
        info["scoopable"] = is_scoopable(star_class)
    row = None
    with ST.lock:
        if id64:
            row = ST.db.system_by_id64(id64)
        if row is None and name:
            row = ST.db.system(name)
        if kind == "arrival" and id64:
            p = ST.db.system_progress(id64, CURRENT)
            if p.get("body_count"):
                info["bodies"] = p["body_count"]
            info["bodies_new"] = p.get("new_discoveries") or 0
    if not star_class and row is not None and row["star_class"]:
        # FSDJump carries no star class; StartJump/FSDTarget stored it earlier
        info["star_class"] = row["star_class"]
        info["scoopable"] = is_scoopable(row["star_class"])
    srcs = set((row["sources"] or "").split(",")) if row is not None else set()
    info["known_sources"] = [s for s in _EXTERNAL_DBS if s in srcs]
    # I1: say "in no database" only where a source was really asked
    pos = None
    if row is not None and row["x"] is not None and (row["quality"] or 0) > Q_ESTIMATE:
        pos = (row["x"], row["y"], row["z"])
    try:
        with ST.lock:
            regions = {k: ST.db.valid_shells(k) for k in ("edd", "spansh", "edsm")}
    except Exception:
        regions = {}
    info["level"], info["checked_by"] = shells.info_level(srcs, pos, regions)
    if row is not None and kind == "target":
        with ST.lock:
            if ST.db.is_visited(row, CURRENT):
                info["visited"] = True
            also = ST.db.explorers(row["id64"], but=ST.db.fid) if ST.db.fid else []
            lost = [d for d in ST.db.lost_summary(ST.db.view_fid(CURRENT))
                    if d["id64"] == row["id64"]]
        if also:
            info["also_by"] = also          # C1: another commander was here
        if lost:
            info["lost"] = lost[0]          # data lost there in a crash, to redo
    pn = parse_name(name or "")
    if pn and ST.probe:
        info["boxel_open"] = sum(1 for q in ST.probe if q.boxel_key == pn.boxel_key)
    try:
        sl = scoop_line(_scoop_plan())
        if sl:
            info["scoop"] = sl          # F1: where to scoop at the latest
    except Exception:
        logger.debug("scoop plan failed", exc_info=True)
    w = ST.fuel.warning() if ST.fuel else None
    if w and kind == "target" and info.get("scoopable") and "CRITICAL" not in w:
        w = None                  # a scoopable target: refuel where you arrive
    if w:
        info["fuel_warning"] = w
    elif ST.fuel and ST.fuel.jumps_left is not None:
        info["jumps_left"] = ST.fuel.jumps_left
    return info


CORRIDOR_META = "route_corridor"   # H3 #2: plot suggestion for the FIS (JSON)
ROUTE_CHECK_MAX = 40          # I1: names in the one EDSM request of a route check
ROUTE_CHECK_R = 0.1           # ly: the region a route check leaves - one system
ROUTE_CHECK_TTL_S = 14 * 86400
ROUTE_CHECK_EDD_R = 0.1       # ly: EDD positions are exact to 1/32 ly


def _route_check(hops: List[Tuple[str, Any, Any]]) -> None:
    """
    I1 (fair use): a plotted route of two jumps or more through space we have
    no data for ("not checked") is checked ONCE - first in EDDiscovery's file
    (local), then the rest with ONE bundled EDSM request through the plugin's
    gateway (pacing, daily cap, offline switch, EDSM switch). Found systems
    get their source (known); every system asked is remembered as a tiny
    checked region for 14 days, so the briefing can say "in no database
    (checked: EDSM)" and the same route plotted again asks nothing.
    Runs in the background.
    """
    with ST.lock:
        regions = {k: ST.db.valid_shells(k) for k in ("edd", "spansh", "edsm")}
        todo: List[Tuple[str, Tuple[float, float, float]]] = []
        for name, _cls, pos in hops[1:]:
            if not name or pos is None:
                continue
            row = ST.db.system(name)
            srcs = set((row["sources"] or "").split(",")) if row is not None else set()
            if shells.info_level(srcs, pos, regions)[0] == "unchecked":
                todo.append((name, tuple(pos)))
    todo = todo[:ROUTE_CHECK_MAX]
    if not todo:
        return
    ttl = shells.ttl_seconds()
    known: List[Dict] = []
    rest = list(todo)
    edd = ST.sources.sources.get("edd") if ST.sources else None
    if edd is not None and cfg_bool(CFG["src_edd"], True) and edd.available()[0]:
        left = []
        for name, pos in rest:
            try:
                rows = edd.fetch(pos, ROUTE_CHECK_EDD_R)
            except Exception:
                rows = None
            if rows is None:
                left.append((name, pos))
                continue
            with ST.lock:
                ST.db.record_shell("edd", pos, 0.0, ROUTE_CHECK_R, len(rows), ttl)
            if rows:
                known.append({"name": name, "x": pos[0], "y": pos[1], "z": pos[2],
                              "source": edd.name})
            else:
                left.append((name, pos))
        rest = left
    asked_edsm = 0
    edsm = ST.sources.sources.get("edsm") if ST.sources else None
    if rest and edsm is not None and cfg_bool(CFG["src_edsm"], True):
        res = edsm.lookup([n for n, _p in rest])
        _log_net(_flush_net_log())
        if res is not None:
            asked_edsm = len(rest)
            for name, pos in rest:
                hit = res.get(name.lower())
                with ST.lock:
                    ST.db.record_shell("edsm", pos, 0.0, ROUTE_CHECK_R, 1 if hit else 0, ttl)
                if hit:
                    known.append(dict(hit, name=name, x=hit.get("x", pos[0]),
                                      y=hit.get("y", pos[1]), z=hit.get("z", pos[2])))
    if known:
        _store_rows(known)
    logger.info("route check | %d systems not checked before: %d known, %d asked EDSM in one "
                "request, %d in no database", len(todo), len(known), asked_edsm,
                len(todo) - len(known) if asked_edsm or len(rest) == 0 else 0)


def _maybe_route_check(hops: List[Tuple[str, Any, Any]]) -> None:
    """A plotted route of two jumps or more (I1); the same route only once."""
    if len(hops) < 3:
        return
    sig = tuple(h[0] for h in hops)
    if sig == ST._route_checked:
        return
    ST._route_checked = sig
    _run_async(_route_check, hops, label="route check")


def _note_navroute(route: Any) -> None:
    """F1: keep the plotted route (EDMC hands NavRoute with its Route)."""
    hops = []
    for h in route or []:
        pos = h.get("StarPos")
        hops.append((h.get("StarSystem") or "", h.get("StarClass"),
                     tuple(pos[:3]) if pos and len(pos) >= 3 else None))
    ST.navroute = hops
    if len(hops) > 2:
        sl = scoop_line(_scoop_plan())
        if sl:
            logger.info("fuel | route of %d jumps: %s", len(hops) - 1, sl[0])


def _scoop_plan() -> Optional[Dict[str, Any]]:
    """F1: the rest of the plotted route from where we are, with the fuel
    curve of this ship - None for a single jump or without a fuel model."""
    route = ST.navroute
    if len(route) < 3 or not ST.fuel:
        return None
    start = 0
    for i, h in enumerate(route):
        if h[0] == ST.cur_system:
            start = i + 1
    rest = route[start:]
    if len(rest) < 2:
        return None
    prev = ST.cur_pos or (route[start - 1][2] if start else None)
    hops = []
    for nm, cls, pos in rest:
        d = math.dist(prev, pos) if prev and pos else 0.0
        hops.append((nm, cls, d))
        prev = pos
    here = (ST.cur_system or "", route[start - 1][1] if start else None)
    return scoop_plan(ST.fuel, hops, here=here)


def _overlay_briefing(kind: str, name: Optional[str], id64: Optional[int],
                      star_class: Optional[str]) -> None:
    ov = getattr(ST, "overlay", None)
    if ov is None or not ov.enabled or not cfg_bool(CFG["overlay_brief"], True):
        return
    try:
        info = _briefing_info(kind, name, id64, star_class)
        # 30 s: long enough to read while aligning for the jump (user, 05.11.)
        ov.show_briefing(info, seconds=30)
        if kind == "target":
            lv = info.get("level")
            if lv == "checked":
                logger.info("briefing | %s is in no database (checked: %s) - first "
                            "discovery likely", name, ", ".join(info.get("checked_by") or []))
            elif lv == "unchecked":
                logger.info("briefing | %s not checked - outside our data frame", name)
            elif lv == "inhabited":
                logger.info("briefing | %s is inhabited - known", name)
    except Exception:
        logger.debug("overlay briefing failed", exc_info=True)


_bio_model: Optional[BioModel] = None    # relearned after each new analysis


def _bio_model_reset() -> None:
    global _bio_model
    _bio_model = None


def _get_bio_model() -> BioModel:
    global _bio_model
    if _bio_model is None:
        with ST.lock:
            rows = ST.db.bio_training_rows()
        _bio_model = BioModel.learn(rows)
        logger.info("bio | %s", _bio_model.summary())
    return _bio_model


_replayed_for: set = set()     # system id64s already replayed this session


def _rebuild_route() -> None:
    """Order the bodies of the current system into a short in-system route."""
    ST.route = None
    ST.route_lines = []
    _resolve_current_system()
    if not (ST.db and ST.cur_id64):
        logger.info("route | no current system known yet")
        return
    with ST.lock:
        # C1: what THIS commander still has to do here (knowledge is shared)
        rows = ST.db.bodies_for(ST.cur_id64, ST.db.view_fid(CURRENT))
    if not rows and ST.cur_id64 not in _replayed_for:
        # Nothing stored for this system - the scans may predate the plugin or
        # have happened while it was not running. Replay the recent journals
        # once per system and session: arriving in a fresh, unscanned system
        # used to trigger a full replay on every route rebuild, which could
        # never find anything the live journal feed had not already seen.
        _replayed_for.add(ST.cur_id64)
        logger.info("route | no bodies stored for %s, replaying recent journals",
                    ST.cur_system)
        d = _journal_dir()
        if d:
            res = ST.db.import_journals(d, max_files=6, lock=ST.lock)
            logger.info("route | replayed %s", res)
            with ST.lock:
                rows = ST.db.bodies_for(ST.cur_id64, ST.db.view_fid(CURRENT))
    if not rows:
        logger.info("route | %s has no scanned bodies yet - run a system scan",
                    ST.cur_system)
        _ui(_route_window_refresh)
        return
    bodies = bodies_from_rows(rows, now=time.time())
    for b in bodies.values():
        b.short = shorten(b.name, ST.cur_system or "")
    try:
        model = _get_bio_model()
        by_id = {r["body_id"]: r for r in rows}
        for b in bodies.values():
            r = by_id.get(b.body_id)
            b.bio_hint = model.hint(r) if r is not None else ""
    except Exception:
        logger.debug("bio hints failed", exc_info=True)
    filters = [F_ALL] if cfg_bool(CFG["route_all"], False) else get_filters()
    # R2: start the run at the arrival star (default) or with the first body
    skip_arrival = not cfg_bool(CFG["route_arrival"], True)
    # R3: riding along on a carrier into a system you have not explored, you
    # start at the carrier - this visit's route begins at its body, without
    # the arrival star. Later visits start at the main star again.
    start = (0.0, 0.0, 0.0)
    ST.route_from = None
    ST.route_start_pos = None
    with ST.lock:
        r3 = ST.db.route_start(ST.db.view_fid(CURRENT), ST.cur_id64)
    if r3:
        at = start_at_body(bodies, r3[0])
        if at:
            start, skip_arrival = at, True
            ST.route_start_pos = at
            ST.route_from = shorten(r3[1], ST.cur_system or "") if r3[1] else "#%d" % r3[0]
            logger.info("route | starting at the carrier (%s), not at the main star",
                        r3[1] or r3[0])
    route = plan_route(ST.cur_system or "", bodies, model=ST.cost_model,
                       filters=filters, skip_arrival=skip_arrival, start=start)
    ST.route_full = False
    if not route.stops and F_ALL not in filters:
        # Nothing outstanding - show the complete tour anyway rather than an
        # empty window. Useful when revisiting a system, and it makes clear
        # that the system really is finished rather than unknown.
        route = plan_route(ST.cur_system or "", bodies, model=ST.cost_model,
                           filters=[F_ALL], skip_arrival=skip_arrival, start=start)
        ST.route_full = True
    lost_of = {r["body_id"]: r["lost_what"] for r in rows
               if "lost_what" in r.keys() and r["lost_what"]}
    for s in route.stops:
        if s.body.bio_hint and s.body.wants_bio:
            s.work = (s.work + " | " if s.work else "") + s.body.bio_hint
        if s.body.body_id in lost_of:
            # lost with the ship and not redone yet - worth doing again
            s.work = "LOST: redo | " + (s.work or "")
    ST.route = route
    # Restore the ticks for this system, then drop any that no longer refer to
    # a stop on the current route.
    try:
        with ST.lock:
            ST.route_done = ST.db.route_done_of(ST.cur_id64)
    except Exception:
        logger.exception("could not load route ticks")
    ST.route_lines = route.lines(limit=12)
    valid = {st.body.body_id for st in route.stops}
    ST.route_done = {b for b in ST.route_done if b in valid}
    if not ST.route_done:
        ST.route_started = None
        ST.route_feedback = ""
    logger.info("route | %s", route.summary())
    for line in route.lines(limit=8):
        logger.info("route | %s", line)
    _ui(_route_window_refresh)


# ---------------------------------------------------------------------------
# In-system route window
# ---------------------------------------------------------------------------

_MONO_FAMILY = "Consolas" if sys.platform == "win32" else "TkFixedFont"
_MONO = (_MONO_FAMILY, 9)
_FONT_GROUP = (_MONO_FAMILY, 11, "bold")   # planetary system header
_FONT_BODY = (_MONO_FAMILY, 9)             # a planet
_FONT_MOON = (_MONO_FAMILY, 8)             # a moon, visually subordinate
_FONT_SMALL = (_MONO_FAMILY, 8)
# Markers that make the hierarchy readable at a glance
_MARK_PLANET = "\u25cf"    # filled circle - a planetary system heading
_MARK_BODY = "\u25cb"      # hollow circle - the planet itself
_MARK_MOON = "\u00b7"      # middle dot - a moon of that planet
_route_win: Optional[tk.Toplevel] = None
_route_rows: List[Dict[str, Any]] = []
_route_head: Optional[tk.StringVar] = None
_route_body: Optional[tk.Frame] = None
_route_map: Optional[tk.Canvas] = None
_route_scroll: Optional[tk.Canvas] = None
_route_scroll_win = None
_MAP_SIZES = {"small": 260, "medium": 340, "large": 460}
# How tall the scrolling stop list is allowed to get. Together with the map
# and the button rows this has to stay inside a 1080p screen.
_LIST_H = 360
_MAP_W, _MAP_H = 480, 480
_MAP_LAST = "#4ea3ff"      # where you were last - blue, distinct from the theme


def _theme_colours() -> Dict[str, str]:
    """
    Work out the host application's colours.

    EDMC's theme module registers widgets it created itself; a Toplevel a
    plugin opens is not part of that, and Tk gives new widgets its own
    defaults - black text on a light grey button, which is unreadable on the
    dark theme. So the colours are read live from the plugin frame, which does
    follow whatever theme is active.

    EDMC's own config is consulted first, because the frame can report an
    empty string before it has been mapped; the frame is the fallback, and a
    dark default the last resort.
    """
    bg = fg = ""

    # 1. EDMC's theme setting, if it exposes one
    try:
        idx = config.get_int("theme")
    except Exception:
        idx = None
    if idx is not None:
        try:
            bg = cfg_str("dark_background") if idx else ""
            fg = cfg_str("dark_text") if idx else ""
        except Exception:
            bg = fg = ""

    # 2. live values off the plugin frame
    if not bg and _frame is not None:
        for widget in (_frame, getattr(_frame, "master", None)):
            if widget is None:
                continue
            try:
                v = str(widget.cget("background"))
            except Exception:
                continue
            if v:
                bg = v
                break
    if not fg and _frame is not None:
        try:
            for child in _frame.winfo_children():
                try:
                    v = str(child.cget("foreground"))
                except Exception:
                    continue
                if v:
                    fg = v
                    break
        except Exception:
            pass

    # 3. a readable pair rather than Tk's defaults
    if not bg:
        bg = "#000000"
    if not fg or fg == bg:
        fg = "#ffffff" if _is_dark(bg) else "#000000"
    return {"bg": bg, "fg": fg}


def _is_dark(colour: str) -> bool:
    """Rough luminance test, so a fallback foreground is at least readable."""
    try:
        c = colour.strip()
        if c.startswith("#") and len(c) == 7:
            r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
            return (0.299 * r + 0.587 * g + 0.114 * b) < 128
    except Exception:
        pass
    return True


def _dim(colour: str, factor: float = 0.45) -> str:
    """A muted version of a colour, for disabled controls and finished stops."""
    try:
        c = colour.strip()
        if c.startswith("#") and len(c) == 7:
            r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
            return "#%02x%02x%02x" % (int(r * factor), int(g * factor),
                                      int(b * factor))
    except Exception:
        pass
    return "#7a7a7a"


def _apply_theme(widget, colours: Dict[str, str], is_text: bool = False,
                 is_button: bool = False) -> None:
    """
    Paint one widget in the host application's colours.

    Buttons need more than background and foreground. Tk keeps separate
    colours for the pressed and the disabled state, and on Windows a button
    left at its defaults draws black text on whatever background it was given
    - which is exactly the unreadable combination on a dark theme. All four
    are therefore set together.
    """
    bg, fg = colours.get("bg"), colours.get("fg")
    opts = {}
    if bg:
        opts["background"] = bg
    if (is_text or is_button) and fg:
        opts["foreground"] = fg
    if is_button:
        if bg:
            opts["activebackground"] = bg
            opts["highlightbackground"] = bg
        if fg:
            opts["activeforeground"] = fg
            opts["disabledforeground"] = _dim(fg)
        opts["relief"] = tk.FLAT
        opts["borderwidth"] = 1
        opts["highlightthickness"] = 1
    if not opts:
        return
    try:
        widget.configure(**opts)
        return
    except Exception:
        pass
    # some option combinations are rejected per widget class - set them singly
    for key, value in opts.items():
        try:
            widget.configure(**{key: value})
        except Exception:
            continue


def _theme_menu(widget, colours: Dict[str, str]) -> None:
    """
    Colour the dropdown of an OptionMenu.

    The popup is a separate Tk Menu hanging off the button, not a child in the
    widget tree, so walking the children never reaches it - which is how it
    ended up black text on a black background. It has to be fetched via the
    widget's "menu" option and configured on its own.
    """
    bg, fg = colours.get("bg"), colours.get("fg")
    if not (bg and fg):
        return
    try:
        name = widget.cget("menu")
    except Exception:
        return
    if not name:
        return
    try:
        menu = widget.nametowidget(name)
    except Exception:
        return
    for opts in ({"background": bg, "foreground": fg,
                  "activebackground": fg, "activeforeground": bg,
                  "selectcolor": fg, "borderwidth": 1},
                 {"background": bg, "foreground": fg}):
        try:
            menu.configure(**opts)
            return
        except Exception:
            continue


def _theme_tree(widget, colours: Dict[str, str]) -> None:
    """Apply the colours to a widget and everything below it."""
    cls = widget.__class__.__name__
    if cls in ("OptionMenu", "Menubutton"):
        _theme_menu(widget, colours)
    _apply_theme(widget, colours,
                 is_text=cls in ("Label", "Checkbutton", "Entry"),
                 is_button=cls in ("Button", "Menubutton", "Radiobutton"))
    if cls == "Radiobutton" and colours.get("bg"):
        # tab buttons: the chosen one keeps the background (its text says
        # which one it is) - Tk would paint it white otherwise
        try:
            widget.configure(selectcolor=colours["bg"], offrelief=tk.FLAT)
        except Exception:
            pass
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for child in children:
        _theme_tree(child, colours)


def _toggle_route_window() -> None:
    """Open or close the route window."""
    global _route_win
    if _route_win is not None:
        _route_window_close()
        return
    _route_window_open()


def _route_window_close() -> None:
    global _route_win, _route_body, _route_rows, _route_map, _route_scroll
    if _route_win is not None:
        try:
            _route_win.destroy()
        except Exception:
            pass
    _route_win = None
    _route_body = None
    _route_map = None
    _route_scroll = None
    _route_rows = []
    _refresh()


def _route_window_open() -> None:
    """
    A separate window listing the in-system route.

    Copy and paste is pointless in here: bodies are picked in the system map,
    not typed. So the window is a checklist - tick a stop off and the remaining
    time updates. Only the external jump target is ever copied, from the main
    panel.
    """
    global _route_win, _route_head, _route_body
    if _frame is None:
        return
    _route_win = tk.Toplevel(_frame)
    _route_win.title("SHBOXSEARCH - in-system route")
    _route_win.protocol("WM_DELETE_WINDOW", _route_window_close)
    try:
        _route_win.attributes("-topmost", cfg_bool(CFG["route_top"], True))
    except Exception:
        pass

    _route_head = tk.StringVar(value="")
    tk.Label(_route_win, textvariable=_route_head, anchor=tk.W,
             justify=tk.LEFT).grid(row=0, column=0, columnspan=2, sticky=tk.EW,
                                   padx=8, pady=(8, 4))

    global _route_map
    _route_map = tk.Canvas(_route_win, width=_MAP_W, height=_MAP_H,
                           highlightthickness=0)
    if cfg_bool(CFG["route_map"], True):
        _route_map.grid(row=1, column=0, sticky=tk.EW, padx=8, pady=(2, 4))

    # The stop list is put inside a scrolling canvas. A 29-body system needs
    # more vertical space than a 1080p screen has once the map is above it, so
    # without this the bottom of the route is simply unreachable.
    global _route_scroll, _route_scroll_win
    _route_scroll = tk.Canvas(_route_win, highlightthickness=0,
                              width=_MAP_W + 190, height=_LIST_H)
    _route_scroll.grid(row=2, column=0, sticky=tk.NSEW, padx=(8, 0))
    sb = tk.Scrollbar(_route_win, orient=tk.VERTICAL,
                      command=_route_scroll.yview)
    sb.grid(row=2, column=1, sticky=tk.NS)
    _route_scroll.configure(yscrollcommand=sb.set)

    _route_body = tk.Frame(_route_scroll)
    _route_scroll_win = _route_scroll.create_window(
        (0, 0), window=_route_body, anchor=tk.NW)

    def _on_body_resize(_event=None):
        try:
            _route_scroll.configure(scrollregion=_route_scroll.bbox("all"))
        except Exception:
            pass

    _route_body.bind("<Configure>", _on_body_resize)

    def _on_wheel(event):
        try:
            delta = -1 if getattr(event, "delta", 0) > 0 else 1
            _route_scroll.yview_scroll(delta, "units")
        except Exception:
            pass

    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        try:
            _route_win.bind_all(seq, _on_wheel)
        except Exception:
            pass

    _route_win.columnconfigure(0, weight=1)
    _route_win.rowconfigure(2, weight=1)

    bar = tk.Frame(_route_win)
    bar.grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=8, pady=(4, 8))
    tk.Button(bar, text="refresh",
              command=lambda: _run_async(_rebuild_route, label="route")).pack(
        side=tk.LEFT)
    tk.Button(bar, text="map", command=_route_map_toggle).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="reset ticks", command=_route_reset).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="map", command=_toggle_map).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="size", command=_cycle_map_size).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="review", command=_route_review).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="close", command=_route_window_close).pack(
        side=tk.LEFT, padx=(4, 0))

    _route_theme()
    _route_window_refresh()
    _fit_to_screen(_route_win)
    _refresh()


def _fit_to_screen(win, margin: int = 80) -> None:
    """
    Keep a window inside the monitor.

    A 29-body route plus the map is taller than 1080p, and Tk will happily
    place a window whose bottom is off-screen with no way to reach the
    buttons. Capping the height is the difference between usable and not.
    """
    if win is None:
        return
    try:
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        w = min(w, max(400, sw - margin))
        h = min(h, max(400, sh - margin))
        win.geometry("%dx%d" % (w, h))
        win.maxsize(sw - 20, sh - 40)
    except Exception:
        pass


def _route_theme() -> None:
    """Match the route window to the host application's theme."""
    if _route_win is None:
        return
    try:
        theme.register(_route_win)
    except Exception:
        pass
    try:
        theme.update(_route_win)
    except Exception:
        pass
    _theme_tree(_route_win, _theme_colours())


def _route_map_toggle() -> None:
    show = not cfg_bool(CFG["route_map"], True)
    cfg_set(CFG["route_map"], show)
    if _route_map is not None:
        try:
            if show:
                _route_map.grid(row=1, column=0, sticky=tk.EW, padx=8, pady=(2, 4))
                _route_map_draw()
            else:
                _route_map.grid_remove()
        except Exception:
            pass


def _route_map_draw() -> None:
    """
    Top-down map of the system with the route drawn on it.

    Plain tkinter Canvas - no extra dependency, and it redraws in a millisecond.
    The projection is the X/Z plane seen from galactic north, which is how the
    in-game system map is laid out, so the picture matches what you see there.

    Distances span four orders of magnitude in a single system (a moon 2 LS out,
    a gas giant 4000 LS out), so the radius is drawn on a log scale. Angles are
    exact; only the radial spacing is compressed.
    """
    if _route_map is None:
        return
    try:
        _route_map.delete("all")
    except Exception:
        return
    route = ST.route
    if route is None or not route.stops:
        return

    # Tk reports a width of 1 for a widget it has not laid out yet, and
    # `int(1) or _MAP_W` is 1, not _MAP_W - which silently produced a negative
    # span and a blank map. Anything implausibly small falls back to the
    # configured size, and the draw is retried once the window is mapped.
    w = h = 0
    try:
        w = int(_route_map.winfo_width())
        h = int(_route_map.winfo_height())
    except Exception:
        pass
    if w < 40 or h < 40:
        w, h = _MAP_W, _MAP_H
        if _route_win is not None:
            try:
                _route_win.after(150, _route_map_draw)
            except Exception:
                pass
    cx, cy = w / 2.0, h / 2.0
    span = min(cx, cy) - 14.0
    if span <= 10:
        return

    pts = [s.body.pos for s in route.stops if s.body.pos]
    if not pts:
        return

    # Pick the projection plane from the data instead of assuming one.
    #
    # Orbits in a system are close to coplanar, but that plane is not the same
    # one in every system: measured over real systems, five of six have z
    # within a few light seconds of zero while x and y span thousands, and one
    # binary is the other way round. Projecting on a fixed X/Z therefore
    # collapsed most systems onto a single horizontal line. Dropping whichever
    # axis varies least keeps the spread in every case.
    def _spread(idx: int) -> float:
        vals = [p[idx] for p in pts]
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))

    spreads = [(_spread(i), i) for i in range(3)]
    flattest = min(spreads)[1]
    ax, ay = [i for i in range(3) if i != flattest][:2]

    rmax = max(math.sqrt(p[ax] ** 2 + p[ay] ** 2) for p in pts) or 1.0

    def project(p) -> Tuple[float, float]:
        u, v = p[ax], p[ay]
        r = math.sqrt(u * u + v * v)
        if r < 1e-9:
            return (cx, cy)
        # log radial scale so moons and outer giants both stay visible
        rr = math.log10(1.0 + r) / math.log10(1.0 + rmax)
        return (cx + (u / r) * rr * span, cy + (v / r) * rr * span)

    col = _theme_colours()
    fg = col.get("fg") or "#ff8000"
    dim = col.get("bg") or "#101010"

    # E17: bodies that land on one spot (the planets of a far companion
    # star on the log scale) are pulled apart on screen - planets 14 px,
    # moons stay near theirs; drawn and labelled where they ended up
    raw = {st.body.body_id: project(st.body.pos) for st in route.stops if st.body.pos}
    screen = spread_points(raw, 14.0)

    def project_stop(st) -> Tuple[float, float]:
        return screen.get(st.body.body_id) or project(st.body.pos)

    # range rings
    for frac, lbl in ((1.0, "%.0f LS" % rmax), (0.5, "")):
        rr = math.log10(1.0 + rmax * frac) / math.log10(1.0 + rmax) * span
        _route_map.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                               outline=fg, width=1, dash=(2, 4))
        if lbl:
            _route_map.create_text(cx, cy - rr - 7, text=lbl, fill=fg,
                                   font=_FONT_SMALL)

    # the arrival star
    _route_map.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=fg, outline=fg)

    # where we were last, if known. The live position is not in any journal
    # event, so the last body approached is the closest thing to a "you are
    # here" - drawn in blue so it never blends into the route.
    # BodyID is only unique within a system, so the marker is drawn only when
    # the recorded body belongs to the system on screen. Without that check it
    # silently pointed at whatever body happened to share the number here.
    last_pos = None
    if (ST.last_body_id is not None
            and ST.last_body_sys is not None
            and ST.last_body_sys == ST.cur_id64):
        for st in route.stops:
            if st.body.body_id == ST.last_body_id and st.body.pos:
                last_pos = project_stop(st)
                break

    # route legs - from the arrival star, or (R3) from the carrier's body
    prev = (cx, cy)
    if ST.route_from and ST.route_start_pos:
        prev = project(ST.route_start_pos)
        _route_map.create_rectangle(prev[0] - 3, prev[1] - 3, prev[0] + 3, prev[1] + 3,
                                    outline=fg, width=1)
    for i, st in enumerate(route.stops):
        if not st.body.pos:
            continue
        p = project_stop(st)
        done = st.body.body_id in ST.route_done
        _route_map.create_line(prev[0], prev[1], p[0], p[1], fill=fg,
                               width=1, dash=(1, 3) if done else None,
                               arrow="last" if st.group_start and i else None)
        prev = p

    # bodies
    # Bodies, then labels. Labels are placed last and nudged apart, because a
    # tight inner system otherwise draws six names on top of each other and
    # none of them can be read.
    placed: List[Tuple[float, float]] = []

    def free_spot(x: float, y: float, r: float) -> Tuple[float, float, str]:
        """Find a nearby slot no other label has taken."""
        for dx, dy, anchor in ((r + 4, 0, tk.W), (-(r + 4), 0, tk.E),
                               (r + 4, -11, tk.W), (-(r + 4), -11, tk.E),
                               (r + 4, 11, tk.W), (-(r + 4), 11, tk.E),
                               (0, -(r + 10), tk.CENTER), (0, r + 10, tk.CENTER)):
            px, py = x + dx, y + dy
            if all(abs(px - qx) > 46 or abs(py - qy) > 10 for qx, qy in placed):
                placed.append((px, py))
                return px, py, anchor
        return x + r + 4, y, tk.W

    for st in route.stops:
        if not st.body.pos:
            continue
        x, y = project_stop(st)
        done = st.body.body_id in ST.route_done
        r = 2.0 if st.is_moon else 4.0
        if done:
            _route_map.create_oval(x - r, y - r, x + r, y + r, outline=fg)
        else:
            _route_map.create_oval(x - r, y - r, x + r, y + r, fill=fg,
                                   outline=fg)

    for st in route.stops:
        # Only planets get a name. Moons sit within a few light seconds of
        # their planet and would just pile more text into the same spot.
        if not st.body.pos or st.is_moon:
            continue
        x, y = project_stop(st)
        px, py, anchor = free_spot(x, y, 4.0)
        _route_map.create_text(px, py, text=st.body.short[:10], fill=fg,
                               anchor=anchor, font=_FONT_SMALL)

    if last_pos is not None:
        lx, ly = last_pos
        _route_map.create_oval(lx - 7, ly - 7, lx + 7, ly + 7,
                               outline=_MAP_LAST, width=2)
        _route_map.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                               fill=_MAP_LAST, outline=_MAP_LAST)
        _route_map.create_text(lx, ly + 12, text="last here", fill=_MAP_LAST,
                               font=_FONT_SMALL)


def _toggle_map() -> None:
    cfg_set(CFG["route_map"], not cfg_bool(CFG["route_map"], True))
    _route_window_close()
    _route_window_open()


def _cycle_map_size() -> None:
    """Step through the map sizes - dense systems need the room."""
    global _MAP_W, _MAP_H
    order = ["small", "medium", "large"]
    cur = cfg_str(CFG["map_size"], "medium")
    nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "medium"
    cfg_set(CFG["map_size"], nxt)
    _MAP_W = _MAP_H = _MAP_SIZES[nxt]
    _route_window_close()
    _route_window_open()
    _set_status("map size: %s" % nxt)


def _route_reset() -> None:
    n = 0
    if ST.db and ST.cur_id64:
        try:
            with ST.lock:
                n = ST.db.clear_route_done(ST.cur_id64)
        except Exception:
            logger.exception("could not clear route ticks")
    ST.route_done.clear()
    logger.info("route | ticks cleared for %s (%d)", ST.cur_system, n)
    _set_status("ticks cleared (%d)" % n)
    _route_window_refresh()
    _refresh()


def _note_position(entry: Dict[str, Any]) -> None:
    """
    Record which body we are at.

    Every event that names a body counts, not just ApproachBody: in a typical
    session that fires 11 times while Touchdown, Liftoff and SAAScanComplete
    together fire 180. Relying on the rare one left the marker stuck wherever
    it was last set.
    """
    bid = entry.get("BodyID")
    if bid is None:
        return
    sysa = entry.get("SystemAddress") or ST.cur_id64
    name = entry.get("Body") or entry.get("BodyName") or ""
    if (bid, sysa) == (ST.last_body_id, ST.last_body_sys):
        return
    ST.last_body_id = bid
    ST.last_body_sys = sysa
    ST.last_body_name = name
    logger.debug("position | %s (body %s in %s)", name, bid, sysa)
    _ui(_route_window_refresh)


def _route_auto_tick(body_name: Optional[str], reason: str) -> None:
    """
    Tick a stop off automatically when the journal says you were there.

    ApproachBody, SAAScanComplete, Touchdown and ScanOrganic all name the body
    directly, so there is no need to tick anything by hand while flying. The
    manual checkbox stays for the cases the journal cannot see - a body you
    looked at and decided to skip.
    """
    if not (body_name and ST.route):
        return
    for st in ST.route.stops:
        if st.body.name == body_name and st.body.body_id not in ST.route_done:
            ST.route_done.add(st.body.body_id)
            if ST.db and ST.cur_id64:
                try:
                    with ST.lock:
                        ST.db.set_route_done(ST.cur_id64, st.body.body_id, True)
                except Exception:
                    logger.exception("could not store automatic tick")
            logger.info("route | reached %s (%s), %d of %d done",
                        st.body.short, reason, len(ST.route_done),
                        len(ST.route.stops))
            _route_progress_feedback(st)
            _ui(_route_window_refresh)
            _ui(_refresh)
            return


def _route_progress_feedback(stop: Any = None) -> None:
    """
    Compare the estimate against what actually happened - leg by leg.

    Each tick measures the time since the previous tick against the planned
    time of the stop just reached, taken now, while it still holds its work
    (once a body is mapped the rebuilt route plans no work for it, so a sum
    over the rebuilt route made every pace look slow). The pace is the
    median of those ratios (sysroute.pace_ratio): a leg with repairs, a
    landing or a body mapped on the side does not decide it. The first tick
    - also halfway through a system after an EDMC restart - starts the
    clock.
    """
    route = ST.route
    now = time.time()
    if route is None or not ST.route_done:
        ST.route_feedback = ""
        return
    if ST.route_started is None:
        ST.route_started = now
        ST.route_legs = []
        ST.route_feedback = ""
        return
    if stop is not None:
        ST.route_legs.append((stop.leg_s, now - ST.route_started))
    ST.route_started = now                   # the next leg starts here
    ratio = pace_ratio(ST.route_legs)
    if ratio is None:
        ST.route_feedback = ""
        return
    left = sum(s.leg_s for s in route.stops
               if s.body.body_id not in ST.route_done)
    ST.route_feedback = ("actual pace %.1fx the estimate - "
                         "remaining is more like %.0f min"
                         % (ratio, left * ratio / 60.0))
    logger.info("route | %s (median of %d legs)", ST.route_feedback, len(ST.route_legs))


def _route_tick(body_id: int) -> None:
    """
    Tick a stop off by hand, and remember it.

    Stored per body in the database rather than in a session list, because a
    system is often left half worked: you fly out, come back days later, and
    the ticks have to still be there.
    """
    done = body_id not in ST.route_done
    if done:
        ST.route_done.add(body_id)
        _route_progress_feedback(next((s for s in (ST.route.stops if ST.route else [])
                                       if s.body.body_id == body_id), None))
    else:
        ST.route_done.discard(body_id)
    if ST.db and ST.cur_id64:
        try:
            with ST.lock:
                ST.db.set_route_done(ST.cur_id64, body_id, done)
        except Exception:
            logger.exception("could not store route tick")
    _route_window_refresh()
    _refresh()


def _route_window_refresh() -> None:
    """
    Redraw the route window: a top-down map, then the stop list.

    The list is grouped by planetary system, because that is how the flight
    actually feels - you arrive at a planet, work its moons, then make a long
    transfer to the next planet. A planet heading is bold and full width, its
    moons are indented under it, and the transfer distance is called out on
    the heading so a long haul is obvious before you start it.
    """
    global _route_rows
    # every route change and every tick passes through here - also when the
    # route window itself is closed
    _overlay_targets()
    if _route_win is None or _route_body is None:
        return
    try:
        for w in _route_body.winfo_children():
            w.destroy()
    except Exception:
        pass
    _route_rows = []
    col = _theme_colours()

    route = ST.route
    lost = _lost_here()
    if route is None or not route.stops:
        _route_head.set("%s\nnothing to fly here - scan the system first%s"
                        % (ST.cur_system or "no system", "\n" + lost if lost else ""))
        _route_map_draw()
        return

    open_stops = [s for s in route.stops if s.body.body_id not in ST.route_done]
    left_s = sum(s.leg_s for s in open_stops)
    left_ls = sum(s.leg_ls for s in open_stops)
    head = ["%s   %d of %d stops left in %d planetary systems"
            % (route.system, len(open_stops), len(route.stops),
               route.group_switches + 1),
            "%.0f LS remaining, roughly %.0f min%s"
            % (left_ls, left_s / 60.0,
               "  (model from %d of your own runs)" % ST.cost_model.samples
               if ST.cost_model.samples else "")]
    if lost:
        head.append(lost)
    if ST.route_from:
        head.append("starts at your carrier (%s) - you arrived on board" % ST.route_from)
    if ST.route_full:
        head.append("nothing outstanding here - showing the full tour")
    if ST.route_done:
        head.append("%d ticked off - kept across restarts" % len(ST.route_done))
    _route_head.set("\n".join(head))

    _route_map_draw()

    row_i = 0
    n = 0
    for label, stops in route.groups():
        n += 1
        transfer = stops[0].leg_ls
        moons_here = len(stops) - 1
        # A planet with no moons needs no heading of its own - it would just
        # repeat the single row underneath. The log showed "4 stops in 4
        # planetary systems", four headings for four lone planets.
        if moons_here == 0:
            st = stops[0]
            done = st.body.body_id in ST.route_done
            row = tk.Frame(_route_body)
            row.grid(row=row_i, column=0, sticky=tk.EW, pady=(6 if row_i else 0, 0))
            row_i += 1
            var = tk.IntVar(value=1 if done else 0)
            cb = tk.Checkbutton(row, variable=var,
                                command=lambda b=st.body.body_id: _route_tick(b))
            cb.pack(side=tk.LEFT)
            text = "%s %-24s %7.0f LS %4.0f min  %s" % (
                _MARK_PLANET, st.body.short[:24], st.leg_ls,
                st.leg_s / 60.0, st.work)
            lone = tk.Label(row, text=text, anchor=tk.W, font=_FONT_GROUP)
            lone.pack(side=tk.LEFT)
            _apply_theme(row, col)
            _apply_theme(cb, col, is_text=True)
            _apply_theme(lone, col, is_text=True)
            _route_rows.append({"body_id": st.body.body_id, "var": var})
            continue
        # --- planet heading -------------------------------------------------
        hdr = tk.Frame(_route_body)
        hdr.grid(row=row_i, column=0, sticky=tk.EW, pady=(8 if row_i else 0, 1))
        row_i += 1
        moons = len(stops) - 1
        htxt = "%s  %s" % (_MARK_PLANET, label)
        if moons:
            htxt += "   +%d moon%s" % (moons, "" if moons == 1 else "s")
        if transfer >= 1.0:
            htxt += "   transfer %.0f LS, %.0f min" % (transfer,
                                                       stops[0].leg_s / 60.0)
        lbl = tk.Label(hdr, text=htxt, anchor=tk.W, font=_FONT_GROUP)
        lbl.pack(side=tk.LEFT)
        _apply_theme(hdr, col)
        _apply_theme(lbl, col, is_text=True)

        # --- the stops of this planetary system -----------------------------
        for st in stops:
            done = st.body.body_id in ST.route_done
            row = tk.Frame(_route_body)
            row.grid(row=row_i, column=0, sticky=tk.EW)
            row_i += 1
            var = tk.IntVar(value=1 if done else 0)
            cb = tk.Checkbutton(row, variable=var,
                                command=lambda b=st.body.body_id: _route_tick(b))
            cb.pack(side=tk.LEFT)
            indent = "    " if st.is_moon else ""
            marker = _MARK_MOON if st.is_moon else _MARK_BODY
            text = "%s%s %-24s %7.0f LS %4.0f min  %s" % (
                indent, marker, st.body.short[:24], st.leg_ls,
                st.leg_s / 60.0, st.work)
            body_lbl = tk.Label(row, text=text, anchor=tk.W,
                                font=_FONT_MOON if st.is_moon else _FONT_BODY)
            body_lbl.pack(side=tk.LEFT)
            _apply_theme(row, col)
            _apply_theme(cb, col, is_text=True)
            _apply_theme(body_lbl, col, is_text=True)
            _route_rows.append({"body_id": st.body.body_id, "var": var})

    _route_theme()


def _measure_work(ev: str, entry: Dict[str, Any]) -> None:
    """
    Time the work at a body as it happens.

    These intervals are clean in a way supercruise timings are not: a surface
    scan is bracketed by arrival and SAAScanComplete, a sample by its own Log
    and Analyse events. Nothing can stretch them except the commander pausing,
    which the trimmed median then discards.
    """
    try:
        now = time.time()
        if ev == "SAAScanComplete":
            b = entry.get("BodyName")
            t0 = ST._arrive.pop(b, None) if b else None
            if t0 and 10 < now - t0 < 1800:
                ST.work_dss.append(now - t0)
        elif ev == "ScanOrganic":
            key = (entry.get("SystemAddress"), entry.get("Body"),
                   entry.get("Species"))
            kind = entry.get("ScanType")
            if kind in ("Log", "Sample"):
                ST._bio_log.setdefault(key, now)
            elif kind == "Analyse":
                t0 = ST._bio_log.pop(key, None)
                if t0 and 20 < now - t0 < 3600:
                    ST.work_bio.append(now - t0)
        total = len(ST.work_dss) + len(ST.work_bio)
        if total and total % 5 == 0:
            ST.cost_model = calibrate_work_from_journal(
                ST.work_dss, ST.work_bio, ST.work_approach, ST.cost_model)
            logger.info("work model recalibrated: %s", ST.cost_model.as_dict())
    except Exception:
        logger.exception("work measurement failed")


def _bootstrap_work_model() -> None:
    """Measure the work constants once from the existing journals."""
    import glob
    import calendar
    d = _journal_dir()
    if not d:
        return
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))[-30:]
    dss: List[float] = []
    bio: List[float] = []
    arrive: Dict[str, float] = {}
    blog: Dict[Tuple, float] = {}
    last_saa: Dict[int, float] = {}
    # supercruise legs body A -> body B: (system, A, B, entry time, seconds)
    here: Dict[str, Any] = {"sys": None, "body": None}
    sc_from: Optional[Tuple[int, str, float]] = None
    sc_legs: List[Tuple[int, str, str, float, float]] = []
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        ts = calendar.timegm(time.strptime(
                            e["timestamp"], "%Y-%m-%dT%H:%M:%SZ"))
                    except (ValueError, KeyError):
                        continue
                    v = e.get("event")
                    if v in ("FSDJump", "CarrierJump", "Location"):
                        here = {"sys": e.get("SystemAddress"), "body": None}
                        sc_from = None
                    elif v == "SupercruiseEntry":
                        sc_from = ((here["sys"], here["body"], ts)
                                   if here["sys"] and here["body"] else None)
                    elif v == "SupercruiseExit":
                        b = e.get("Body")
                        if (sc_from and b and b != sc_from[1]
                                and e.get("SystemAddress") == sc_from[0]
                                and 5 < ts - sc_from[2] < 3600):
                            sc_legs.append((sc_from[0], sc_from[1], b,
                                            sc_from[2], ts - sc_from[2]))
                        sc_from = None
                        if b and e.get("SystemAddress"):
                            here = {"sys": e["SystemAddress"], "body": b}
                    elif v in ("ApproachBody", "Touchdown", "Liftoff"):
                        if e.get("Body") and e.get("SystemAddress"):
                            here = {"sys": e["SystemAddress"], "body": e["Body"]}
                    elif v in ("Shutdown", "LoadGame", "Died", "Resurrect"):
                        sc_from = None
                    if v in ("ApproachBody", "SupercruiseExit"):
                        if e.get("Body"):
                            arrive[e["Body"]] = ts
                    elif v == "SAAScanComplete":
                        # Most mapping is done straight from supercruise with
                        # no ApproachBody at all, so the honest bracket is the
                        # gap between consecutive mappings in one system: it
                        # covers the transfer plus the probe run, which is
                        # exactly the per-body rate the estimate needs.
                        t0 = arrive.pop(e.get("BodyName"), None)
                        prev = last_saa.get(e.get("SystemAddress"))
                        if t0 and 10 < ts - t0 < 1800:
                            dss.append(ts - t0)
                        elif prev and 20 < ts - prev < 1800:
                            dss.append(ts - prev)
                        last_saa[e.get("SystemAddress")] = ts
                    elif v == "ScanOrganic":
                        key = (e.get("SystemAddress"), e.get("Body"),
                               e.get("Species"))
                        if e.get("ScanType") in ("Log", "Sample"):
                            blog.setdefault(key, ts)
                        elif e.get("ScanType") == "Analyse":
                            t0 = blog.pop(key, None)
                            if t0 and 20 < ts - t0 < 3600:
                                bio.append(ts - t0)
        except OSError:
            continue
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


def _version_tuple(v: str) -> Tuple[int, ...]:
    """'v4.1.0' -> (4, 1, 0). Anything unparseable sorts lowest."""
    parts = []
    for chunk in (v or "").lstrip("vV").split(".")[:4]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _check_for_update(force: bool = False) -> None:
    """
    Ask GitHub whether a newer release exists. Notify only - never touch files.

    The plugin is deliberately not self-updating: its value sits in a database
    that grows over months, and a half-applied update in the same folder is
    the one failure that is genuinely painful. Copying eight files by hand a
    few times a year is the better trade.

    Checked once a day at most. GitHub allows 60 unauthenticated calls per
    hour per address, and every failure is swallowed - an update check must
    never be the reason something does not work.
    """
    # Every way out says why, at INFO: in 4.0 the check left no trace at all
    # in the log, so nobody could tell whether it ran, failed or was off.
    if not force and not cfg_bool(CFG["check_updates"], True):
        logger.info("update check: switched off in the preferences")
        return
    if not force:
        last = cfg_str(CFG["update_checked"], "")
        try:
            if last and time.time() - float(last) < 86400:
                logger.info("update check: last run %.1f h ago, next after 24 h",
                            (time.time() - float(last)) / 3600.0)
                return
        except ValueError:
            pass
    if not ST.net.usable:
        logger.info("update check: 'requests' not available in this EDMC build")
        return
    try:
        r = ST.net.request("github", "GET", RELEASES_API, "releases/latest",
                           timeout=10,
                           headers={"Accept": "application/vnd.github+json"})
        _flush_net_log()
        if r is None:
            logger.info("update check: no answer (offline, resting or no network)")
            return
        cfg_set(CFG["update_checked"], str(int(time.time())))
        if r.status_code == 403:
            logger.info("update check: rate limited by GitHub, trying again tomorrow")
            return
        if r.status_code == 404:
            logger.info("update check: no release published yet")
            return
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.info("update check failed (ignored): %s", e)
        return

    tag = (data.get("tag_name") or "").strip()
    if not tag:
        return
    if _version_tuple(tag) <= _version_tuple(VERSION):
        logger.info("update check: %s is current (latest %s)", VERSION, tag)
        if force:
            _set_status("up to date (%s)" % VERSION)
        return

    ST.update_version = tag
    ST.update_notes = (data.get("body") or "").strip()
    logger.info("update available: %s (running %s) - %s", tag, VERSION,
                RELEASES_URL)
    for line in ST.update_notes.splitlines()[:8]:
        logger.info("update | %s", line)
    _set_status("update %s available - click here" % tag)
    _ui(_refresh)


# ---------------------------------------------------------------------------
# SHBOX FIS - the flight information system in the FIS folder. It runs as its
# own Python process (EDMC's built-in Python cannot host it); the plugin only
# starts it and opens it in the browser.
# ---------------------------------------------------------------------------

FIS_DIR = os.path.join(_PLUGIN_DIR, "FIS")
FIS_BAT = os.path.join(FIS_DIR, "start_fis.bat")


def _fis_settings() -> Dict[str, str]:
    """Port, LAN and token from FIS/fis.ini (written by the FIS's first start)."""
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(os.path.join(FIS_DIR, "fis.ini"), encoding="utf-8")
    except Exception:
        pass
    s = cp["fis"] if cp.has_section("fis") else {}
    return {"port": str(s.get("port", "8770") or "8770"), "lan": str(s.get("lan", "false")),
            "token": str(s.get("token", "") or "")}


def _fis_python() -> Optional[str]:
    """A Python the start script will find (same order as start_fis.bat)."""
    import glob
    import shutil
    local = os.environ.get("LOCALAPPDATA", "")
    found = sorted(glob.glob(os.path.join(local, "Programs", "Python", "Python3*", "python.exe")),
                   reverse=True)
    return found[0] if found else (shutil.which("py") or shutil.which("python"))


def _fis_running(port: str) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
            return True
    except (OSError, ValueError):
        return False


def _fis_status() -> str:
    if not os.path.exists(FIS_BAT):
        return "FIS folder not found (download the full release)"
    st = _fis_settings()
    if _fis_running(st["port"]):
        return "running on port %s%s" % (st["port"], " (home network)" if st["lan"].lower() == "true" else "")
    py = _fis_python()
    return ("not running - Python found: %s" % py) if py else \
        "not running - needs Python 3.11+ (python.org), EDMC's Python cannot run it"


def _fis_setup_done() -> bool:
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(os.path.join(FIS_DIR, "fis.ini"), encoding="utf-8")
        return cp.get("fis", "setup_done", fallback="false").strip().lower() == "true"
    except Exception:
        return False


def _fis_start(minimized: bool = False, open_if_running: bool = True) -> None:
    """
    Start the FIS in its own console window - independent of EDMC, it keeps
    running when EDMC closes. Minimised only once the first-start questions
    have been answered (they need the window).
    """
    if not os.path.exists(FIS_BAT):
        return
    st = _fis_settings()
    if _fis_running(st["port"]):
        if open_if_running:
            _fis_open()
        return
    try:
        if minimized and _fis_setup_done():
            import subprocess
            subprocess.Popen('start "SHBOX FIS" /min "%s"' % FIS_BAT, shell=True, cwd=FIS_DIR)
        else:
            os.startfile(FIS_BAT)
        logger.info("FIS | started %s%s", FIS_BAT, " (minimised)" if minimized else "")
    except Exception:
        logger.exception("FIS | could not start %s", FIS_BAT)


FIS_AUTOSTART_DELAY_MS = 4000      # let EDMC finish starting first


def _fis_autostart() -> None:
    """Start the FIS with EDMC when the commander asked for it (settings)."""
    if not cfg_bool(CFG["fis_autostart"], False) or not os.path.exists(FIS_BAT):
        return
    threading.Thread(target=lambda: _fis_start(minimized=True, open_if_running=False),
                     name="shbox-fis-autostart", daemon=True).start()


def _fis_open() -> None:
    """Open the running FIS in the browser of this PC."""
    import webbrowser
    st = _fis_settings()
    url = "http://127.0.0.1:%s/" % st["port"]
    if st["lan"].lower() == "true" and st["token"]:
        url += "?token=" + st["token"]
    try:
        webbrowser.open(url)
    except Exception:
        logger.exception("FIS | could not open the browser")


def _open_release_page() -> None:
    """Open the release page; the copying stays with the commander."""
    import webbrowser
    try:
        webbrowser.open(RELEASES_URL if ST.update_version else REPO_URL)
        if ST.update_version:
            cfg_set(CFG["update_seen"], ST.update_version)
    except Exception:
        logger.exception("could not open the browser")
        _copy(RELEASES_URL)


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
        _check_for_update()
    except Exception:
        logger.exception("update check failed")
    _ui(_refresh)


def _bootstrap_last_body() -> None:
    """
    Recover the last body we were at.

    The live position appears in no journal event, so the newest
    ApproachBody / SupercruiseExit / Touchdown is the closest thing to it.
    Read backwards so the first hit wins.
    """
    import glob
    d = _journal_dir()
    if not d:
        return
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))
    for fn in reversed(files[-3:]):
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line or '"BodyID"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") in ("ApproachBody", "SupercruiseExit",
                                  "Touchdown", "Liftoff",
                                  "SAAScanComplete") and e.get("BodyID") is not None:
                ST.last_body_id = e["BodyID"]
                ST.last_body_name = e.get("Body") or e.get("BodyName") or ""
                ST.last_body_sys = e.get("SystemAddress")
                logger.info("last known position: %s (body %d)",
                            ST.last_body_name or "?", ST.last_body_id)
                return
    logger.info("last position unknown - no body approach in recent journals")


def _bootstrap_fuel() -> None:
    """Read ship fuel figures out of the recent journals."""
    import glob
    d = _journal_dir()
    if not d:
        return
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))[-6:]
    cmdr: Optional[str] = None
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    v = e.get("event")
                    if v in ("Commander", "LoadGame"):
                        cmdr = e.get("Name") or e.get("Commander") or cmdr
                    if v in ("LoadGame", "Loadout") and e.get("ShipID") is not None:
                        ST.fuel.set_ship((cmdr, e.get("ShipID")))
                    if v == "Loadout":
                        if e.get("MaxJumpRange"):
                            ST.fuel.max_jump = float(e["MaxJumpRange"])
                        cap = (e.get("FuelCapacity") or {}).get("Main")
                        if cap:
                            ST.fuel.capacity = float(cap)
                    elif v == "FSDJump":
                        if e.get("FuelUsed") is not None:
                            ST.fuel.add_jump(e.get("JumpDist"), e.get("FuelUsed"))
                        if e.get("FuelLevel") is not None:
                            ST.fuel.level = float(e["FuelLevel"])
        except (OSError, TypeError, ValueError):
            continue
    logger.info("fuel | %s", ST.fuel.summary())


def _plan_staging() -> None:
    """Work out where the carrier should go next, tritium permitting."""
    if not (ST.db and ST.planner and ST.center):
        _set_status("no active sphere")
        return
    with ST.lock:
        rows = best_staging(ST.db, ST.planner, ST.center, ST.radius,
                            get_masscodes())
    ST.staging = rows
    for line in staging_lines(rows):
        logger.info("carrier | %s", line)
    if rows:
        _set_status("next carrier spot: %s (%.0f ly, %d icy rings)"
                    % (rows[0]["name"], rows[0]["dist"], rows[0]["icy_rings"]))
    else:
        _set_status("no tritium system known far enough out yet")


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
    _rebuild_route()
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
    _set_status("route re-ordered after %s (%+.0f LS)" % (reason, delta))


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
    _run_async(_route_review_worker, label="review")


def _route_review_worker() -> None:
    if not (ST.db and ST.cur_id64 and ST.route and ST.route.stops):
        _set_status("no route to review")
        return
    visits = _actual_visits(ST.cur_id64)
    if not visits:
        logger.info("review | no approaches recorded for %s yet", ST.cur_system)
        _set_status("nothing flown here yet")
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
        _set_status("only %d stop flown here so far" % len(seq))
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
        _set_status("review: %.0f LS flown, %.0f%% above the best order "
                    "(details in log)" % (actual_ls, over))
    else:
        _set_status("review: %.0f LS flown, within %.0f%% of the best order"
                    % (actual_ls, max(0.0, over)))


def _actual_visits(sys_id64: int) -> List[Tuple[str, float]]:
    """
    (body name, unix time) for every body approached in this system, in order.

    Read straight from the journals rather than kept in memory, so it also
    works for a system flown before the plugin was running.
    """
    import glob
    import calendar
    d = _journal_dir()
    if not d:
        return []
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))[-8:]
    out: List[Tuple[str, float]] = []
    seen = set()
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"Body' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("SystemAddress") != sys_id64:
                        continue
                    if e.get("event") not in ("ApproachBody", "SupercruiseExit",
                                              "SAAScanComplete"):
                        continue
                    nm = e.get("Body") or e.get("BodyName")
                    if not nm or nm in seen:
                        continue
                    try:
                        ts = calendar.timegm(time.strptime(
                            e["timestamp"], "%Y-%m-%dT%H:%M:%SZ"))
                    except (KeyError, ValueError):
                        continue
                    seen.add(nm)
                    out.append((nm, float(ts)))
        except OSError:
            continue
    out.sort(key=lambda p: p[1])
    return out


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
    use_carrier = bool(_carrier_var.get()) if _carrier_var else False
    if use_carrier:
        if not (ST.carrier and ST.carrier.get("coords")):
            _set_status("no carrier position known - dock at it once")
            return
        center = tuple(ST.carrier["coords"])
        label = ST.carrier["system"]
        origin_kind = "carrier"
    else:
        if not ST.cur_pos:
            _set_status("position unknown - jump first")
            return
        center = ST.cur_pos
        label = ST.cur_system
        origin_kind = "free"

    if ST.active and ST.center and ST.center != center:
        logger.info("survey re-centred: %s -> %s", ST.start_system, label)

    radius = float(_radius_var.get()) if _radius_var else 50.0

    with ST.lock:
        ov = ST.db.sphere_overlap(center, radius)
    if ov["volume_pct"] > 0.5:
        msg = ("overlap %.0f%% with earlier spheres (worst %s at %.0f ly, %.0f%%); "
               "%d of %d known systems already visited"
               % (ov["volume_pct"], ov["worst_label"] or "-",
                  ov["worst_distance"] or 0.0, ov["worst_pct"],
                  ov["visited"], ov["known"]))
        logger.info(msg)
        _set_status("overlap %.0f%% | %d systems already visited | move %.0f ly for none"
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
    _run_async(_start_worker, label="starting survey")


def _start_worker() -> None:
    ST.horizon = 0.0
    _fetch_local()
    _advance_horizon(allow_fetch=True)
    _rebuild_plan()


def _stop_survey() -> None:
    ST.active = False
    if ST.sphere_id and ST.stats.get("finished"):
        with ST.lock:
            ST.db.close_sphere(ST.sphere_id)
    with ST.lock:
        ST.db.save_survey(False, ST.start_system, ST.center, ST.radius, get_masscodes())
    ST.flight = []
    ST.probe = []
    _refresh()


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
        ST.db.mark_absent(t.name)
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
    _set_status("%s does not exist - boxel closed (%d candidates dropped)"
                % (t.name, max(0, dropped - 1)))
    _refresh()
    _copy_probe()


def _boxel_done() -> None:
    """
    The galaxy map list for this boxel is fully accounted for. Close it in one
    go - every remaining candidate of that boxel leaves the queue. This is the
    cheap path: one prefix search plus one click retires a whole boxel.
    """
    t = current_probe()
    if not t or not t.boxel_key:
        return
    with ST.lock:
        end = ST.db.close_boxel(t.boxel_key)
    key = t.boxel_key
    before = len(ST.probe)
    ST.probe = [q for q in ST.probe if q.boxel_key != key]
    dropped = before - len(ST.probe)
    logger.info("boxel %s closed at n2=%d by hand, %d candidates dropped",
                key, end, dropped)
    _set_status("boxel %s done (%d candidates dropped)" % (key, dropped))
    _refresh()
    _copy_probe()


def _copy_prefix() -> None:
    """Copy the boxel search prefix - one paste lists the whole boxel."""
    t = current_probe()
    if t and t.boxel_key:
        _copy(boxel_prefix(t.boxel_key))
    else:
        _set_status("no boxel prefix for this candidate")


def _copy_bundle() -> None:
    """Copy one prefix for several of the next probe boxels (same sector,
    letters and mass code) - one paste in the galaxy map lists them all."""
    prefix, keys = bundled_probe_prefix(ST.probe, 5)
    if not prefix:
        _set_status("no probe boxels to bundle")
        return
    _copy(prefix)
    if len(keys) > 1:
        tails = ", ".join(k[len(prefix):] or k.split()[-1] for k in keys)
        _set_status("'%s' lists the next %d probe boxels (%s) - and the other "
                    "boxels starting with it" % (prefix, len(keys), tails))
    else:
        _set_status("only one of the next boxels in this group - '%s' copied"
                    % prefix)


def _probe_skip() -> None:
    if ST.probe:
        ST.probe.append(ST.probe.pop(0))
    _refresh()
    _copy_probe()


def _flight_skip() -> None:
    if ST.flight:
        ST.flight.append(ST.flight.pop(0))
    _refresh()
    _copy_flight()


def _copy(text: str) -> None:
    if not _frame or not text:
        return
    try:
        _frame.clipboard_clear()
        _frame.clipboard_append(text)
        _frame.update_idletasks()
        _set_status("copied: %s" % text)
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
        _set_status("no carrier system remembered yet")


_stats_win: Optional[tk.Toplevel] = None
_stats_body: Optional[tk.Frame] = None
_stats_scroll: Optional[tk.Canvas] = None


def _toggle_stats_window() -> None:
    global _stats_win
    if _stats_win is not None:
        _stats_window_close()
        return
    _stats_window_open()


def _stats_window_close() -> None:
    global _stats_win, _stats_body
    if _stats_win is not None:
        try:
            _stats_win.destroy()
        except Exception:
            pass
    _stats_win = None
    _stats_body = None
    _refresh()


def _stats_window_open() -> None:
    """Statistics in their own window, as tables, in the host's colours."""
    global _stats_win, _stats_body
    if _frame is None:
        return
    _stats_win = tk.Toplevel(_frame)
    _stats_win.title("SHBOXSEARCH - survey statistics")
    _stats_win.protocol("WM_DELETE_WINDOW", _stats_window_close)
    try:
        _stats_win.attributes("-topmost", cfg_bool(CFG["route_top"], True))
    except Exception:
        pass
    global _stats_scroll
    _stats_scroll = tk.Canvas(_stats_win, highlightthickness=0,
                              width=430, height=520)
    _stats_scroll.grid(row=0, column=0, sticky=tk.NSEW, padx=(10, 0), pady=8)
    sb = tk.Scrollbar(_stats_win, orient=tk.VERTICAL,
                      command=_stats_scroll.yview)
    sb.grid(row=0, column=1, sticky=tk.NS, pady=8)
    _stats_scroll.configure(yscrollcommand=sb.set)
    _stats_body = tk.Frame(_stats_scroll)
    _stats_scroll.create_window((0, 0), window=_stats_body, anchor=tk.NW)
    _stats_body.bind("<Configure>", lambda e: _stats_scroll.configure(
        scrollregion=_stats_scroll.bbox("all")))
    _stats_win.columnconfigure(0, weight=1)
    _stats_win.rowconfigure(0, weight=1)
    bar = tk.Frame(_stats_win)
    bar.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=(0, 8))
    tk.Button(bar, text="refresh",
              command=lambda: _run_async(_rebuild_plan, label="stats")).pack(
        side=tk.LEFT)
    tk.Button(bar, text="reload online data",
              command=lambda: _run_async(_reload_online,
                                         label="reload online data")).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="close", command=_stats_window_close).pack(
        side=tk.LEFT, padx=(4, 0))
    _stats_window_refresh()
    _fit_to_screen(_stats_win)
    _refresh()


def _thousands(n: int) -> str:
    return "{:,}".format(int(n)).replace(",", " ")


def _stats_window_refresh() -> None:
    """Draw the statistics tables."""
    if _stats_win is None or _stats_body is None:
        return
    try:
        for w in _stats_body.winfo_children():
            w.destroy()
    except Exception:
        pass
    col = _theme_colours()
    row_i = 0

    def table(title: str, rows: List[Tuple[str, str]]) -> None:
        nonlocal row_i
        head = tk.Label(_stats_body, text=title, anchor=tk.W, font=_FONT_GROUP)
        head.grid(row=row_i, column=0, columnspan=2, sticky=tk.W,
                  pady=(10 if row_i else 0, 2))
        _apply_theme(head, col, is_text=True)
        row_i += 1
        for label, value in rows:
            a = tk.Label(_stats_body, text="  " + label, anchor=tk.W, font=_MONO)
            b = tk.Label(_stats_body, text=value, anchor=tk.W, font=_MONO)
            a.grid(row=row_i, column=0, sticky=tk.W, padx=(8, 16))
            b.grid(row=row_i, column=1, sticky=tk.W)
            _apply_theme(a, col, is_text=True)
            _apply_theme(b, col, is_text=True)
            row_i += 1

    if ST.stats:
        for title, rows in Planner.stats_table(ST.stats):
            table(title, rows)

    # this sphere, in time
    sphere_rows = []
    if ST.start_system:
        sphere_rows.append(("Centre", "%s  r=%.0f ly"
                            % (ST.start_system, ST.radius)))
    if ST.stats.get("systems_measured"):
        sphere_rows.append(("Bodies per system", "%.1f average over %d systems"
                            % (ST.stats["avg_bodies"],
                               ST.stats["systems_measured"])))
    if ST.sys_minutes:
        avg = sum(ST.sys_minutes) / len(ST.sys_minutes)
        sphere_rows.append(("Time per system", "%.0f min average (%d measured)"
                            % (avg, len(ST.sys_minutes))))
        sphere_rows.append(("Time in this sphere", "%.1f h over %d systems"
                            % (sum(ST.sys_minutes) / 60.0, len(ST.sys_minutes))))
    if ST.fuel.capacity:
        sphere_rows.append(("Fuel", ST.fuel.summary()))
    if sphere_rows:
        table("This sphere", sphere_rows)

    # what it paid
    try:
        with ST.lock:
            e = ST.db.earnings()
        if e["sales"]:
            rows = []
            ex, bi = e.get("exploration"), e.get("organic")
            if ex:
                rows.append(("Exploration data", "%.1f M cr from %d bodies"
                             % (ex["total"] / 1e6, ex["units"])))
                if ex["units"]:
                    rows.append(("  per body", "%s cr"
                                 % _thousands(ex["total"] // ex["units"])))
            if bi:
                rows.append(("Biological data", "%.1f M cr from %d samples"
                             % (bi["total"] / 1e6, bi["units"])))
                if bi["units"]:
                    rows.append(("  per sample", "%s cr"
                                 % _thousands(bi["total"] // bi["units"])))
            rows.append(("Total earned", "%.1f M cr over %d sales"
                         % (e["total"] / 1e6, e["sales"])))
            if ex and bi and ex["units"] and bi["units"]:
                ratio = (bi["total"] / bi["units"]) / max(
                    1.0, ex["total"] / ex["units"])
                rows.append(("Bio vs mapping", "%.0fx more per unit" % ratio))
            table("Earnings", rows)
    except Exception:
        logger.exception("earnings summary failed")

    # everything ever
    try:
        with ST.lock:
            lt = ST.db.lifetime()
        who = []
        if lt.get("commander"):
            who.append(("Commander", "%s (main)" % lt["commander"]))
        for nm, n in lt.get("also") or []:
            who.append(("Also explored by", "%s: %d systems" % (nm, n)))
        table("All time", who + [
            ("Systems visited", "%d" % lt["systems_visited"]),
            ("Distance flown", "%.0f ly" % lt["jumps_ly"]),
            ("Bodies scanned", "%d" % lt["bodies"]),
            ("Bodies mapped", "%d" % lt["mapped"]),
            ("First discoveries", "%d" % lt["first_discoveries"]),
            ("First to map", "%d" % lt["first_mapped"]),
            ("Bio sampled", "%d" % lt["bio_sampled"]),
            ("Boxels closed", "%d" % lt["boxels_closed"]),
            ("Names ruled out", "%d" % lt["not_there"]),
            ("Spheres surveyed", "%d" % lt["spheres"]),
        ])
    except Exception:
        logger.exception("lifetime statistics failed")

    _theme_tree(_stats_win, col)


def _toggle_stats() -> None:
    show = not cfg_bool(CFG["show_stats"], False)
    cfg_set(CFG["show_stats"], show)
    _refresh()


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
        while ST.probe and ST.db.system(ST.probe[0].name) is not None:
            ST.probe.pop(0)
            changed = True
    if changed:
        _refresh()


# ============================================================================
# Journal / status
# ============================================================================

def journal_entry(cmdr: str, is_beta: bool, system: str, station: str,
                  entry: Dict[str, Any], state: Dict[str, Any]) -> None:
    if not ST.db:
        return
    ev = entry.get("event")
    if cmdr and cmdr != ST.cmdr:
        if ST.cmdr is not None:
            _commander_switched()
        ST.cmdr = cmdr
    fid = state.get("FID") if isinstance(state, dict) else None
    if fid and fid != ST.db.fid:
        with ST.lock:
            ST.db.set_commander(fid, cmdr)
        _apply_main_cmdr()
    try:
        # Before the dispatch chain: any event naming a body updates where we
        # are. Putting this inside the chain meant whichever branch matched
        # first swallowed it, and the marker stopped moving.
        if entry.get("BodyID") is not None and ev in POSITION_EVENTS:
            _note_position(entry)

        # mining: rock, hold, rate, session, limpets on the overlay
        if ev in miningstat.EVENTS or ev in miningstat.PLACE or ev == "Cargo":
            try:
                cargo = state.get("Cargo") if isinstance(state, dict) else None
                changed = ST.mine.feed(entry, cargo=cargo)
                if changed or (ev == "Cargo" and ST.mine.active()):
                    _mining_overlay(force=True)
            except Exception:
                logger.debug("mining overlay failed", exc_info=True)

        # EDMC enriches NavRoute with the full Route array
        if ev == "NavRoute" and entry.get("Route"):
            _note_navroute(entry.get("Route"))
            try:
                _maybe_route_check(list(ST.navroute))
            except Exception:
                logger.debug("route check not started", exc_info=True)
        elif ev == "NavRouteClear":
            ST.navroute = []
        if ev == "NavRoute" and not cfg_bool(CFG["harvest_navroute"], True):
            return

        with ST.lock:
            ST.db.ingest_journal_event(entry)

        # Supercruise timing, measured on the legs the route actually plans:
        # body A -> body B inside one system. The distance comes from the
        # orbital positions of both bodies at the moment of the flight.
        # Up to 4.2.0 every SupercruiseEntry -> Exit was paired with the
        # *arrival distance* of the target (its distance from the arrival
        # star), which is not the distance flown, so the fit ended at the
        # edge of its grid. The first leg after a jump is left out on purpose:
        # it also holds what you do on arrival (honk, FSS), not just flying.
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
                dt = time.time() - start[0]
                if 5 < dt < 3600:
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

        if ev in ("FSDJump", "CarrierJump"):
            if ST._sys_enter is not None:
                spent = (time.time() - ST._sys_enter) / 60.0
                if 0.5 < spent < 180.0:      # ignore pauses and instant hops
                    ST.sys_minutes.append(spent)
                    del ST.sys_minutes[:-60]
            ST._sys_enter = time.time()

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

        if ev in ("FSDJump", "Location", "CarrierJump"):
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
            pos = entry.get("StarPos")
            if pos and len(pos) >= 3:
                ST.cur_pos = (pos[0], pos[1], pos[2])
            if ST.active:
                _prune_queues()
                _resort_queues()
                _ui(_copy_flight)
            if ev == "FSDJump":
                _overlay_briefing("arrival", ST.cur_system, ST.cur_id64,
                                  entry.get("StarClass") or None)
                if ST.active:
                    threading.Thread(target=_update_route_targets, daemon=True,
                                     name="SHBOX-navroute").start()
                    _maybe_extend()
            _request_route()
            _ui(_refresh)

        elif ev in ("CarrierJump", "CarrierLocation", "CarrierStats") or (
                ev == "Docked" and entry.get("StationType") == "FleetCarrier"):
            with ST.lock:
                ST.carrier = ST.db.get_carrier()
            if ST.carrier:
                logger.info("fleet carrier now at %s", ST.carrier["system"])
                _set_status("carrier: %s" % ST.carrier["system"])
            _ui(_refresh)

        elif ev in ("ApproachBody", "Touchdown"):
            _route_auto_tick(entry.get("Body") or entry.get("BodyName"),
                             "approach" if ev == "ApproachBody" else "landed")

        elif ev == "Loadout":
            if entry.get("ShipID") is not None:
                ST.fuel.set_ship((cmdr, entry.get("ShipID")))
            mj = entry.get("MaxJumpRange")
            if mj:
                ST.max_jump = float(mj)
                ST.fuel.max_jump = float(mj)
            cap = (entry.get("FuelCapacity") or {}).get("Main")
            if cap:
                ST.fuel.capacity = float(cap)

        elif ev == "StartUp":
            if entry.get("StarSystem"):
                ST.cur_system = entry["StarSystem"]
                ST.cur_id64 = entry.get("SystemAddress") or ST.cur_id64
                pos = entry.get("StarPos")
                if pos and len(pos) >= 3:
                    ST.cur_pos = (pos[0], pos[1], pos[2])
                ST.awaiting_position = False
            if not ST.awaiting_position:
                _run_async(_recheck_route, "game restart", label="route recheck")
            route = state.get("NavRoute") if state else None
            if route and route.get("Route"):
                _note_navroute(route.get("Route"))
            if route and cfg_bool(CFG["harvest_navroute"], True):
                with ST.lock:
                    ST.db.ingest_journal_event({"event": "NavRoute",
                                                "Route": route.get("Route", [])})

        elif ev == "Liftoff":
            # Lifting off usually ends a pause spent on the surface.
            _run_async(_recheck_route, "lift-off", label="route recheck")

        elif ev == "ApproachBody":
            if entry.get("Body"):
                ST._arrive[entry["Body"]] = time.time()

        elif ev in ("Scan", "SAAScanComplete", "SAASignalsFound", "FSSBodySignals",
                    "FSSDiscoveryScan", "FSSAllBodiesFound", "ScanOrganic"):
            _measure_work(ev, entry)
            if not ST.cur_id64 and entry.get("SystemAddress"):
                ST.cur_id64 = entry["SystemAddress"]
                ST.cur_system = (entry.get("StarSystem") or entry.get("SystemName")
                                 or ST.cur_system)
            if ST.active:
                _prune_queues()
            if ev == "ScanOrganic":
                _bio_event(entry)
            if ev == "ScanOrganic" and entry.get("ScanType") == "Analyse":
                _bio_model_reset()          # one more find to learn from
            if ev in ("SAAScanComplete", "ScanOrganic"):
                _route_auto_tick(entry.get("BodyName") or entry.get("Body"),
                                 "mapped" if ev == "SAAScanComplete" else "sampled")
            if ev in ("FSSAllBodiesFound", "SAAScanComplete", "ScanOrganic",
                      "FSSBodySignals", "SAASignalsFound"):
                _request_route()
            _ui(_refresh)

        elif ev == "FSDTarget":
            nm = entry.get("Name")
            _overlay_briefing("target", nm, entry.get("SystemAddress"),
                              entry.get("StarClass"))
            t = current_probe()
            if t and nm == t.name:
                _set_status("confirmed: %s" % nm)
                if ST.active:
                    _prune_queues()
            _ui(_refresh)

    except Exception:
        logger.exception("journal_entry(%s) failed", ev)


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
    """Status.json. The Destination field carries the id64 of any selected target."""
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
        fuel = entry.get("Fuel") or {}
        if fuel.get("FuelMain") is not None:
            try:
                ST.fuel.level = float(fuel["FuelMain"])
            except (TypeError, ValueError):
                pass
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
            _set_status("confirmed: %s" % new)
            if ST.active:
                _prune_queues()
        _ui(_refresh)
    except Exception:
        logger.exception("dashboard_entry failed")


# ============================================================================
# User interface
# ============================================================================

def _ui(fn) -> None:
    if _frame:
        try:
            _frame.after(0, fn)
        except Exception:
            pass


def _set_status(txt: str) -> None:
    ST.status = txt
    if _v_status:
        _ui(lambda: _v_status.set(txt))


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """
    The main panel, kept deliberately small.

    EDMC's window is shared with every other plugin, so this shows only what
    you act on between jumps: the next flight target, the next name to check,
    and where you are. Counters, fuel, statistics and the route list all live
    in their own windows, reachable from one row of buttons.
    """
    global _frame, _v_status, _v_target, _v_kind, _v_sys, _v_queue, _v_probe
    global _btn_start, _btn_absent, _btn_skip, _radius_var
    global _btn_fc, _btn_stats, _lbl_stats, _v_stats, _carrier_var
    global _btn_boxel, _btn_prefix, _btn_next, _v_route, _lbl_route, _btn_route
    global _v_fuel, _lbl_queue, _lbl_fuel, _v_update, _lbl_update

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)

    _v_status = tk.StringVar(value="ready")
    _v_target = tk.StringVar(value="-")
    _v_kind = tk.StringVar(value="survey inactive")
    _v_sys = tk.StringVar(value="-")
    _v_probe = tk.StringVar(value="-")
    _v_queue = tk.StringVar(value="")
    _v_stats = tk.StringVar(value="")
    _v_route = tk.StringVar(value="")
    _v_fuel = tk.StringVar(value="")
    _v_update = tk.StringVar(value="")
    _radius_var = tk.StringVar(value=str(cfg_int(CFG["radius"], 50)))
    _carrier_var = tk.IntVar(value=1 if cfg_bool(CFG["carrier_start"], False) else 0)

    # 0  flight target (click to copy)
    tk.Label(_frame, text="Fly").grid(row=0, column=0, sticky=tk.W)
    lt = tk.Label(_frame, textvariable=_v_target, anchor=tk.W)
    lt.grid(row=0, column=1, sticky=tk.EW)
    lt.bind("<Button-1>", lambda e: _copy_flight_click())

    # 1  kind of flight target
    tk.Label(_frame, textvariable=_v_kind, anchor=tk.W).grid(
        row=1, column=1, sticky=tk.EW)

    # 2  galaxy map probe
    tk.Label(_frame, text="Probe").grid(row=2, column=0, sticky=tk.W)
    lp = tk.Label(_frame, textvariable=_v_probe, anchor=tk.W)
    lp.grid(row=2, column=1, sticky=tk.EW)
    lp.bind("<Button-1>", lambda e: _copy_probe())

    # 3  current system
    tk.Label(_frame, text="Here").grid(row=3, column=0, sticky=tk.W)
    tk.Label(_frame, textvariable=_v_sys, anchor=tk.W).grid(
        row=3, column=1, sticky=tk.EW)

    # 4  one row of buttons - everything else opens a window
    bar = tk.Frame(_frame)
    bar.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(3, 0))
    _btn_start = tk.Button(bar, text="Start", width=6, command=_on_start)
    _btn_start.pack(side=tk.LEFT)
    radius_pick = ttk.OptionMenu(bar, _radius_var, _radius_var.get(),
                                 *RADIUS_CHOICES)
    radius_pick.pack(side=tk.LEFT, padx=(3, 4))
    _theme_menu(radius_pick, _theme_colours())
    _btn_next = tk.Button(bar, text="copy", width=6, command=_copy_flight_click)
    _btn_next.pack(side=tk.LEFT)
    _btn_route = tk.Button(bar, text="route", width=6,
                           command=_toggle_route_window)
    _btn_route.pack(side=tk.LEFT, padx=(3, 0))
    _btn_stats = tk.Button(bar, text="info", width=6,
                           command=_toggle_stats_window)
    _btn_stats.pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(bar, text="probe", width=6,
              command=_toggle_probe_window).pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(bar, text="atlas", width=6,
              command=_toggle_mining_window).pack(side=tk.LEFT, padx=(3, 0))

    # 5-7  optional lines, hidden unless switched on
    _lbl_route = tk.Label(_frame, textvariable=_v_route, anchor=tk.W,
                          justify=tk.LEFT)
    _lbl_route.grid(row=5, column=0, columnspan=2, sticky=tk.EW)
    _lbl_fuel = tk.Label(_frame, textvariable=_v_fuel, anchor=tk.W)
    _lbl_fuel.grid(row=6, column=0, columnspan=2, sticky=tk.EW)
    _lbl_queue = tk.Label(_frame, textvariable=_v_queue, anchor=tk.W)
    _lbl_queue.grid(row=7, column=0, columnspan=2, sticky=tk.EW)
    _lbl_stats = tk.Label(_frame, textvariable=_v_stats, anchor=tk.W,
                          justify=tk.LEFT)
    _lbl_stats.grid(row=8, column=0, columnspan=2, sticky=tk.EW)
    tk.Label(_frame, textvariable=_v_status, anchor=tk.W).grid(
        row=9, column=0, columnspan=2, sticky=tk.EW)

    # Only appears when a newer release exists. Clicking opens the page -
    # the plugin never replaces its own files.
    _lbl_update = tk.Label(_frame, textvariable=_v_update, anchor=tk.W,
                           cursor="hand2")
    _lbl_update.grid(row=10, column=0, columnspan=2, sticky=tk.EW)
    _lbl_update.bind("<Button-1>", lambda e: _open_release_page())
    _lbl_update.grid_remove()

    _refresh()
    theme.update(_frame)
    # SHBOX FIS along with EDMC, when ticked in the settings
    _frame.after(FIS_AUTOSTART_DELAY_MS, _fis_autostart)
    _frame.after(OVERLAY_KEEP_MS, _overlay_keepalive)
    return _frame


# ---------------------------------------------------------------------------
# Probe window - the galaxy map checking controls, out of the main panel
# ---------------------------------------------------------------------------

_probe_win: Optional[tk.Toplevel] = None
_probe_head: Optional[tk.StringVar] = None


# ---------------------------------------------------------------------------
# Mining window - find a ring again, months later
# ---------------------------------------------------------------------------

_mine_win: Optional[tk.Toplevel] = None
_mine_body: Optional[tk.Frame] = None
_mine_mat: Optional[tk.StringVar] = None


def _toggle_mining_window() -> None:
    global _mine_win
    if _mine_win is not None:
        _mining_window_close()
        return
    _mining_window_open()


def _mining_window_close() -> None:
    global _mine_win, _mine_body
    if _mine_win is not None:
        try:
            _mine_win.destroy()
        except Exception:
            pass
    _mine_win = None
    _mine_body = None


ATLAS_MODES = ("ring hotspots", "body signals", "materials picked up", "finds on the ground")
# tab captions, and which setting remembers each tab's picker
ATLAS_TABS = {ATLAS_MODES[0]: "rings", ATLAS_MODES[1]: "signals",
              ATLAS_MODES[2]: "materials", ATLAS_MODES[3]: "finds"}
_ATLAS_KEY = {ATLAS_MODES[0]: "mine_mat", ATLAS_MODES[1]: "atlas_sig",
              ATLAS_MODES[2]: "atlas_mat", ATLAS_MODES[3]: "atlas_find"}
_atlas_mode: Optional[tk.StringVar] = None
_atlas_pick_frame: Optional[tk.Frame] = None
_atlas_tabs: Dict[str, Any] = {}
_atlas_range: Optional[tk.StringVar] = None
# far from the bubble, finds 2000 ly back would fill the list - limit by distance
ATLAS_RANGES = ("any distance", "25 ly", "50 ly", "100 ly", "250 ly", "500 ly",
                "1000 ly", "2000 ly")


def _atlas_max_ly() -> Optional[float]:
    v = _atlas_range.get() if _atlas_range is not None else ATLAS_RANGES[0]
    try:
        return float(v.split()[0])
    except (ValueError, IndexError):
        return None
# signal kinds shown first, in this order; everything else follows by count
_SIG_FIRST = ("mining_location", "geological", "biological", "genus:Brain Trees",
              "site:nonhuman", "site:guardian", "thargoid", "guardian", "human",
              "uss:nonhuman")


def _sig_label(k: Dict[str, Any]) -> str:
    kind, label = k["kind"], k["label"] or k["kind"]
    if kind == "genus:Brain Trees":
        return "Brain Trees"
    if kind.startswith("genus:"):
        return "Bio: " + label
    if kind.startswith("codex:"):
        return "Codex: " + label
    return label


def _atlas_choices(mode: str) -> List[Tuple[str, Optional[str]]]:
    """(label shown, key used for the query) for the second picker."""
    with ST.lock:
        if mode == ATLAS_MODES[1]:
            kinds = ST.db.signal_kinds()
        elif mode == ATLAS_MODES[2]:
            kinds = ST.db.material_kinds()
        elif mode == ATLAS_MODES[3]:
            kinds = ST.db.find_kinds()
        else:
            kinds = ST.db.hotspot_materials()
    if mode == ATLAS_MODES[1]:
        order = {k: i for i, k in enumerate(_SIG_FIRST)}
        kinds = sorted(kinds, key=lambda k: (order.get(k["kind"], 99), -k["total"]))
        return [("(all)", None)] + [(_sig_label(k), k["kind"]) for k in kinds]
    if mode == ATLAS_MODES[2]:
        return [("(all)", None)] + [("%s: %s" % ((k["category"] or "?")[:5], k["label"]),
                                     k["material"]) for k in kinds]
    if mode == ATLAS_MODES[3]:
        return [("(all)", None)] + [("%s (%d)" % (k["label"], k["places"]), k["kind"])
                                    for k in kinds]
    return [("(all)", None)] + [((m["label"] or m["material"]), m["material"])
                                for m in kinds]


def _mining_window_open() -> None:
    """
    The atlas: what you have found, searchable, nearest first.

    * ring hotspots - mining materials from ring scans (since 4.0)
    * body signals - planetary mining locations, geological / biological /
      thargoid / guardian / human signals, the genera the DSS names (Brain
      Trees), codex sites, and non-human or Guardian sites marked from what
      you picked up there (the journal reports those sites themselves never)
    * materials picked up - every MaterialCollected with the body you were at
    * finds on the ground - codex finds, analysed species, settlements and
      screenshots with the body and the latitude/longitude where they were

    One tab per kind; clicking a row copies the system name.
    """
    global _mine_win, _mine_body, _mine_mat, _atlas_mode, _atlas_pick_frame, _atlas_range
    if _frame is None or ST.db is None:
        return
    _mine_win = tk.Toplevel(_frame)
    _mine_win.title("SHBOXSEARCH - atlas")
    _mine_win.protocol("WM_DELETE_WINDOW", _mining_window_close)
    try:
        _mine_win.attributes("-topmost", cfg_bool(CFG["route_top"], True))
    except Exception:
        pass

    mode = cfg_str(CFG["atlas_mode"], ATLAS_MODES[0])
    _atlas_mode = tk.StringVar(value=mode if mode in ATLAS_MODES else ATLAS_MODES[0])

    tabs = tk.Frame(_mine_win)
    tabs.grid(row=0, column=0, sticky=tk.EW, padx=10, pady=(8, 0))
    _atlas_tabs.clear()
    for m in ATLAS_MODES:
        # radio buttons drawn as buttons: one tab per kind of find
        rb = tk.Radiobutton(tabs, text=ATLAS_TABS[m], value=m, variable=_atlas_mode,
                            indicatoron=False, width=12, padx=4, pady=2,
                            command=_atlas_build_picker)
        rb.pack(side=tk.LEFT, padx=(0, 2))
        _atlas_tabs[m] = rb
    bar = tk.Frame(_mine_win)
    bar.grid(row=1, column=0, sticky=tk.EW, padx=10, pady=(4, 4))
    _atlas_pick_frame = tk.Frame(bar)
    _atlas_pick_frame.pack(side=tk.LEFT, padx=(6, 0))
    rng = cfg_str(CFG["atlas_range"], ATLAS_RANGES[0])
    _atlas_range = tk.StringVar(value=rng if rng in ATLAS_RANGES else ATLAS_RANGES[0])
    rng_pick = ttk.OptionMenu(bar, _atlas_range, _atlas_range.get(), *ATLAS_RANGES,
                              command=lambda *_: (cfg_set(CFG["atlas_range"], _atlas_range.get()),
                                                  _mining_refresh()))
    rng_pick.pack(side=tk.LEFT, padx=(6, 0))
    _theme_menu(rng_pick, _theme_colours())
    tk.Button(bar, text="refresh", command=_atlas_build_picker).pack(
        side=tk.LEFT, padx=(6, 0))
    tk.Button(bar, text="close", command=_mining_window_close).pack(
        side=tk.LEFT, padx=(4, 0))

    _mine_body = tk.Frame(_mine_win)
    _mine_body.grid(row=2, column=0, sticky=tk.NSEW, padx=10, pady=(0, 8))
    _atlas_build_picker()
    _theme_tree(_mine_win, _theme_colours())
    _fit_to_screen(_mine_win)


def _atlas_build_picker() -> None:
    """(Re)build the second picker for the chosen mode, then the list."""
    global _mine_mat
    if _atlas_pick_frame is None or _atlas_mode is None:
        return
    for w in _atlas_pick_frame.winfo_children():
        w.destroy()
    mode = _atlas_mode.get()
    cfg_set(CFG["atlas_mode"], mode)
    for m, rb in _atlas_tabs.items():
        try:
            rb.configure(text=("[ %s ]" % ATLAS_TABS[m]) if m == mode else ATLAS_TABS[m])
        except Exception:
            pass
    names = [c[0] for c in _atlas_choices(mode)]
    _mine_mat = tk.StringVar(value=cfg_str(CFG[_ATLAS_KEY[mode]], names[0]))
    if _mine_mat.get() not in names:
        _mine_mat.set(names[0])
    picker = ttk.OptionMenu(_atlas_pick_frame, _mine_mat, _mine_mat.get(), *names,
                            command=lambda *_: _mining_refresh())
    picker.pack(side=tk.LEFT)
    _theme_menu(picker, _theme_colours())
    _mining_refresh()


def _atlas_row(parent, row: int, text: str, system: str, col) -> None:
    lbl = tk.Label(parent, text=text, anchor=tk.W, font=_MONO)
    lbl.grid(row=row, column=0, sticky=tk.W)
    lbl.bind("<Button-1>", lambda e, n=system: _copy(n))
    _apply_theme(lbl, col, is_text=True)


def _short_body(body: Optional[str], system: str) -> str:
    b = str(body or "")
    return b[len(system):].strip() if system and b.startswith(system) else b


def _mining_refresh() -> None:
    if _mine_win is None or _mine_body is None or ST.db is None:
        return
    try:
        for w in _mine_body.winfo_children():
            w.destroy()
    except Exception:
        pass
    col = _theme_colours()
    mode = _atlas_mode.get() if _atlas_mode else ATLAS_MODES[0]
    want = _mine_mat.get() if _mine_mat else "(all)"
    choices = dict(_atlas_choices(mode))
    key = choices.get(want)

    with ST.lock:
        if mode == ATLAS_MODES[1]:
            rows = ST.db.find_signals(key, near=ST.cur_pos, limit=100000)
        elif mode == ATLAS_MODES[2]:
            rows = ST.db.find_materials(key, near=ST.cur_pos, limit=100000)
        elif mode == ATLAS_MODES[3]:
            rows = ST.db.find_marks(key, near=ST.cur_pos, limit=100000)
        else:
            rows = ST.db.find_hotspots(key, near=ST.cur_pos, limit=100000)
    max_ly = _atlas_max_ly()
    if max_ly and ST.cur_pos is not None:
        rows = [r for r in rows if r.get("dist") is not None and r["dist"] <= max_ly]
    rows = rows[:40]

    if not rows:
        hint = {ATLAS_MODES[0]: "map a ring with the DSS and its materials land here",
                ATLAS_MODES[1]: "FSS / DSS a body and its signals land here",
                ATLAS_MODES[2]: "pick up a material and where you were lands here",
                ATLAS_MODES[3]: "land, log a codex entry, sample or take a screenshot"}
        max_ly = _atlas_max_ly()
        lbl = tk.Label(_mine_body, anchor=tk.W, font=_MONO,
                       text=("nothing within %.0f ly - pick a larger distance" % max_ly)
                       if max_ly and ST.cur_pos is not None else "nothing yet - " + hint.get(mode, ""))
        lbl.grid(row=0, column=0, sticky=tk.W)
        _apply_theme(lbl, col, is_text=True)
        return

    def dist(h):
        return ("%.0f ly" % h["dist"]) if h.get("dist") is not None else "-"

    if mode == ATLAS_MODES[1]:
        head = "%-26s %-22s %4s  %s" % ("system", "body", "x", "distance")
    elif mode == ATLAS_MODES[2]:
        head = "%-26s %-22s %5s  %-10s %s" % ("system", "where", "got", "last", "distance")
    elif mode == ATLAS_MODES[3]:
        head = "%-26s %-10s %-28s %-17s %s" % ("system", "body", "what", "lat / lon", "distance")
    else:
        head = "%-26s %-26s %3s  %-10s %s" % ("system", "ring", "x", "ring type", "distance")
    h = tk.Label(_mine_body, font=_FONT_GROUP, anchor=tk.W, text=head)
    h.grid(row=0, column=0, sticky=tk.W)
    _apply_theme(h, col, is_text=True)

    for i, r in enumerate(rows, 1):
        sysname = str(r["system"])
        if mode == ATLAS_MODES[1]:
            body = _short_body(r.get("body_name"), sysname) or "(system)"
            text = "%-26s %-22s %4d  %s" % (sysname[:26], body[:22], r["count"] or 1, dist(r))
            if key is None:
                text += "   " + _sig_label({"kind": r["kind"], "label": r["label"]})
        elif mode == ATLAS_MODES[3]:
            body = _short_body(r.get("body_name"), sysname)
            where = ("%+.4f %+.4f" % (r["lat"], r["lon"])) if r.get("lat") is not None else "-"
            text = "%-26s %-10s %-28s %-17s %s" % (
                sysname[:26], body[:10], str(r.get("label") or "")[:28], where, dist(r))
        elif mode == ATLAS_MODES[2]:
            body = _short_body(r.get("body_name"), sysname) or "(in space)"
            text = "%-26s %-22s %5d  %-10s %s" % (
                sysname[:26], body[:22], r["count"], str(r.get("last") or "")[:10], dist(r))
            if key is None:
                text += "   " + str(r.get("label") or r.get("material"))
        else:
            ring = _short_body(r["body"], sysname)
            text = "%-26s %-26s %3d  %-10s %s" % (
                sysname[:26], ring[:26], r["count"], (r["ring_class"] or "")[:10], dist(r))
            if key is None:
                text += "   " + str(r["material"])
        _atlas_row(_mine_body, i, text, sysname, col)

    if _mine_mat:
        cfg_set(CFG[_ATLAS_KEY[mode]], want)


def _toggle_probe_window() -> None:
    global _probe_win
    if _probe_win is not None:
        _probe_window_close()
        return
    _probe_window_open()


def _probe_window_close() -> None:
    """
    Close the probe window and drop the widget references.

    The buttons live inside this window, so once it is destroyed the globals
    point at widgets Tk no longer knows about. Leaving them set makes every
    later _refresh raise `invalid command name ...!button2`, which is exactly
    what the log showed.
    """
    global _probe_win, _btn_prefix, _btn_absent, _btn_boxel, _btn_skip
    if _probe_win is not None:
        try:
            _probe_win.destroy()
        except Exception:
            pass
    _probe_win = None
    _btn_prefix = _btn_bundle = _btn_absent = _btn_boxel = _btn_skip = None
    _refresh()


def _probe_window_open() -> None:
    global _probe_win, _probe_head
    if _frame is None:
        return
    _probe_win = tk.Toplevel(_frame)
    _probe_win.title("SHBOXSEARCH - galaxy map check")
    _probe_win.protocol("WM_DELETE_WINDOW", _probe_window_close)
    try:
        _probe_win.attributes("-topmost", cfg_bool(CFG["route_top"], True))
    except Exception:
        pass
    _probe_head = tk.StringVar(value="")
    tk.Label(_probe_win, textvariable=_probe_head, anchor=tk.W,
             justify=tk.LEFT, font=_MONO).grid(row=0, column=0, sticky=tk.EW,
                                               padx=10, pady=(8, 6))
    bar = tk.Frame(_probe_win)
    bar.grid(row=1, column=0, sticky=tk.EW, padx=10, pady=(0, 4))
    global _btn_prefix, _btn_bundle, _btn_absent, _btn_boxel, _btn_skip
    _btn_prefix = tk.Button(bar, text="copy prefix", command=_copy_prefix)
    _btn_prefix.pack(side=tk.LEFT)
    _btn_bundle = tk.Button(bar, text="copy bundle", command=_copy_bundle)
    _btn_bundle.pack(side=tk.LEFT, padx=(4, 0))
    _btn_absent = tk.Button(bar, text="not there", command=_probe_absent)
    _btn_absent.pack(side=tk.LEFT, padx=(4, 0))
    _btn_boxel = tk.Button(bar, text="boxel done", command=_boxel_done)
    _btn_boxel.pack(side=tk.LEFT, padx=(4, 0))
    _btn_skip = tk.Button(bar, text="later", command=_probe_skip)
    _btn_skip.pack(side=tk.LEFT, padx=(4, 0))

    bar2 = tk.Frame(_probe_win)
    bar2.grid(row=2, column=0, sticky=tk.EW, padx=10, pady=(0, 8))
    tk.Button(bar2, text="replan",
              command=lambda: _run_async(_rebuild_plan, label="replanning")).pack(
        side=tk.LEFT)
    tk.Button(bar2, text="copy route target", command=_copy_route_target).pack(
        side=tk.LEFT, padx=(0, 4))
    tk.Button(bar2, text="copy FC", command=_copy_carrier).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar2, text="carrier spot",
              command=lambda: _run_async(_plan_staging, label="staging")).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Checkbutton(bar2, text="carrier start", variable=_carrier_var,
                   command=_on_carrier_toggle).pack(side=tk.LEFT, padx=(8, 0))

    _probe_window_refresh()
    _theme_tree(_probe_win, _theme_colours())
    _refresh()


def _probe_window_refresh() -> None:
    if _probe_win is None or _probe_head is None:
        return
    p = current_probe()
    if not p:
        _probe_head.set("no candidates to check\n"
                        "press Start to begin a sphere survey")
    else:
        same = sum(1 for q in ST.probe if q.boxel_key == p.boxel_key)
        odds = ("high" if p.score >= 3.0 else "fair" if p.score >= 1.5
                else "low" if p.score > 0 else "void")
        c = ST.plan_counts
        _probe_head.set(
            "check this name in the galaxy map:\n"
            "    %s\n"
            "prefix       %s%s\n"
            "distance     %.1f ly   uncertainty +-%.0f ly\n"
            "this boxel   %d candidate%s   odds %s\n"
            "queue        %d probes (gap %d, probe %d, empty %d)%s"
            % (p.name,
               boxel_prefix(p.boxel_key) if p.boxel_key else "?",
               # n1 = 0 boxels: the prefix also lists the d1-.., d2-.. boxels
               "   (count only names without '-')"
               if p.boxel_key and p.boxel_key[-1:].isalpha() else "",
               p.dist_origin, p.uncertainty,
               same, "" if same == 1 else "s", odds, len(ST.probe),
               c.get(K_GAP, 0), c.get(K_PROBE, 0), c.get(K_EMPTY, 0),
               ("\nplot route   %s  %.0f ly, %d unprobed boxels on the way"
                "\n             (economical route = more hops = more systems)"
                % (ST.route_targets[0]["name"], ST.route_targets[0]["dist"],
                   ST.route_targets[0]["boxels"])) if ST.route_targets else ""))


def _on_carrier_toggle() -> None:
    cfg_set(CFG["carrier_start"], bool(_carrier_var.get()))
    _refresh()


def _copy_flight_click() -> None:
    t = current_flight()
    if t:
        _copy(t.name)


def _on_start() -> None:
    if ST.active:
        _stop_survey()
    else:
        _start_survey()


def _refresh() -> None:
    if not _frame:
        return
    try:
        t = current_flight()
        if t:
            _v_target.set("%s   %.1f ly" % (t.name, t.dist_origin))
            _v_kind.set("%s %s" % (KIND_SHORT.get(t.kind, t.kind),
                                   t.detail or LABEL.get(t.kind, "")))
        else:
            _v_target.set("-")
            _v_kind.set("no flight targets left" if ST.active else "survey inactive")

        _probe_window_refresh()

        p = current_probe()
        if p:
            same = sum(1 for q in ST.probe if q.boxel_key == p.boxel_key)
            hint = "  odds %s" % ("high" if p.score >= 3.0
                                  else "fair" if p.score >= 1.5
                                  else "low" if p.score > 0 else "void")
            _v_probe.set("%s   %.1f ly  +-%.0f   [%d in boxel]%s"
                         % (p.name, p.dist_origin, p.uncertainty, same, hint))
        else:
            _v_probe.set("-")

        if ST.cur_system:
            line = ST.cur_system
            if ST.cur_id64 and ST.db:
                with ST.lock:
                    pr = ST.db.system_progress(ST.cur_id64, CURRENT)
                bits = []
                if pr["body_count"]:
                    bits.append("FSS %d/%d" % (pr["scanned"], pr["body_count"]))
                if pr["dss_open"]:
                    bits.append("DSS %d" % len(pr["dss_open"]))
                if pr["bio_open"]:
                    # M1: open signals and where - finished bodies drop out
                    short = [shorten(n, ST.cur_system) for n in pr["bio_open"]]
                    bits.append("Bio %d open (%s%s)" % (
                        pr.get("bio_signals_open") or len(short), ", ".join(short[:3]),
                        ", ..." if len(short) > 3 else ""))
                if pr["new_discoveries"]:
                    bits.append("first %d" % pr["new_discoveries"])
                if bits:
                    line += "   " + " | ".join(bits)
            _v_sys.set(line)
        else:
            _v_sys.set("-")

        if ST.active:
            c = ST.plan_counts
            _v_queue.set("r=%.0f ly | fly %d (new %d, tasks %d) | probes %d "
                         "(gap %d, probe %d, empty %d)"
                         % (ST.radius, len(ST.flight), c.get(K_NEW, 0),
                            c.get(K_SCAN, 0) + c.get(K_DSS, 0) + c.get(K_BIO, 0),
                            len(ST.probe), c.get(K_GAP, 0), c.get(K_PROBE, 0),
                            c.get(K_EMPTY, 0)))
        else:
            if _carrier_var and _carrier_var.get() and ST.carrier:
                _v_queue.set("Start centres the sphere on the carrier at %s"
                             % ST.carrier["system"])
            else:
                _v_queue.set("Start sets the sphere centre to your current position")

        # Fuel: the warning always shows, the full line only if switched on.
        warn = ST.fuel.warning()
        if _v_fuel is not None:
            if warn:
                _v_fuel.set(warn)
            elif cfg_bool(CFG["panel_fuel"], False):
                _v_fuel.set(ST.fuel.summary())
            else:
                _v_fuel.set("")
        if _lbl_fuel is not None:
            (_lbl_fuel.grid() if (warn or cfg_bool(CFG["panel_fuel"], False))
             else _lbl_fuel.grid_remove())

        # one compact line here; the full list lives in the route window
        if cfg_bool(CFG["show_route"], True) and ST.route and ST.route.stops:
            open_stops = [x for x in ST.route.stops
                          if x.body.body_id not in ST.route_done]
            nxt = open_stops[0].body.short if open_stops else "-"
            _v_route.set("in-system%s: %d/%d left, %.0f min | next %s"
                         % (" (all done)" if ST.route_full else "",
                            len(open_stops), len(ST.route.stops),
                            sum(x.leg_s for x in open_stops) / 60.0, nxt))
            if _lbl_route:
                _lbl_route.grid()
        elif cfg_bool(CFG["show_route"], True) and ST.cur_id64:
            _v_route.set("in-system: nothing to fly here")
            if _lbl_route:
                _lbl_route.grid()
        else:
            _v_route.set("")
            if _lbl_route:
                _lbl_route.grid_remove()

        if _v_update is not None and _lbl_update is not None:
            if ST.update_version:
                _v_update.set("update %s available - click to open GitHub"
                              % ST.update_version)
                _lbl_update.grid()
            else:
                _v_update.set("")
                _lbl_update.grid_remove()

        if _lbl_queue is not None:
            (_lbl_queue.grid() if cfg_bool(CFG["panel_queue"], False)
             else _lbl_queue.grid_remove())

        # The statistics block is gone from the panel - it is 12 lines in a
        # window shared with every other plugin. The info window holds it all.
        if _v_stats is not None:
            _v_stats.set("")
        if _lbl_stats is not None:
            _lbl_stats.grid_remove()

        if _btn_start:
            _btn_start.config(text="Stop" if ST.active else "Start")
        if _btn_fc:
            _btn_fc.config(state=tk.NORMAL if ST.carrier else tk.DISABLED)
        # These live in the probe window and vanish when it closes.
        state = tk.NORMAL if (ST.active and ST.probe) else tk.DISABLED
        for b in (_btn_absent, _btn_skip, _btn_boxel, _btn_prefix, _btn_bundle):
            if b is None:
                continue
            try:
                b.config(state=state)
            except tk.TclError:
                pass
        if _btn_next:
            _btn_next.config(state=tk.NORMAL if ST.flight else tk.DISABLED)
        if _btn_route:
            _btn_route.config(text="route x" if _route_win is not None else "route")
        if _btn_stats:
            _btn_stats.config(text="info x" if _stats_win is not None else "info")
    except Exception:
        logger.exception("UI refresh failed")


# ============================================================================
# Preferences
# ============================================================================

_p: Dict[str, Any] = {}


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> Optional[nb.Frame]:
    """
    Preferences, laid out in two columns.

    Everything is grid() - EDMC's notebook frames already use the grid
    manager, and mixing in pack() raises TclError. The two columns exist
    because a single stack of every option runs off the bottom of the window
    on a 1080p screen.
    """
    f = nb.Frame(parent)
    f.columnconfigure(0, weight=1, uniform="cols")
    f.columnconfigure(1, weight=1, uniform="cols")

    nb.Label(f, text="SHBOXSEARCH v%s" % VERSION).grid(
        row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 4))

    left = nb.Frame(f)
    left.grid(row=1, column=0, sticky=tk.NW, padx=(0, 14))
    right = nb.Frame(f)
    right.grid(row=1, column=1, sticky=tk.NW)

    state = {"left": 0, "right": 0}

    def head(parent_frame, side: str, text: str) -> None:
        nb.Label(parent_frame, text=text).grid(
            row=state[side], column=0, columnspan=4, sticky=tk.W,
            pady=(10 if state[side] else 0, 2))
        state[side] += 1

    def field(parent_frame, side: str, label: str, widget) -> None:
        if label:
            nb.Label(parent_frame, text=label).grid(
                row=state[side], column=0, sticky=tk.W, padx=(12, 6))
            widget.grid(row=state[side], column=1, columnspan=3, sticky=tk.W)
        else:
            widget.grid(row=state[side], column=0, columnspan=4, sticky=tk.W,
                        padx=(12, 0))
        state[side] += 1

    def note(parent_frame, side: str, text: str) -> None:
        nb.Label(parent_frame, text=text).grid(
            row=state[side], column=0, columnspan=4, sticky=tk.W, padx=(12, 0))
        state[side] += 1

    # ======================= left column: the survey =======================
    head(left, "left", "Sphere")

    _p["radius"] = tk.StringVar(value=str(cfg_int(CFG["radius"], 50)))
    field(left, "left", "Radius (ly)",
          ttk.OptionMenu(left, _p["radius"], _p["radius"].get(), *RADIUS_CHOICES))

    nb.Label(left, text="Mass codes").grid(row=state["left"], column=0,
                                           sticky=tk.W, padx=(12, 6))
    mcf = nb.Frame(left)
    mcf.grid(row=state["left"], column=1, columnspan=3, sticky=tk.W)
    _p["mc"] = {}
    active_mc = set(get_masscodes())
    for i in range(8):
        v = tk.IntVar(value=1 if i in active_mc else 0)
        _p["mc"][i] = v
        nb.Checkbutton(mcf, text=MASSCODES[i], variable=v).grid(
            row=0, column=i, sticky=tk.W)
    state["left"] += 1

    _p["probe"] = tk.StringVar(value=str(cfg_int(CFG["probe_depth"], 2)))
    field(left, "left", "Probes above max",
          nb.EntryMenu(left, textvariable=_p["probe"], width=5))

    _p["empty"] = tk.IntVar(value=1 if cfg_bool(CFG["include_empty"], True) else 0)
    field(left, "left", "", nb.Checkbutton(
        left, text="probe unexplored boxels", variable=_p["empty"]))

    _p["tasks"] = tk.IntVar(value=1 if cfg_bool(CFG["include_tasks"], True) else 0)
    field(left, "left", "", nb.Checkbutton(
        left, text="queue outstanding scans", variable=_p["tasks"]))

    _p["carrier_start"] = tk.IntVar(
        value=1 if cfg_bool(CFG["carrier_start"], False) else 0)
    field(left, "left", "", nb.Checkbutton(
        left, text="carrier start (centre on the carrier)",
        variable=_p["carrier_start"]))

    head(left, "left", "What counts as needing a visit")
    note(left, "left", "Any ticked reason is enough.")
    active_f = set(get_filters())
    _p["filters"] = {}
    for key in ALL_FILTERS:
        v = tk.IntVar(value=1 if key in active_f else 0)
        _p["filters"][key] = v
        field(left, "left", "", nb.Checkbutton(
            left, text=FILTER_LABEL[key], variable=v))

    # ================= right column: sources, display, tools ===============
    head(right, "right", "Data sources")

    _p["edd"] = tk.IntVar(value=1 if cfg_bool(CFG["src_edd"], True) else 0)
    _p["spansh"] = tk.IntVar(value=1 if cfg_bool(CFG["src_spansh"], True) else 0)
    _p["edsm"] = tk.IntVar(value=1 if cfg_bool(CFG["src_edsm"], True) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="EDDiscovery (local)", variable=_p["edd"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="Spansh", variable=_p["spansh"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="EDSM", variable=_p["edsm"]))
    _p["offline"] = tk.IntVar(value=1 if cfg_bool(CFG["offline"], False) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="offline - no online requests at all (EDSM, Spansh, "
                    "update check)", variable=_p["offline"]))

    _p["eddpath"] = tk.StringVar(value=cfg_str(CFG["edd_path"]))
    nb.Label(right, text="EDDSystem.sqlite").grid(
        row=state["right"], column=0, sticky=tk.W, padx=(12, 6))
    nb.EntryMenu(right, textvariable=_p["eddpath"], width=30).grid(
        row=state["right"], column=1, columnspan=2, sticky=tk.W)
    tk.Button(right, text="...", width=3, command=_pick_edd).grid(
        row=state["right"], column=3, sticky=tk.W, padx=4)
    state["right"] += 1

    for name, ok, why in ST.sources.status():
        note(right, "right", "  %-12s %-4s %s" % (name, "ok" if ok else "no",
                                                  why[:40]))

    head(right, "right", "Harvesting")
    _p["navroute"] = tk.IntVar(value=1 if cfg_bool(CFG["harvest_navroute"], True) else 0)
    _p["dest"] = tk.IntVar(value=1 if cfg_bool(CFG["harvest_destination"], True) else 0)
    _p["autocopy"] = tk.IntVar(value=1 if cfg_bool(CFG["autocopy"], True) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="read NavRoute", variable=_p["navroute"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="read target selection", variable=_p["dest"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="copy next target to clipboard", variable=_p["autocopy"]))

    head(right, "right", "Windows")
    _p["route_top"] = tk.IntVar(value=1 if cfg_bool(CFG["route_top"], True) else 0)
    _p["route_map"] = tk.IntVar(value=1 if cfg_bool(CFG["route_map"], True) else 0)
    _p["route_all"] = tk.IntVar(value=1 if cfg_bool(CFG["route_all"], False) else 0)
    _p["route_arrival"] = tk.IntVar(value=1 if cfg_bool(CFG["route_arrival"], True) else 0)
    _p["show_route"] = tk.IntVar(value=1 if cfg_bool(CFG["show_route"], True) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="keep windows on top", variable=_p["route_top"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="draw the system map", variable=_p["route_map"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="route every body", variable=_p["route_all"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="start the route at the arrival star", variable=_p["route_arrival"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="show the route line in the panel", variable=_p["show_route"]))

    # C1: more than one commander on this PC
    choices = _main_cmdr_choices()
    if len(choices) > 1:
        head(right, "right", "Commanders")
        labels = [c[0] for c in choices]
        cur = cfg_str(CFG["main_cmdr"], "")
        sel = next((c[0] for c in choices if c[1] == cur), labels[0])
        _p["main_cmdr"] = tk.StringVar(value=sel)
        _p["main_cmdr_map"] = {c[0]: c[1] for c in choices}
        field(right, "right", "Main commander",
              ttk.OptionMenu(right, _p["main_cmdr"], sel, *labels))
        note(right, "right", "survey plan and statistics; each commander's own")
        note(right, "right", "visits and scans are kept apart, finds are shared")

    head(right, "right", "Cockpit overlay (needs EDMCModernOverlay)")
    _p["overlay"] = tk.IntVar(value=1 if cfg_bool(CFG["overlay"], True) else 0)
    _p["overlay_brief"] = tk.IntVar(value=1 if cfg_bool(CFG["overlay_brief"], True) else 0)
    _p["overlay_pos"] = tk.StringVar(value=cfg_str(CFG["overlay_pos"], "top-left"))
    _p["overlay_nav"] = tk.IntVar(value=1 if cfg_bool(CFG["overlay_nav"], True) else 0)
    _p["overlay_mining"] = tk.IntVar(value=1 if cfg_bool(CFG["overlay_mining"], True) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="show the next route targets in the game", variable=_p["overlay"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="briefing on target selection and arrival",
        variable=_p["overlay_brief"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="surface compass: parked SRV, open samples, known points",
        variable=_p["overlay_nav"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="mining: last rock, hold, rate, session, limpets (5 lines)",
        variable=_p["overlay_mining"]))
    field(right, "right", "Position",
          ttk.OptionMenu(right, _p["overlay_pos"], _p["overlay_pos"].get(),
                         *OVERLAY_POSITIONS))
    ov = getattr(ST, "overlay", None)
    note(right, "right", "  overlay: %s" % (
        "connected" if ov is not None and ov.available() else "not installed"))

    head(right, "right", "SHBOX FIS - flight information system")
    fis_row = tk.Frame(right)
    tk.Button(fis_row, text="start FIS", command=_fis_start).pack(side=tk.LEFT)
    tk.Button(fis_row, text="open in browser", command=_fis_open).pack(side=tk.LEFT, padx=(6, 0))
    fis_state = tk.StringVar(value=_fis_status())
    tk.Button(fis_row, text="check", command=lambda: fis_state.set(_fis_status())).pack(
        side=tk.LEFT, padx=(6, 0))
    field(right, "right", "", fis_row)
    _p["fis_autostart"] = tk.IntVar(value=1 if cfg_bool(CFG["fis_autostart"], False) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="start the FIS together with EDMC (window minimised)",
        variable=_p["fis_autostart"]))
    nb.Label(right, textvariable=fis_state).grid(
        row=state["right"], column=0, columnspan=4, sticky=tk.W, padx=(12, 0))
    state["right"] += 1
    note(right, "right", "  or double-click FIS\\start_fis.bat - first start asks, then remembers;")
    note(right, "right", "  change it later with FIS\\fis_settings.bat. Details: FIS\\README.md")

    _p["panel_fuel"] = tk.IntVar(value=1 if cfg_bool(CFG["panel_fuel"], False) else 0)
    _p["check_updates"] = tk.IntVar(
        value=1 if cfg_bool(CFG["check_updates"], True) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="check GitHub for a newer release (once a day, notify only)",
        variable=_p["check_updates"]))

    _p["panel_queue"] = tk.IntVar(value=1 if cfg_bool(CFG["panel_queue"], False) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="show fuel in the panel (warnings always show)",
        variable=_p["panel_fuel"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="show queue counters in the panel", variable=_p["panel_queue"]))

    _p["map_size"] = tk.StringVar(value=cfg_str(CFG["map_size"], "medium"))
    field(right, "right", "Map size",
          ttk.OptionMenu(right, _p["map_size"], _p["map_size"].get(),
                         "small", "medium", "large"))

    _p["jump"] = tk.StringVar(value=str(cfg_int(CFG["jump_range"], 0) or ""))
    field(right, "right", "Jump range (0=auto)",
          nb.EntryMenu(right, textvariable=_p["jump"], width=6))

    # ========================= full width: tools ===========================
    tools = nb.Frame(f)
    tools.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(12, 0))
    nb.Label(tools, text="Maintenance").grid(row=0, column=0, columnspan=6,
                                             sticky=tk.W)
    buttons = [
        ("Run first import", lambda: _run_async(_first_run_migration,
                                                label="first-run import")),
        ("Replay journals", lambda: _run_async(_import_journals, label="journals")),
        ("Import JSON", lambda: _run_async(_import_json, label="JSON import")),
        ("Export plan (CSV)", _export_csv),
        ("Boxel prefixes", _export_prefixes),
        ("Self test", lambda: _run_async(_selftest, label="self test")),
        ("Check for update",
         lambda: _run_async(_check_for_update, True, label="update check")),
    ]
    for i, (text, cmd) in enumerate(buttons):
        tk.Button(tools, text=text, command=cmd).grid(
            row=1 + i // 3, column=i % 3, sticky=tk.W, padx=(0, 6), pady=2)

    info = nb.Frame(f)
    info.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
    jd = _journal_dir()
    car = ST.db.get_carrier() if ST.db else None
    lines = [
        "Version %s  -  %s" % (VERSION, REPO_URL),
        "Journal folder: %s" % (jd or "NOT FOUND"),
        "First import: %s" % ((ST.db.get_meta("migrated") if ST.db else None)
                              or "not run yet"),
        "Carrier: %s" % ("%s%s" % (car["system"],
                                   "  (%s)" % car["callsign"]
                                   if car.get("callsign") else "")
                         if car else "not known yet - dock at it once"),
    ]
    for i, line in enumerate(lines):
        nb.Label(info, text=line).grid(row=i, column=0, sticky=tk.W)

    _p["debug"] = tk.IntVar(value=1 if cfg_bool(CFG["debug"], False) else 0)
    nb.Checkbutton(f, text="verbose logging", variable=_p["debug"]).grid(
        row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
    return f


def _pick_edd() -> None:
    p = filedialog.askopenfilename(
        title="Select EDDSystem.sqlite",
        filetypes=[("SQLite database", "*.sqlite"), ("All files", "*.*")])
    if p:
        _p["eddpath"].set(p)


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    try:
        cfg_set(CFG["radius"], int(_p["radius"].get()))
        cfg_set(CFG["masscodes"], ",".join(str(i) for i, v in _p["mc"].items() if v.get()))
        cfg_set(CFG["probe_depth"], int(_p["probe"].get() or 2))
        cfg_set(CFG["include_empty"], bool(_p["empty"].get()))
        cfg_set(CFG["include_tasks"], bool(_p["tasks"].get()))
        cfg_set(CFG["jump_range"], int(float(_p["jump"].get() or 0)))
        cfg_set(CFG["src_edd"], bool(_p["edd"].get()))
        cfg_set(CFG["src_spansh"], bool(_p["spansh"].get()))
        cfg_set(CFG["src_edsm"], bool(_p["edsm"].get()))
        cfg_set(CFG["offline"], bool(_p["offline"].get()))
        ST.net.offline = bool(_p["offline"].get())
        cfg_set(CFG["edd_path"], _p["eddpath"].get())
        cfg_set(CFG["harvest_navroute"], bool(_p["navroute"].get()))
        cfg_set(CFG["harvest_destination"], bool(_p["dest"].get()))
        cfg_set(CFG["autocopy"], bool(_p["autocopy"].get()))
        cfg_set(CFG["carrier_start"], bool(_p["carrier_start"].get()))
        cfg_set(CFG["show_route"], bool(_p["show_route"].get()))
        cfg_set(CFG["route_all"], bool(_p["route_all"].get()))
        cfg_set(CFG["route_arrival"], bool(_p["route_arrival"].get()))
        if "main_cmdr" in _p:
            cfg_set(CFG["main_cmdr"], _p["main_cmdr_map"].get(_p["main_cmdr"].get(), ""))
            _apply_main_cmdr()
        cfg_set(CFG["route_top"], bool(_p["route_top"].get()))
        cfg_set(CFG["route_map"], bool(_p["route_map"].get()))
        cfg_set(CFG["map_size"], _p["map_size"].get())
        cfg_set(CFG["panel_fuel"], bool(_p["panel_fuel"].get()))
        cfg_set(CFG["panel_queue"], bool(_p["panel_queue"].get()))
        cfg_set(CFG["check_updates"], bool(_p["check_updates"].get()))
        cfg_set(CFG["overlay"], bool(_p["overlay"].get()))
        cfg_set(CFG["overlay_brief"], bool(_p["overlay_brief"].get()))
        cfg_set(CFG["overlay_nav"], bool(_p["overlay_nav"].get()))
        cfg_set(CFG["overlay_mining"], bool(_p["overlay_mining"].get()))
        if "fis_autostart" in _p:
            cfg_set(CFG["fis_autostart"], bool(_p["fis_autostart"].get()))
        cfg_set(CFG["overlay_pos"], _p["overlay_pos"].get())
        _overlay_apply_settings()
        _overlay_targets()
        global _MAP_W, _MAP_H
        _MAP_W = _MAP_H = _MAP_SIZES.get(_p["map_size"].get(), 480)
        picked = [k for k, v in _p.get("filters", {}).items() if v.get()]
        cfg_set(CFG["filters"], ",".join(picked) if picked else F_OUTSTANDING)
        _request_route(delay=0.2)
        if _carrier_var:
            _carrier_var.set(_p["carrier_start"].get())
        cfg_set(CFG["debug"], bool(_p["debug"].get()))
        logger.setLevel(logging.DEBUG if _p["debug"].get() else logging.INFO)
        ST.sources = SourceManager(_p["eddpath"].get() or None, gateway=ST.net)
        if _radius_var:
            _radius_var.set(_p["radius"].get())
        if ST.active:
            _run_async(_rebuild_plan, label="Plan")
    except Exception:
        logger.exception("could not save settings")


# ============================================================================
# Maintenance
# ============================================================================

def _journal_dir() -> Optional[str]:
    """Journal folder: EDMC's own setting first, then the default paths."""
    for getter in ("get_str", "get"):
        try:
            v = getattr(config, getter)("journaldir")
            if v and os.path.isdir(v):
                return v
        except Exception:
            pass
    for attr in ("default_journal_dir", "default_journal_dir_path"):
        try:
            v = getattr(config, attr, None)
            if callable(v):
                v = v()
            if v and os.path.isdir(str(v)):
                return str(v)
        except Exception:
            pass
    for p in (r"%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous",
              r"%HOMEPATH%\Saved Games\Frontier Developments\Elite Dangerous"):
        q = os.path.expandvars(p)
        if os.path.isdir(q):
            return q
    return None


def _import_journals(max_files: int = 0) -> None:
    d = _journal_dir()
    if not d:
        _set_status("journal folder not found")
        logger.warning("journal folder not found")
        return

    def prog(i, total, fn):
        _set_status("journals %d/%d" % (i, total))

    # the lock is taken per chunk inside, never for the whole replay
    res = ST.db.import_journals(d, max_files=max_files, progress=prog, lock=ST.lock)
    logger.info("journals replayed: %s", res)
    _set_status("journals: %d files, %d lines, %d events"
                % (res["files"], res["lines"], res["events"]))
    if ST.active:
        _rebuild_plan()


def _first_run_migration() -> None:
    """
    Runs once on first start. Replaces calling migrate.py, so no system-wide
    Python installation is needed - EDMC ships its own interpreter.
    """
    logger.info("first-run import starting")
    _set_status("first-run import: JSON")
    _import_json()
    _set_status("first-run import: journals")
    _import_journals()
    with ST.lock:
        st = ST.db.stats()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ST.db.set_meta("migrated", now)
        for t in REPLAY_TAGS:                 # a fresh import already has it all
            ST.db.set_meta(t, now)
    logger.info("first-run import finished: %s", st)
    _apply_main_cmdr()
    _rebuild_route()
    _set_status("first-run import done: %d systems, %d bodies"
                % (st["systems"], st["bodies"]))


# Releases that need one full journal replay to fill what they store new.
# upgrade_44b: barycentre parents (binary moons placed far from their planet)
# upgrade_46_rigs: Rhino rig collection points from MiningRefined + the track
# upgrade_48_cmdr (C1): exploration per commander - visited, FSS, scans,
# maps, first discoveries and species analysed sorted by FID
# upgrade_48_lost: what each commander carries unsold, and what a lost ship
# took with it (marked, planned again)
REPLAY_TAGS = ("upgrade_41", "upgrade_43", "upgrade_44", "upgrade_44b",
               "upgrade_46_rigs", CMDR_READY, LOSS_REPLAY)


def _upgrade_replay() -> None:
    """
    One full journal replay after an update that stores something new.

    4.3: the signal atlas (planetary mining locations, geological and
    biological signals, genera incl. Brain Trees, codex sites) and the
    material atlas (where each material was picked up).

    4.1:
    * fills the new per-body columns (gravity, temperature, atmosphere,
      volcanism, materials, radius, rings ...) from the existing history
    * corrects the bio sample counter: up to 4.0 every replay - including
      the automatic one behind the route window - added +1 per sample again,
      so bodies looked sampled when they were not. It is now written as the
      number of distinct species analysed, so this replay sets it right.
    """
    # let EDMC finish its own start-up (journal monitor, commander, cAPI) first
    time.sleep(15)
    todo = [t for t in REPLAY_TAGS if not ST.db.get_meta(t)]
    logger.info("upgrade (%s): replaying all journals once to fill new data",
                ", ".join(todo))
    _set_status("upgrade: journals")
    _import_journals()
    with ST.lock:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for t in todo:
            ST.db.set_meta(t, now)
        n_sig = len(ST.db.signal_kinds())
        n_mat = len(ST.db.material_kinds())
        n_cmdr = len(ST.db.commanders())
    logger.info("upgrade finished - atlas: %d signal kinds, %d materials, "
                "%d commanders", n_sig, n_mat, n_cmdr)
    _apply_main_cmdr()
    _rebuild_route()


def _selftest() -> None:
    """Verify the procgen maths. Result goes to the EDMC log."""
    import io
    import contextlib
    import procgen
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fails = procgen._selftest()
    for line in buf.getvalue().splitlines():
        logger.info("selftest | %s", line)
    with ST.lock:
        st = ST.db.stats()
    logger.info("selftest | database: %s", st)
    _set_status("self test: %s (details in log)"
                % ("passed" if fails == 0 else "%d failures" % fails))


def _import_json() -> None:
    ok_total = 0
    for fn, fn2 in (("neareststars.json", "import_neareststars"),
                    ("survey_state.json", "import_survey_state")):
        p = os.path.join(_PLUGIN_DIR, fn)
        if os.path.exists(p):
            with ST.lock:
                a, b = getattr(ST.db, fn2)(p)
            ok_total += a
            logger.info("%s -> %d / %d", fn, a, b)
    _set_status("JSON import: %d records" % ok_total)


def _export_csv() -> None:
    if not (ST.center and ST.planner):
        _set_status("no active survey")
        return
    p = filedialog.asksaveasfilename(defaultextension=".csv",
                                     initialfile="shboxsearch_plan.csv")
    if not p:
        return
    with ST.lock:
        plan = ST.planner.build(ST.center, _plan_radius(), masscodes=get_masscodes(),
                                probe_depth=cfg_int(CFG["probe_depth"], 2),
                                include_empty=cfg_bool(CFG["include_empty"], True))
    n = Planner.export_csv(plan, p)
    _set_status("%d targets written to %s" % (n, os.path.basename(p)))


def _export_prefixes() -> None:
    if not (ST.center and ST.planner):
        _set_status("no active survey")
        return
    p = filedialog.asksaveasfilename(defaultextension=".txt",
                                     initialfile="boxel_praefixe.txt")
    if not p:
        return
    with ST.lock:
        plan = ST.planner.build(ST.center, _plan_radius(), masscodes=get_masscodes(),
                                probe_depth=cfg_int(CFG["probe_depth"], 2),
                                include_empty=cfg_bool(CFG["include_empty"], True))
    rows = Planner.boxel_prefixes(plan, limit=100000)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# One prefix per boxel. Paste into the galaxy map search;\n"
                "# the result list shows every system of that boxel.\n")
        for pref, d, n in rows:
            f.write("%-32s  %7.1f ly  open %d\n" % (pref, d, n))
    _set_status("%d prefixes written to %s" % (len(rows), os.path.basename(p)))
