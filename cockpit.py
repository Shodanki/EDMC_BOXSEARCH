# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Cockpit overlay and briefing.

What the next jump brings (``_briefing_info``), the route check of a
plotted route, fuel-scoop planning and the targets block - shown through
EDMCModernOverlay when it is installed. Display only; nothing is sent to
the game.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from . import shells
from .biopredict import BioModel
from .deepspace import is_scoopable, scoop_line, scoop_plan
from .overlay import POSITIONS as OVERLAY_POSITIONS
from .procgen import parse_name, star_pos
from .sysdb import CURRENT, Q_ESTIMATE
from .state import CFG, ST, cfg_bool, cfg_str, logger
from . import panel
from . import planning
from . import uithread
try:                # codex regions (klightspeed's map, MIT) - optional
    from . import regionmap
except Exception:   # pragma: no cover - folder missing
    regionmap = None

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
        if panel._frame is not None:
            try:
                panel._frame.after(OVERLAY_KEEP_MS, _overlay_keepalive)
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
    # 4.10: the codex region - from the position, else from the id64 boxel
    if regionmap is not None:
        try:
            reg = None
            if row is not None and row["x"] is not None:
                reg = regionmap.find_region(row["x"], row["y"], row["z"])
            elif id64:
                reg = regionmap.find_region_for_id64(int(id64))
            if reg:
                info["region"] = reg[1]
        except Exception:
            logger.debug("region lookup failed", exc_info=True)
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
        planning._log_net(planning._flush_net_log())
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
        planning._store_rows(known)
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
    uithread._run_async(_route_check, hops, label="route check")


def _note_navroute(route: Any) -> None:
    """F1: keep the plotted route (EDMC hands NavRoute with its Route)."""
    hops = []
    for h in route or []:
        hops.append((h.get("StarSystem") or "", h.get("StarClass"),
                     star_pos(h.get("StarPos"))))
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
