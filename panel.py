# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The plugin's panel in EDMC's main window.

Builds the panel (``plugin_app``), holds its widgets and redraws it in
``_refresh``. Status lines go through ``_set_status``. Runs on the main
thread only.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

# EDMC API
from theme import theme

from .boxelplan import K_BIO, K_DSS, K_EMPTY, K_GAP, K_NEW, K_PROBE, K_SCAN, LABEL
from .sysdb import CURRENT
from .sysroute import shorten
from .state import CFG, KIND_SHORT, RADIUS_CHOICES, ST, cfg_bool, cfg_int, cfg_set, logger
from . import cockpit
from . import fislaunch
from . import miningwin
from . import probewin
from . import routewin
from . import skin
from . import statswin
from . import survey
from . import uithread
from . import updater

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


def _set_status(txt: str) -> None:
    ST.status = txt
    if _v_status:
        uithread._ui(lambda: _v_status.set(txt))


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """
    The main panel, kept deliberately small.

    EDMC's window is shared with every other plugin, so this shows only what
    you act on between jumps: the next flight target, the next name to check,
    and where you are. Counters, fuel, statistics and the route list all live
    in their own windows, reachable from one row of buttons.
    """
    global _frame, _v_status, _v_target, _v_kind, _v_sys, _v_queue, _v_probe
    global _btn_start, _radius_var
    global _btn_stats, _lbl_stats, _v_stats, _carrier_var
    global _btn_next, _v_route, _lbl_route, _btn_route
    global _v_fuel, _lbl_queue, _lbl_fuel, _v_update, _lbl_update

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)
    uithread._ui_target = _frame.winfo_toplevel()  # updates sent by worker threads
    uithread._ui_target.bind(uithread._UI_EVENT, uithread._ui_drain, add="+")

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
    lp.bind("<Button-1>", lambda e: survey._copy_probe())

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
    skin._theme_menu(radius_pick, skin._theme_colours())
    _btn_next = tk.Button(bar, text="copy", width=6, command=_copy_flight_click)
    _btn_next.pack(side=tk.LEFT)
    _btn_route = tk.Button(bar, text="route", width=6,
                           command=routewin._toggle_route_window)
    _btn_route.pack(side=tk.LEFT, padx=(3, 0))
    _btn_stats = tk.Button(bar, text="info", width=6,
                           command=statswin._toggle_stats_window)
    _btn_stats.pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(bar, text="probe", width=6,
              command=probewin._toggle_probe_window).pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(bar, text="atlas", width=6,
              command=miningwin._toggle_mining_window).pack(side=tk.LEFT, padx=(3, 0))

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
    _lbl_update.bind("<Button-1>", lambda e: updater._open_release_page())
    _lbl_update.grid_remove()

    _refresh()
    theme.update(_frame)
    # SHBOX FIS along with EDMC, when ticked in the settings
    _frame.after(fislaunch.FIS_AUTOSTART_DELAY_MS, fislaunch._fis_autostart)
    _frame.after(cockpit.OVERLAY_KEEP_MS, cockpit._overlay_keepalive)
    return _frame


def _on_carrier_toggle() -> None:
    cfg_set(CFG["carrier_start"], bool(_carrier_var.get()))
    _refresh()


def _copy_flight_click() -> None:
    t = survey.current_flight()
    if t:
        survey._copy(t.name)


def _on_start() -> None:
    if ST.active:
        survey._stop_survey()
    else:
        survey._start_survey()


def _refresh() -> None:
    if not _frame:
        return
    try:
        t = survey.current_flight()
        if t:
            _v_target.set("%s   %.1f ly" % (t.name, t.dist_origin))
            _v_kind.set("%s %s" % (KIND_SHORT.get(t.kind, t.kind),
                                   t.detail or LABEL.get(t.kind, "")))
        else:
            _v_target.set("-")
            _v_kind.set("no flight targets left" if ST.active else "survey inactive")

        probewin._probe_window_refresh()

        p = survey.current_probe()
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
            _btn_route.config(text="route x" if routewin._route_win is not None else "route")
        if _btn_stats:
            _btn_stats.config(text="info x" if statswin._stats_win is not None else "info")
    except Exception:
        logger.exception("UI refresh failed")
