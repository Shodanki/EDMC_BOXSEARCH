# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The plugin's page in EDMC's settings (``plugin_prefs``, ``prefs_changed``)."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Dict, Optional

# EDMC API
import myNotebook as nb

from .overlay import POSITIONS as OVERLAY_POSITIONS
from .procgen import MASSCODES
from .sources import SourceManager
from .sysroute import ALL_FILTERS, FILTER_LABEL, F_OUTSTANDING
from .state import (CFG, RADIUS_CHOICES, REPO_URL, ST, VERSION, cfg_bool, cfg_int, cfg_set,
                    cfg_str, get_filters, get_masscodes, logger)
from . import cockpit
from . import fislaunch
from . import maintenance
from . import panel
from . import planning
from . import routewin
from . import uithread
from . import updater

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
    choices = planning._main_cmdr_choices()
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
    tk.Button(fis_row, text="start FIS", command=fislaunch._fis_start).pack(side=tk.LEFT)
    tk.Button(fis_row, text="open in browser", command=fislaunch._fis_open).pack(side=tk.LEFT, padx=(6, 0))
    fis_state = tk.StringVar(value=fislaunch._fis_status())
    tk.Button(fis_row, text="check", command=lambda: fis_state.set(fislaunch._fis_status())).pack(
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
        ("Run first import", lambda: uithread._run_async(maintenance._first_run_migration,
                                                         label="first-run import")),
        ("Replay journals", lambda: uithread._run_async(maintenance._import_journals, label="journals")),
        ("Import JSON", lambda: uithread._run_async(maintenance._import_json, label="JSON import")),
        ("Export plan (CSV)", maintenance._export_csv),
        ("Boxel prefixes", maintenance._export_prefixes),
        ("Self test", lambda: uithread._run_async(maintenance._selftest, label="self test")),
        ("Check for update",
         lambda: uithread._run_async(updater._check_for_update, True, label="update check")),
    ]
    for i, (text, cmd) in enumerate(buttons):
        tk.Button(tools, text=text, command=cmd).grid(
            row=1 + i // 3, column=i % 3, sticky=tk.W, padx=(0, 6), pady=2)

    info = nb.Frame(f)
    info.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
    jd = maintenance._journal_dir()
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
    """EDMC hook: the settings dialog was closed - store our settings."""
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
            planning._apply_main_cmdr()
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
        cockpit._overlay_apply_settings()
        cockpit._overlay_targets()
        routewin._MAP_W = routewin._MAP_H = routewin._MAP_SIZES.get(_p["map_size"].get(), 480)
        picked = [k for k, v in _p.get("filters", {}).items() if v.get()]
        cfg_set(CFG["filters"], ",".join(picked) if picked else F_OUTSTANDING)
        planning._request_route(delay=0.2)
        if panel._carrier_var:
            panel._carrier_var.set(_p["carrier_start"].get())
        cfg_set(CFG["debug"], bool(_p["debug"].get()))
        logger.setLevel(logging.DEBUG if _p["debug"].get() else logging.INFO)
        ST.sources = SourceManager(_p["eddpath"].get() or None, gateway=ST.net)
        if panel._radius_var:
            panel._radius_var.set(_p["radius"].get())
        if ST.active:
            uithread._run_async(planning._rebuild_plan, label="Plan")
    except Exception:
        logger.exception("could not save settings")
