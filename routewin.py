# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The in-system route: computing it and its window.

``_rebuild_route`` plans the order of the bodies to visit; the route
window lists the stops and draws the system map. The route follows the
ship's position from the journal.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

# EDMC API
from theme import theme

from .sysdb import CURRENT
from .sysroute import (F_ALL, bodies_from_rows, map_projection, pace_ratio, plan_route, shorten,
                       spread_points, start_at_body)
from .state import CFG, ST, cfg_bool, cfg_set, cfg_str, get_filters, logger
from . import cockpit
from . import maintenance
from . import panel
from . import planning
from . import skin
from . import survey
from . import uithread


def _rebuild_route() -> None:
    """Order the bodies of the current system into a short in-system route."""
    ST.route = None
    ST.route_lines = []
    planning._resolve_current_system()
    if not (ST.db and ST.cur_id64):
        logger.info("route | no current system known yet")
        return
    with ST.lock:
        # C1: what THIS commander still has to do here (knowledge is shared)
        rows = ST.db.bodies_for(ST.cur_id64, ST.db.view_fid(CURRENT))
    if not rows and ST.cur_id64 not in cockpit._replayed_for:
        # Nothing stored for this system - the scans may predate the plugin or
        # have happened while it was not running. Replay the recent journals
        # once per system and session: arriving in a fresh, unscanned system
        # used to trigger a full replay on every route rebuild, which could
        # never find anything the live journal feed had not already seen.
        cockpit._replayed_for.add(ST.cur_id64)
        logger.info("route | no bodies stored for %s, replaying recent journals",
                    ST.cur_system)
        d = maintenance._journal_dir()
        if d:
            res = ST.db.import_journals(d, max_files=6, lock=ST.lock)
            logger.info("route | replayed %s", res)
            with ST.lock:
                rows = ST.db.bodies_for(ST.cur_id64, ST.db.view_fid(CURRENT))
    if not rows:
        logger.info("route | %s has no scanned bodies yet - run a system scan",
                    ST.cur_system)
        uithread._ui(_route_window_refresh)
        return
    bodies = bodies_from_rows(rows, now=time.time())
    for b in bodies.values():
        b.short = shorten(b.name, ST.cur_system or "")
    try:
        model = cockpit._get_bio_model()
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
    uithread._ui(_route_window_refresh)


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


def _toggle_route_window() -> None:
    """Open or close the route window."""
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
    panel._refresh()


def _route_window_open() -> None:
    """
    A separate window listing the in-system route.

    Copy and paste is pointless in here: bodies are picked in the system map,
    not typed. So the window is a checklist - tick a stop off and the remaining
    time updates. Only the external jump target is ever copied, from the main
    panel.
    """
    global _route_win, _route_head, _route_body
    if panel._frame is None:
        return
    _route_win = tk.Toplevel(panel._frame)
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
              command=lambda: uithread._run_async(_rebuild_route, label="route")).pack(
        side=tk.LEFT)
    tk.Button(bar, text="map", command=_route_map_toggle).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="reset ticks", command=_route_reset).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="map", command=_toggle_map).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="size", command=_cycle_map_size).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="review", command=survey._route_review).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="close", command=_route_window_close).pack(
        side=tk.LEFT, padx=(4, 0))

    _route_theme()
    _route_window_refresh()
    _fit_to_screen(_route_win)
    panel._refresh()


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
    skin._theme_tree(_route_win, skin._theme_colours())


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

    # plane from the data, log radius (sysroute.map_projection)
    project, rmax = map_projection(pts, cx, cy, span)

    col = skin._theme_colours()
    fg = col.get("fg") or "#ff8000"

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
                                   font=skin._FONT_SMALL)

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
                               anchor=anchor, font=skin._FONT_SMALL)

    if last_pos is not None:
        lx, ly = last_pos
        _route_map.create_oval(lx - 7, ly - 7, lx + 7, ly + 7,
                               outline=_MAP_LAST, width=2)
        _route_map.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                               fill=_MAP_LAST, outline=_MAP_LAST)
        _route_map.create_text(lx, ly + 12, text="last here", fill=_MAP_LAST,
                               font=skin._FONT_SMALL)


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
    panel._set_status("map size: %s" % nxt)


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
    panel._set_status("ticks cleared (%d)" % n)
    _route_window_refresh()
    panel._refresh()


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
    uithread._ui(_route_window_refresh)


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
            uithread._ui(_route_window_refresh)
            uithread._ui(panel._refresh)
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
    panel._refresh()


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
    cockpit._overlay_targets()
    if _route_win is None or _route_body is None:
        return
    try:
        for w in _route_body.winfo_children():
            w.destroy()
    except Exception:
        pass
    _route_rows = []
    col = skin._theme_colours()

    route = ST.route
    lost = planning._lost_here()
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
                skin._MARK_PLANET, st.body.short[:24], st.leg_ls,
                st.leg_s / 60.0, st.work)
            lone = tk.Label(row, text=text, anchor=tk.W, font=skin._FONT_GROUP)
            lone.pack(side=tk.LEFT)
            skin._apply_theme(row, col)
            skin._apply_theme(cb, col, is_text=True)
            skin._apply_theme(lone, col, is_text=True)
            _route_rows.append({"body_id": st.body.body_id, "var": var})
            continue
        # --- planet heading -------------------------------------------------
        hdr = tk.Frame(_route_body)
        hdr.grid(row=row_i, column=0, sticky=tk.EW, pady=(8 if row_i else 0, 1))
        row_i += 1
        moons = len(stops) - 1
        htxt = "%s  %s" % (skin._MARK_PLANET, label)
        if moons:
            htxt += "   +%d moon%s" % (moons, "" if moons == 1 else "s")
        if transfer >= 1.0:
            htxt += "   transfer %.0f LS, %.0f min" % (transfer,
                                                       stops[0].leg_s / 60.0)
        lbl = tk.Label(hdr, text=htxt, anchor=tk.W, font=skin._FONT_GROUP)
        lbl.pack(side=tk.LEFT)
        skin._apply_theme(hdr, col)
        skin._apply_theme(lbl, col, is_text=True)

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
            marker = skin._MARK_MOON if st.is_moon else skin._MARK_BODY
            text = "%s%s %-24s %7.0f LS %4.0f min  %s" % (
                indent, marker, st.body.short[:24], st.leg_ls,
                st.leg_s / 60.0, st.work)
            body_lbl = tk.Label(row, text=text, anchor=tk.W,
                                font=skin._FONT_MOON if st.is_moon else skin._FONT_BODY)
            body_lbl.pack(side=tk.LEFT)
            skin._apply_theme(row, col)
            skin._apply_theme(cb, col, is_text=True)
            skin._apply_theme(body_lbl, col, is_text=True)
            _route_rows.append({"body_id": st.body.body_id, "var": var})

    _route_theme()
