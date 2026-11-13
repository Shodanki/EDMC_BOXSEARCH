# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The statistics window: survey progress, sources and timing."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

from .boxelplan import Planner
from .state import CFG, ST, cfg_bool, cfg_set, logger
from . import panel
from . import planning
from . import routewin
from . import skin
from . import uithread


_stats_win: Optional[tk.Toplevel] = None
_stats_body: Optional[tk.Frame] = None
_stats_scroll: Optional[tk.Canvas] = None


def _toggle_stats_window() -> None:
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
    panel._refresh()


def _stats_window_open() -> None:
    """Statistics in their own window, as tables, in the host's colours."""
    global _stats_win, _stats_body
    if panel._frame is None:
        return
    _stats_win = tk.Toplevel(panel._frame)
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
              command=lambda: uithread._run_async(planning._rebuild_plan, label="stats")).pack(
        side=tk.LEFT)
    tk.Button(bar, text="reload online data",
              command=lambda: uithread._run_async(planning._reload_online,
                                                  label="reload online data")).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="close", command=_stats_window_close).pack(
        side=tk.LEFT, padx=(4, 0))
    _stats_window_refresh()
    routewin._fit_to_screen(_stats_win)
    panel._refresh()


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
    col = skin._theme_colours()
    row_i = 0

    def table(title: str, rows: List[Tuple[str, str]]) -> None:
        nonlocal row_i
        head = tk.Label(_stats_body, text=title, anchor=tk.W, font=skin._FONT_GROUP)
        head.grid(row=row_i, column=0, columnspan=2, sticky=tk.W,
                  pady=(10 if row_i else 0, 2))
        skin._apply_theme(head, col, is_text=True)
        row_i += 1
        for label, value in rows:
            a = tk.Label(_stats_body, text="  " + label, anchor=tk.W, font=skin._MONO)
            b = tk.Label(_stats_body, text=value, anchor=tk.W, font=skin._MONO)
            a.grid(row=row_i, column=0, sticky=tk.W, padx=(8, 16))
            b.grid(row=row_i, column=1, sticky=tk.W)
            skin._apply_theme(a, col, is_text=True)
            skin._apply_theme(b, col, is_text=True)
            row_i += 1

    if ST.stats:
        for title, rows in Planner.stats_table(ST.stats):
            table(title, rows)

    # this sphere, in time
    sphere_rows = _sphere_rows()
    if sphere_rows:
        table("This sphere", sphere_rows)

    # what it paid
    try:
        with ST.lock:
            e = ST.db.earnings()
        if e["sales"]:
            table("Earnings", _earnings_rows(e))
    except Exception:
        logger.exception("earnings summary failed")

    # everything ever
    try:
        with ST.lock:
            lt = ST.db.lifetime()
        table("All time", _lifetime_rows(lt))
    except Exception:
        logger.exception("lifetime statistics failed")

    skin._theme_tree(_stats_win, col)


def _sphere_rows() -> List[Tuple[str, str]]:
    """This sphere: centre, bodies and time per system, fuel."""
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
    return sphere_rows


def _earnings_rows(e: Dict[str, Any]) -> List[Tuple[str, str]]:
    """What exploration and biology data sold for (``e`` from db.earnings)."""
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
    return rows


def _lifetime_rows(lt: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Everything ever (``lt`` from db.lifetime), with the commanders."""
    who = []
    if lt.get("commander"):
        who.append(("Commander", "%s (main)" % lt["commander"]))
    for nm, n in lt.get("also") or []:
        who.append(("Also explored by", "%s: %d systems" % (nm, n)))
    return who + [
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
    ]


def _toggle_stats() -> None:
    show = not cfg_bool(CFG["show_stats"], False)
    cfg_set(CFG["show_stats"], show)
    panel._refresh()
