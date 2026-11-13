# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The plugin's shared state and settings.

Everything the other modules share lives here: the version, the settings
keys (all ``shboxsearch_*`` in EDMC's config), the one ``State`` object
``ST`` (database, planner, survey, position, route, timing) and the small
config helpers. This module imports no sibling module, so every other
module can import it first.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

# EDMC API
from config import appname, config

from . import journalscan
from . import miningstat
from . import netgate
from . import overlay as _overlay_mod
from . import sources as _sources_mod
from . import sysdb as _sysdb_mod
from .boxelplan import K_BIO, K_CHECK, K_DSS, K_EMPTY, K_GAP, K_NEW, K_PROBE, K_SCAN, Planner, Target
from .deepspace import FuelState
from .netgate import Gateway
from .sources import SourceManager
from .sysdb import SystemDB
from .sysroute import ALL_FILTERS, DEFAULT_MODEL, F_OUTSTANDING

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

VERSION = "4.11.0"
PLUGIN_NAME = os.path.basename(_PLUGIN_DIR)
logger = logging.getLogger("%s.%s" % (appname, PLUGIN_NAME))
for _mod in (_sysdb_mod, _sources_mod, netgate, _overlay_mod):
    _mod.logger = logger

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


def _edmc_user_agent() -> str:
    """EDMC's own User-Agent (config.user_agent), which PLUGINS.md asks
    plugins to send, with ours appended by netgate. Empty on EDMC builds
    without it."""
    ua = getattr(config, "user_agent", "")
    return ua if isinstance(ua, str) else ""


# ============================================================================
# State
# ============================================================================

class State:
    def __init__(self):
        self.db: Optional[SystemDB] = None
        self.lock = threading.RLock()
        # the plugin's one door to the internet - created once, so pacing
        # and rests survive a rebuilt SourceManager
        self.net = Gateway(VERSION, base_ua=_edmc_user_agent())
        self.sources = SourceManager(gateway=self.net)
        # local-first (shells.py): how far out the online sources have been
        # asked for the running survey; the planner plans only inside it
        self.horizon = 0.0
        self.fetch_lock = threading.Lock()
        self.extending = False
        # EDDiscovery's file was busy (EDD running) - read it again later
        self.edd_pending = False
        self.edd_next_try = 0.0
        # 4.10: probe candidates already looked up in EDD's file by id64
        self.edd_asked: Set[int] = set()
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
        self.work_meter = journalscan.WorkMeter()   # live DSS / sampling timing
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


# ============================================================================
# Config helpers (EDMC's config API, 5.0 and newer)
# ============================================================================

def cfg_bool(key: str, default: bool) -> bool:
    """A plugin setting through EDMC's config API (5.0+), with its default."""
    # The default has to go to EDMC itself: since EDMC 6 (config.toml) a key
    # that was never saved reads as False, not None, so a "True" default
    # applied afterwards never took effect. Up to 4.2.0 that silently
    # switched off the update check and the overlay for everyone who had not
    # opened and saved the preferences since those options existed.
    try:
        v = config.get_bool(key, default=default)
    except Exception:
        return default
    return default if v is None else bool(v)


def cfg_int(key: str, default: int) -> int:
    """A whole-number setting; a stored 0 counts as unset when there is a default."""
    try:
        v = config.get_int(key, default=default)
    except Exception:
        return default
    return default if v in (None, 0) and default else (default if v is None else int(v))


def cfg_str(key: str, default: str = "") -> str:
    """A text setting; empty counts as unset."""
    try:
        v = config.get_str(key, default=default)
    except Exception:
        return default
    return default if v in (None, "") else str(v)


def cfg_set(key: str, value) -> None:
    try:
        config.set(key, value)
    except Exception as e:
        logger.warning("config.set(%s) failed: %s", key, e)


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
