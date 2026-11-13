# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SHBOXSEARCH - systematic sphere survey for Elite Dangerous
==========================================================
EDMC plugin. Goal: fully explore and chart a radius around a start point,
deliberately hunting for systems that appear in no database at all.

This file is the thin layer EDMC talks to: the lifecycle hooks
(``plugin_start3``, ``plugin_stop``, ``capi_fleetcarrier``) and the hooks
implemented elsewhere, re-exported here:

* ``plugin_app``                    -> panel.py
* ``journal_entry``, ``dashboard_entry`` -> journal.py
* ``plugin_prefs``, ``prefs_changed``    -> prefs.py

The other modules: state.py (shared state, settings), uithread.py (Tk
hand-over from threads), planning.py, survey.py, cockpit.py, routewin.py,
statswin.py, probewin.py, miningwin.py, skin.py, updater.py, fislaunch.py,
maintenance.py; and the helpers procgen, sysdb, sources, netgate, shells,
boxelplan, sysroute, deepspace, overlay, biopredict, surfacenav,
miningstat, journalscan.

Documentation: see README.md in the plugin folder.
Tested against EDMC 6.1.2 / Python 3.13.
Licence: MPL-2.0 (see LICENSE); 4.6 and earlier were released under MIT.
"""

from __future__ import annotations

import os
import sys

if not __package__:
    # EDMC imports a plugin as "<folder>.load". When the folder name is no
    # valid Python name (say "SHBOXSEARCH-main") it falls back to loading
    # this file by path, without a package - and the relative imports below
    # would fail. Register the folder as a package of its own then.
    import importlib.machinery
    import importlib.util
    _PKG = "shboxsearch_plugin"
    if _PKG not in sys.modules:
        _spec = importlib.machinery.ModuleSpec(_PKG, None, is_package=True)
        _spec.submodule_search_locations = [os.path.dirname(os.path.abspath(__file__))]
        sys.modules[_PKG] = importlib.util.module_from_spec(_spec)
    __package__ = _PKG

import json  # noqa: E402
import time  # noqa: E402
from typing import Any, Optional  # noqa: E402

from .boxelplan import Planner  # noqa: E402
from .overlay import CockpitOverlay  # noqa: E402
from .sources import SourceManager  # noqa: E402
from .sysdb import SystemDB  # noqa: E402
from .state import CFG, DB_FILE, ST, VERSION, _PLUGIN_DIR, cfg_bool, cfg_str, logger  # noqa: E402
from . import cockpit  # noqa: E402
from . import maintenance  # noqa: E402
from . import miningwin  # noqa: E402
from . import planning  # noqa: E402
from . import probewin  # noqa: E402
from . import routewin  # noqa: E402
from . import statswin  # noqa: E402
from . import survey  # noqa: E402
from . import uithread  # noqa: E402

# EDMC hooks implemented in their own modules
from .journal import dashboard_entry, journal_entry  # noqa: E402,F401
from .panel import plugin_app  # noqa: E402,F401
from .prefs import plugin_prefs, prefs_changed  # noqa: E402,F401


# ============================================================================
# EDMC lifecycle
# ============================================================================

def plugin_start3(plugin_dir: str) -> str:
    """
    EDMC hook: load the plugin. Opens the database and starts the journal
    reading in worker threads; returns the name shown in EDMC.
    """
    logger.info("SHBOXSEARCH v%s starting", VERSION)
    routewin._MAP_W = routewin._MAP_H = routewin._MAP_SIZES.get(cfg_str(CFG["map_size"], "medium"), 480)
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
    cockpit._overlay_apply_settings()

    if not ST.db.get_meta("migrated"):
        uithread._run_async(maintenance._first_run_migration, label="first-run import")
    elif any(not ST.db.get_meta(t) for t in maintenance.REPLAY_TAGS):
        uithread._run_async(maintenance._upgrade_replay, label="upgrade")

    planning._apply_main_cmdr()
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
        uithread._run_async(planning._resume_worker, label="loading plan")
    # These read the journals to establish fuel, the work-time model and where
    # we last were. Without them the panel shows "fuel: unknown" and the map
    # has no "last here" marker until the first jump of the session.
    uithread._run_async(survey._bootstrap_session, label="reading journals")
    planning._request_route(delay=2.5)
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
    """
    EDMC hook: EDMC is closing. Clears the overlay, closes the windows, stops
    the gateway (no more requests), waits up to 2 s for running work, stores
    the call log, closes the database.
    """
    ov = getattr(ST, "overlay", None)
    if ov is not None:
        ov.clear()
    routewin._route_window_close()
    statswin._stats_window_close()
    probewin._probe_window_close()
    miningwin._mining_window_close()
    ST.net.stop()             # wake a waiting request; nothing more is sent
    # N8: let running work finish before the database closes - briefly
    busy = uithread._join_workers(2.0)
    if busy:
        logger.info("stop: still running after 2 s, left to end with EDMC: %s", ", ".join(busy))
    planning._flush_net_log()
    with ST.lock:
        if ST.db:
            ST.db.close()
    logger.info("SHBOXSEARCH stopped")
