# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The probe window: the galaxy map checking controls.

Shows the boxel being checked, the name to type, and the buttons for
"not there", "list ends at [n]" and skip.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Optional, Tuple

from .boxelplan import K_EMPTY, K_GAP, K_PROBE
from .procgen import boxel_prefix
from .state import CFG, ST, cfg_bool
from . import panel
from . import planning
from . import skin
from . import survey
from . import uithread

_probe_win: Optional[tk.Toplevel] = None
_probe_head: Optional[tk.StringVar] = None
# "list ends at [n]" (4.10): the field, and the boxel it was filled for
_list_end_var: Optional[tk.StringVar] = None
_list_end_key: Optional[str] = None
_known_max_cache: Tuple[Any, Optional[int]] = (None, None)


def _toggle_probe_window() -> None:
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
    global _probe_win
    if _probe_win is not None:
        try:
            _probe_win.destroy()
        except Exception:
            pass
    _probe_win = None
    panel._btn_prefix = panel._btn_bundle = panel._btn_absent = panel._btn_boxel = panel._btn_skip = None
    panel._refresh()


def _probe_window_open() -> None:
    global _probe_win, _probe_head
    if panel._frame is None:
        return
    _probe_win = tk.Toplevel(panel._frame)
    _probe_win.title("SHBOXSEARCH - galaxy map check")
    _probe_win.protocol("WM_DELETE_WINDOW", _probe_window_close)
    try:
        _probe_win.attributes("-topmost", cfg_bool(CFG["route_top"], True))
    except Exception:
        pass
    _probe_head = tk.StringVar(value="")
    tk.Label(_probe_win, textvariable=_probe_head, anchor=tk.W,
             justify=tk.LEFT, font=skin._MONO).grid(row=0, column=0, sticky=tk.EW,
                                                    padx=10, pady=(8, 6))
    bar = tk.Frame(_probe_win)
    bar.grid(row=1, column=0, sticky=tk.EW, padx=10, pady=(0, 4))
    panel._btn_prefix = tk.Button(bar, text="copy prefix", command=survey._copy_prefix)
    panel._btn_prefix.pack(side=tk.LEFT)
    panel._btn_bundle = tk.Button(bar, text="copy bundle", command=survey._copy_bundle)
    panel._btn_bundle.pack(side=tk.LEFT, padx=(4, 0))
    panel._btn_absent = tk.Button(bar, text="not there", command=survey._probe_absent)
    panel._btn_absent.pack(side=tk.LEFT, padx=(4, 0))
    global _list_end_var, _list_end_key
    _list_end_var = tk.StringVar(value="")
    _list_end_key = None
    tk.Label(bar, text="list ends at").pack(side=tk.LEFT, padx=(8, 0))
    ent = tk.Entry(bar, textvariable=_list_end_var, width=5)
    ent.pack(side=tk.LEFT, padx=(4, 0))
    ent.bind("<Return>", lambda e: survey._list_end())
    panel._btn_boxel = tk.Button(bar, text="list end", command=survey._list_end)
    panel._btn_boxel.pack(side=tk.LEFT, padx=(4, 0))
    panel._btn_skip = tk.Button(bar, text="later", command=survey._probe_skip)
    panel._btn_skip.pack(side=tk.LEFT, padx=(4, 0))

    bar2 = tk.Frame(_probe_win)
    bar2.grid(row=2, column=0, sticky=tk.EW, padx=10, pady=(0, 8))
    tk.Button(bar2, text="replan",
              command=lambda: uithread._run_async(planning._rebuild_plan, label="replanning")).pack(
        side=tk.LEFT)
    tk.Button(bar2, text="copy route target", command=planning._copy_route_target).pack(
        side=tk.LEFT, padx=(0, 4))
    tk.Button(bar2, text="copy FC", command=survey._copy_carrier).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar2, text="carrier spot",
              command=lambda: uithread._run_async(survey._plan_staging, label="staging")).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Checkbutton(bar2, text="carrier start", variable=panel._carrier_var,
                   command=panel._on_carrier_toggle).pack(side=tk.LEFT, padx=(8, 0))

    _probe_window_refresh()
    skin._theme_tree(_probe_win, skin._theme_colours())
    panel._refresh()


def _probe_window_refresh() -> None:
    global _list_end_key, _known_max_cache
    if _probe_win is None or _probe_head is None:
        return
    p = survey.current_probe()
    top = None
    if p and p.boxel_key and ST.db is not None:
        # asked again only when the boxel or the queue changed - a refresh
        # runs on the UI thread and comes often
        tag = (p.boxel_key, len(ST.probe))
        if _known_max_cache[0] != tag:
            with ST.lock:
                _known_max_cache = (tag, ST.db.boxel_known_max(p.boxel_key))
        top = _known_max_cache[1]
        if p.boxel_key != _list_end_key and _list_end_var is not None:
            # a new boxel: the field starts with the highest number known
            _list_end_key = p.boxel_key
            _list_end_var.set("" if top is None else str(top))
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
            "this boxel   %d candidate%s   odds %s   known to %s\n"
            "queue        %d probes (gap %d, probe %d, empty %d)%s%s"
            % (p.name,
               boxel_prefix(p.boxel_key) if p.boxel_key else "?",
               # n1 = 0 boxels: the prefix also lists the d1-.., d2-.. boxels
               "   (count only names without '-')"
               if p.boxel_key and p.boxel_key[-1:].isalpha() else "",
               p.dist_origin, p.uncertainty,
               same, "" if same == 1 else "s", odds,
               "-" if top is None else "-%d" % top, len(ST.probe),
               c.get(K_GAP, 0), c.get(K_PROBE, 0), c.get(K_EMPTY, 0),
               # 4.10: a named sector's surface cuts this boxel - its
               # systems can carry either name (same number n2)
               ("\nedge         %s" % p.detail) if p.detail else "",
               ("\nplot route   %s  %.0f ly, %d unprobed boxels on the way"
                "\n             (economical route = more hops = more systems)"
                % (ST.route_targets[0]["name"], ST.route_targets[0]["dist"],
                   ST.route_targets[0]["boxels"])) if ST.route_targets else ""))
