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
from . import overlaywin
from . import panel
from . import planning
from . import routewin
from . import uithread
from . import updater

_p: Dict[str, Any] = {}


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> Optional[nb.Frame]:
    """
    Preferences, on tabs of their own (4.12): Survey, Data, Overlay,
    Windows, FIS, Maintenance.

    Everything is grid() - EDMC's notebook frames already use the grid
    manager, and mixing in pack() raises TclError. All options in two
    columns had grown taller than a 1080p screen (the OK button was just
    reachable, user 14.11.2026); on tabs the window is as tall as the
    longest tab.
    """
    f = nb.Frame(parent)
    f.columnconfigure(0, weight=1)
    nb.Label(f, text="SHBOXSEARCH v%s" % VERSION).grid(row=0, column=0, sticky=tk.W, pady=(0, 4))
    tabs = nb.Notebook(f)
    tabs.grid(row=1, column=0, sticky=tk.NSEW)
    for title, build in (("Survey", _tab_survey), ("Data", _tab_data), ("Overlay", _tab_overlay),
                         ("Windows", _tab_windows), ("FIS", _tab_fis), ("Maintenance", _tab_maintenance)):
        page = nb.Frame(tabs)
        page.columnconfigure(3, weight=1)
        tabs.add(page, text=title)
        build(_Rows(page))
    return f


class _Rows:
    """One settings tab: headings, labelled fields and notes, row after row."""

    def __init__(self, frame: Any) -> None:
        self.f = frame
        self.row = 0

    def head(self, text: str) -> None:
        """A section heading."""
        nb.Label(self.f, text=text).grid(row=self.row, column=0, columnspan=4, sticky=tk.W,
                                         pady=(10 if self.row else 6, 2))
        self.row += 1

    def field(self, label: str, widget: Any) -> None:
        """A widget, with a label on its left when one is given."""
        if label:
            nb.Label(self.f, text=label).grid(row=self.row, column=0, sticky=tk.W, padx=(12, 6))
            widget.grid(row=self.row, column=1, columnspan=3, sticky=tk.W)
        else:
            widget.grid(row=self.row, column=0, columnspan=4, sticky=tk.W, padx=(12, 0))
        self.row += 1

    def note(self, text: str) -> None:
        """A line of explanation."""
        nb.Label(self.f, text=text).grid(row=self.row, column=0, columnspan=4, sticky=tk.W, padx=(12, 0))
        self.row += 1

    def check(self, key: str, cfg: str, default: bool, text: str) -> None:
        """A tick box bound to one setting (kept in _p[key])."""
        _p[key] = tk.IntVar(value=1 if cfg_bool(CFG[cfg], default) else 0)
        self.field("", nb.Checkbutton(self.f, text=text, variable=_p[key]))


def _tab_survey(r: _Rows) -> None:
    """The sphere and what counts as needing a visit."""
    r.head("Sphere")
    _p["radius"] = tk.StringVar(value=str(cfg_int(CFG["radius"], 50)))
    r.field("Radius (ly)", ttk.OptionMenu(r.f, _p["radius"], _p["radius"].get(), *RADIUS_CHOICES))
    mcf = nb.Frame(r.f)
    _p["mc"] = {}
    active_mc = set(get_masscodes())
    for i in range(8):
        v = tk.IntVar(value=1 if i in active_mc else 0)
        _p["mc"][i] = v
        nb.Checkbutton(mcf, text=MASSCODES[i], variable=v).grid(row=0, column=i, sticky=tk.W)
    r.field("Mass codes", mcf)
    _p["probe"] = tk.StringVar(value=str(cfg_int(CFG["probe_depth"], 2)))
    r.field("Probes above max", nb.EntryMenu(r.f, textvariable=_p["probe"], width=5))
    r.check("empty", "include_empty", True, "probe unexplored boxels")
    r.check("tasks", "include_tasks", True, "queue outstanding scans")
    r.check("carrier_start", "carrier_start", False, "carrier start (centre on the carrier)")
    r.head("What counts as needing a visit")
    r.note("Any ticked reason is enough.")
    active_f = set(get_filters())
    _p["filters"] = {}
    for key in ALL_FILTERS:
        v = tk.IntVar(value=1 if key in active_f else 0)
        _p["filters"][key] = v
        r.field("", nb.Checkbutton(r.f, text=FILTER_LABEL[key], variable=v))


def _tab_data(r: _Rows) -> None:
    """Where the data comes from, what is read from the game, commanders."""
    r.head("Data sources")
    r.check("edd", "src_edd", True, "EDDiscovery (local)")
    r.check("spansh", "src_spansh", True, "Spansh")
    r.check("edsm", "src_edsm", True, "EDSM")
    r.check("offline", "offline", False, "offline - no online requests at all (EDSM, Spansh, update check)")
    _p["eddpath"] = tk.StringVar(value=cfg_str(CFG["edd_path"]))
    row = nb.Frame(r.f)
    nb.EntryMenu(row, textvariable=_p["eddpath"], width=30).grid(row=0, column=0, sticky=tk.W)
    tk.Button(row, text="...", width=3, command=_pick_edd).grid(row=0, column=1, sticky=tk.W, padx=4)
    r.field("EDDSystem.sqlite", row)
    r.check("edd_archive", "edd_archive", False,
            "learn from EDDiscovery's archive (older journals in EDDUser.sqlite, read only)")
    for name, ok, why in ST.sources.status():
        r.note("  %-12s %-4s %s" % (name, "ok" if ok else "no", why[:40]))
    r.head("Harvesting")
    r.check("navroute", "harvest_navroute", True, "read NavRoute")
    r.check("dest", "harvest_destination", True, "read target selection")
    r.check("autocopy", "autocopy", True, "copy next target to clipboard")
    r.check("check_updates", "check_updates", True, "check GitHub for a newer release (once a day, notify only)")
    # C1: more than one commander on this PC
    choices = planning._main_cmdr_choices()
    if len(choices) > 1:
        r.head("Commanders")
        labels = [c[0] for c in choices]
        cur = cfg_str(CFG["main_cmdr"], "")
        sel = next((c[0] for c in choices if c[1] == cur), labels[0])
        _p["main_cmdr"] = tk.StringVar(value=sel)
        _p["main_cmdr_map"] = {c[0]: c[1] for c in choices}
        r.field("Main commander", ttk.OptionMenu(r.f, _p["main_cmdr"], sel, *labels))
        r.note("survey plan and statistics; each commander's own")
        r.note("visits and scans are kept apart, finds are shared")


def _tab_overlay(r: _Rows) -> None:
    """The cockpit overlay: how it is drawn, its blocks, the situation column."""
    r.head("Cockpit overlay")
    # D3 (4.12): EDMCModernOverlay or a window of the plugin's own
    backends = [("EDMCModernOverlay", "modern")]
    if overlaywin.supported():
        backends.append(("own window (beta)", "window"))
    cur = cfg_str(CFG["overlay_backend"], "modern")
    _p["overlay_backend"] = tk.StringVar(value=next((lb for lb, k in backends if k == cur), backends[0][0]))
    _p["overlay_backends"] = dict(backends)
    r.field("Draw with", ttk.OptionMenu(r.f, _p["overlay_backend"], _p["overlay_backend"].get(),
                                        *[lb for lb, _k in backends]))
    r.note("own window: the game in a borderless window; shown while the game is in front")
    _p["overlay_pos"] = tk.StringVar(value=cfg_str(CFG["overlay_pos"], "top-left"))
    r.field("Position", ttk.OptionMenu(r.f, _p["overlay_pos"], _p["overlay_pos"].get(), *OVERLAY_POSITIONS))
    r.head("Blocks")
    r.check("overlay", "overlay", True, "show the next route targets in the game")
    r.check("overlay_brief", "overlay_brief", True, "briefing on target selection and arrival")
    r.check("overlay_nav", "overlay_nav", True, "surface compass: parked SRV, open samples, known points")
    r.check("overlay_mining", "overlay_mining", True, "mining: last rock, hold, rate, session, limpets (5 lines)")
    # 4.12: the situation column in the opposite corner (cockpitinfo)
    r.head("Situation column (the opposite corner)")
    r.check("overlay_info_warn", "overlay_info_warn", True, "warnings: dangerous star ahead, unsold data at stake")
    r.check("overlay_info_place", "overlay_info_place", True,
            "places: landing card, system value, ring, boxel, route fuel, carrier")
    r.check("overlay_info_session", "overlay_info_session", True, "session tally after a sale or on docking")
    ov = getattr(ST, "overlay", None)
    r.note("overlay: %s" % (
        "own window" if ov is not None and isinstance(ov.client, overlaywin.WindowClient)
        else "EDMCModernOverlay connected" if ov is not None and ov.available() else "EDMCModernOverlay not installed"))


def _tab_windows(r: _Rows) -> None:
    """The plugin's windows and its line in EDMC's main window."""
    r.head("Windows")
    r.check("route_top", "route_top", True, "keep windows on top")
    r.check("route_map", "route_map", True, "draw the system map")
    r.check("route_all", "route_all", False, "route every body, always")
    r.check("route_done_tour", "route_done_tour", True, "nothing left in a system: show the full tour anyway")
    r.check("route_arrival", "route_arrival", True, "start the route at the arrival star")
    _p["map_size"] = tk.StringVar(value=cfg_str(CFG["map_size"], "medium"))
    r.field("Map size", ttk.OptionMenu(r.f, _p["map_size"], _p["map_size"].get(), "small", "medium", "large"))
    r.head("Panel in EDMC")
    r.check("show_route", "show_route", True, "show the route line in the panel")
    r.check("panel_fuel", "panel_fuel", False, "show fuel in the panel (warnings always show)")
    r.check("panel_queue", "panel_queue", False, "show queue counters in the panel")
    _p["jump"] = tk.StringVar(value=str(cfg_int(CFG["jump_range"], 0) or ""))
    r.field("Jump range (0=auto)", nb.EntryMenu(r.f, textvariable=_p["jump"], width=6))


def _tab_fis(r: _Rows) -> None:
    """SHBOX FIS: start, open, autostart."""
    r.head("SHBOX FIS - flight information system")
    fis_row = tk.Frame(r.f)
    tk.Button(fis_row, text="start FIS", command=fislaunch._fis_start).pack(side=tk.LEFT)
    tk.Button(fis_row, text="open in browser", command=fislaunch._fis_open).pack(side=tk.LEFT, padx=(6, 0))
    fis_state = tk.StringVar(value=fislaunch._fis_status())
    tk.Button(fis_row, text="check", command=lambda: fis_state.set(fislaunch._fis_status())).pack(
        side=tk.LEFT, padx=(6, 0))
    r.field("", fis_row)
    r.check("fis_autostart", "fis_autostart", False, "start the FIS together with EDMC (window minimised)")
    r.field("", nb.Label(r.f, textvariable=fis_state))
    r.note("or double-click FIS\\start_fis.bat - first start asks, then remembers;")
    r.note("change it later with FIS\\fis_settings.bat. Details: FIS\\README.md")


def _tab_maintenance(r: _Rows) -> None:
    """Imports, exports, self test, update check; where things are."""
    r.head("Maintenance")
    tools = nb.Frame(r.f)
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
        tk.Button(tools, text=text, command=cmd).grid(row=i // 3, column=i % 3, sticky=tk.W, padx=(0, 6), pady=2)
    r.field("", tools)
    r.head("About")
    jd = maintenance._journal_dir()
    car = ST.db.get_carrier() if ST.db else None
    r.note("Version %s  -  %s" % (VERSION, REPO_URL))
    r.note("Journal folder: %s" % (jd or "NOT FOUND"))
    r.note("First import: %s" % ((ST.db.get_meta("migrated") if ST.db else None) or "not run yet"))
    r.note("Carrier: %s" % ("%s%s" % (car["system"], "  (%s)" % car["callsign"] if car.get("callsign") else "")
                            if car else "not known yet - dock at it once"))
    r.check("debug", "debug", False, "verbose logging")


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
        cfg_set(CFG["edd_archive"], bool(_p["edd_archive"].get()))
        cfg_set(CFG["harvest_navroute"], bool(_p["navroute"].get()))
        cfg_set(CFG["harvest_destination"], bool(_p["dest"].get()))
        cfg_set(CFG["autocopy"], bool(_p["autocopy"].get()))
        cfg_set(CFG["carrier_start"], bool(_p["carrier_start"].get()))
        cfg_set(CFG["show_route"], bool(_p["show_route"].get()))
        cfg_set(CFG["route_all"], bool(_p["route_all"].get()))
        cfg_set(CFG["route_done_tour"], bool(_p["route_done_tour"].get()))
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
        for key in ("overlay_info_warn", "overlay_info_place", "overlay_info_session"):
            cfg_set(CFG[key], bool(_p[key].get()))
        if "fis_autostart" in _p:
            cfg_set(CFG["fis_autostart"], bool(_p["fis_autostart"].get()))
        cfg_set(CFG["overlay_pos"], _p["overlay_pos"].get())
        cfg_set(CFG["overlay_backend"], _p["overlay_backends"].get(_p["overlay_backend"].get(), "modern"))
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
