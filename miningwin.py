# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The mining window and the atlas: find a ring, signal or material again."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

from .state import CFG, ST, cfg_bool, cfg_set, cfg_str
from . import panel
from . import routewin
from . import skin
from . import survey

_mine_win: Optional[tk.Toplevel] = None
_mine_body: Optional[tk.Frame] = None
_mine_mat: Optional[tk.StringVar] = None


def _toggle_mining_window() -> None:
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
    global _mine_win, _mine_body, _atlas_mode, _atlas_pick_frame, _atlas_range
    if panel._frame is None or ST.db is None:
        return
    _mine_win = tk.Toplevel(panel._frame)
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
    skin._theme_menu(rng_pick, skin._theme_colours())
    tk.Button(bar, text="refresh", command=_atlas_build_picker).pack(
        side=tk.LEFT, padx=(6, 0))
    tk.Button(bar, text="close", command=_mining_window_close).pack(
        side=tk.LEFT, padx=(4, 0))

    _mine_body = tk.Frame(_mine_win)
    _mine_body.grid(row=2, column=0, sticky=tk.NSEW, padx=10, pady=(0, 8))
    _atlas_build_picker()
    skin._theme_tree(_mine_win, skin._theme_colours())
    routewin._fit_to_screen(_mine_win)


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
    skin._theme_menu(picker, skin._theme_colours())
    _mining_refresh()


def _atlas_row(parent, row: int, text: str, system: str, col) -> None:
    lbl = tk.Label(parent, text=text, anchor=tk.W, font=skin._MONO)
    lbl.grid(row=row, column=0, sticky=tk.W)
    lbl.bind("<Button-1>", lambda e, n=system: survey._copy(n))
    skin._apply_theme(lbl, col, is_text=True)


def _short_body(body: Optional[str], system: str) -> str:
    b = str(body or "")
    return b[len(system):].strip() if system and b.startswith(system) else b


def _mining_refresh() -> None:
    """Draw the atlas list for the chosen mode and filter."""
    if _mine_win is None or _mine_body is None or ST.db is None:
        return
    try:
        for w in _mine_body.winfo_children():
            w.destroy()
    except Exception:
        pass
    col = skin._theme_colours()
    mode = _atlas_mode.get() if _atlas_mode else ATLAS_MODES[0]
    want = _mine_mat.get() if _mine_mat else "(all)"
    choices = dict(_atlas_choices(mode))
    key = choices.get(want)
    rows = _atlas_query(mode, key)

    if not rows:
        hint = {ATLAS_MODES[0]: "map a ring with the DSS and its materials land here",
                ATLAS_MODES[1]: "FSS / DSS a body and its signals land here",
                ATLAS_MODES[2]: "pick up a material and where you were lands here",
                ATLAS_MODES[3]: "land, log a codex entry, sample or take a screenshot"}
        max_ly = _atlas_max_ly()
        lbl = tk.Label(_mine_body, anchor=tk.W, font=skin._MONO,
                       text=("nothing within %.0f ly - pick a larger distance" % max_ly)
                       if max_ly and ST.cur_pos is not None else "nothing yet - " + hint.get(mode, ""))
        lbl.grid(row=0, column=0, sticky=tk.W)
        skin._apply_theme(lbl, col, is_text=True)
        return

    h = tk.Label(_mine_body, font=skin._FONT_GROUP, anchor=tk.W, text=_atlas_head(mode))
    h.grid(row=0, column=0, sticky=tk.W)
    skin._apply_theme(h, col, is_text=True)

    for i, r in enumerate(rows, 1):
        sysname = str(r["system"])
        _atlas_row(_mine_body, i, _atlas_line(mode, key, r, sysname), sysname, col)

    if _mine_mat:
        cfg_set(CFG[_ATLAS_KEY[mode]], want)


def _atlas_query(mode: str, key: Optional[str]) -> List[Dict[str, Any]]:
    """The atlas rows for a mode and filter, nearest first, within the
    chosen distance, at most 40."""
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
    return rows[:40]


def _atlas_dist(h: Dict[str, Any]) -> str:
    return ("%.0f ly" % h["dist"]) if h.get("dist") is not None else "-"


def _atlas_head(mode: str) -> str:
    """The column heads of a mode."""
    if mode == ATLAS_MODES[1]:
        return "%-26s %-22s %4s  %s" % ("system", "body", "x", "distance")
    if mode == ATLAS_MODES[2]:
        return "%-26s %-22s %5s  %-10s %s" % ("system", "where", "got", "last", "distance")
    if mode == ATLAS_MODES[3]:
        return "%-26s %-10s %-28s %-17s %s" % ("system", "body", "what", "lat / lon", "distance")
    return "%-26s %-26s %3s  %-10s %s" % ("system", "ring", "x", "ring type", "distance")


def _atlas_line(mode: str, key: Optional[str], r: Dict[str, Any], sysname: str) -> str:
    """One atlas row as text; without a filter (key None) the kind is added."""
    if mode == ATLAS_MODES[1]:
        body = _short_body(r.get("body_name"), sysname) or "(system)"
        text = "%-26s %-22s %4d  %s" % (sysname[:26], body[:22], r["count"] or 1, _atlas_dist(r))
        if key is None:
            text += "   " + _sig_label({"kind": r["kind"], "label": r["label"]})
    elif mode == ATLAS_MODES[3]:
        body = _short_body(r.get("body_name"), sysname)
        where = ("%+.4f %+.4f" % (r["lat"], r["lon"])) if r.get("lat") is not None else "-"
        text = "%-26s %-10s %-28s %-17s %s" % (
            sysname[:26], body[:10], str(r.get("label") or "")[:28], where, _atlas_dist(r))
    elif mode == ATLAS_MODES[2]:
        body = _short_body(r.get("body_name"), sysname) or "(in space)"
        text = "%-26s %-22s %5d  %-10s %s" % (
            sysname[:26], body[:22], r["count"], str(r.get("last") or "")[:10], _atlas_dist(r))
        if key is None:
            text += "   " + str(r.get("label") or r.get("material"))
    else:
        ring = _short_body(r["body"], sysname)
        text = "%-26s %-26s %3d  %-10s %s" % (
            sysname[:26], ring[:26], r["count"], (r["ring_class"] or "")[:10], _atlas_dist(r))
        if key is None:
            text += "   " + str(r["material"])
    return text
