# -*- coding: utf-8 -*-
"""
SHBOXSEARCH v4.0 - systematic sphere survey for Elite Dangerous
===============================================================
EDMC plugin. Goal: fully explore and chart a radius around a start point,
deliberately hunting for systems that appear in no database at all.

Documentation: see README.md in the plugin folder.

Tested against EDMC 6.1.2 / Python 3.13.
MIT License (c) 2025-2026
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Dict, List, Optional, Tuple

# EDMC API
import myNotebook as nb
from config import appname, config
from theme import theme

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.append(_PLUGIN_DIR)

from procgen import MASSCODES, parse_name                      # noqa: E402
from sysdb import SystemDB, Q_JOURNAL, Q_UNKNOWN               # noqa: E402
from sources import SourceManager                              # noqa: E402
from deepspace import (FuelState, best_staging, is_scoopable,   # noqa: E402
                       staging_lines, tritium_systems)
from sysroute import (ALL_FILTERS, DEFAULT_MODEL, FILTER_LABEL,  # noqa: E402
                      F_ALL, F_OUTSTANDING, bodies_from_rows,
                      calibrate_from_journal, calibrate_work_from_journal,
                      plan_route, resolve_positions, shorten)
from boxelplan import (K_BIO, K_CHECK, K_DSS, K_EMPTY, K_GAP,  # noqa: E402
                       K_NEW, K_PROBE, K_SCAN, LABEL, Planner, Target,
                       set_origin)

VERSION = "4.0.0"
PLUGIN_NAME = os.path.basename(_PLUGIN_DIR)
logger = logging.getLogger("%s.%s" % (appname, PLUGIN_NAME))

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
    "edd_path": "%s_edd_path" % PLUGIN_NAME,
    "jump_range": "%s_jump_range" % PLUGIN_NAME,
    "harvest_navroute": "%s_harvest_navroute" % PLUGIN_NAME,
    "harvest_destination": "%s_harvest_dest" % PLUGIN_NAME,
    "debug": "%s_debug" % PLUGIN_NAME,
    "carrier_start": "%s_carrier_start" % PLUGIN_NAME,
    "show_stats": "%s_show_stats" % PLUGIN_NAME,
    "show_route": "%s_show_route" % PLUGIN_NAME,
    "route_all": "%s_route_all" % PLUGIN_NAME,
    "route_top": "%s_route_top" % PLUGIN_NAME,
    "route_map": "%s_route_map" % PLUGIN_NAME,
    "filters": "%s_filters" % PLUGIN_NAME,
    "map_size": "%s_map_size" % PLUGIN_NAME,
    "panel_fuel": "%s_panel_fuel" % PLUGIN_NAME,
    "panel_queue": "%s_panel_queue" % PLUGIN_NAME,
    "mine_mat": "%s_mine_mat" % PLUGIN_NAME,
}
RADIUS_CHOICES = ["50", "100", "150"]

KIND_SHORT = {K_SCAN: "FSS", K_DSS: "DSS", K_BIO: "BIO", K_NEW: "NEW",
              K_GAP: "GAP", K_PROBE: "PROBE", K_EMPTY: "EMPTY",
              K_CHECK: "CHECK"}


# ============================================================================
# State
# ============================================================================

class State:
    def __init__(self):
        self.db: Optional[SystemDB] = None
        self.lock = threading.RLock()
        self.sources = SourceManager()
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
        self.cur_id64: Optional[int] = None
        self.cur_pos: Optional[Tuple[float, float, float]] = None
        self.max_jump: Optional[float] = None
        self.last_dest_id64: Optional[int] = None

        self.sphere_id: Optional[int] = None
        self.stats: Dict[str, Any] = {}
        self.stats_lines: List[str] = []
        self.carrier: Optional[Dict[str, Any]] = None
        self.route = None
        self.route_lines: List[str] = []
        self.route_done: set = set()
        self.route_full = False
        self.route_feedback = ""
        self.route_started: Optional[float] = None
        self.cost_model = DEFAULT_MODEL
        self.sc_segments: List[Tuple[float, float]] = []
        self.work_dss: List[float] = []
        self.work_bio: List[float] = []
        self.work_approach: List[float] = []
        self._arrive: Dict[str, float] = {}
        self._bio_log: Dict[Tuple, float] = {}
        self.sys_times: List[Tuple[str, float, int]] = []
        self.fuel = FuelState()
        self.staging: List[Dict[str, Any]] = []
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
_btn_next: Optional[tk.Button] = None
_lbl_stats = None
_v_stats: Optional[tk.StringVar] = None
_v_route: Optional[tk.StringVar] = None
_v_fuel: Optional[tk.StringVar] = None
_lbl_fuel = None
_lbl_queue = None
_lbl_route = None
_btn_route: Optional[tk.Button] = None
_carrier_var: Optional[tk.IntVar] = None
_btn_absent: Optional[tk.Button] = None
_btn_skip: Optional[tk.Button] = None
_radius_var: Optional[tk.StringVar] = None


# ============================================================================
# Config helpers (robust across EDMC versions)
# ============================================================================

def cfg_bool(key: str, default: bool) -> bool:
    try:
        v = config.get_bool(key)
        return default if v is None else bool(v)
    except Exception:
        v = config.get(key)
        return default if v is None else str(v) not in ("0", "False", "")


def cfg_int(key: str, default: int) -> int:
    try:
        v = config.get_int(key)
        return default if v in (None, 0) and default else (default if v is None else int(v))
    except Exception:
        try:
            return int(config.get(key))
        except Exception:
            return default


def cfg_str(key: str, default: str = "") -> str:
    try:
        v = config.get_str(key)
    except Exception:
        v = config.get(key)
    return default if v in (None, "") else str(v)


def cfg_set(key: str, value) -> None:
    try:
        config.set(key, value)
    except Exception as e:
        logger.warning("config.set(%s) fehlgeschlagen: %s", key, e)


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


# ============================================================================
# EDMC lifecycle
# ============================================================================

def plugin_start3(plugin_dir: str) -> str:
    global _MAP_W, _MAP_H
    logger.info("SHBOXSEARCH v%s starting", VERSION)
    _MAP_W = _MAP_H = _MAP_SIZES.get(cfg_str(CFG["map_size"], "medium"), 480)
    try:
        ST.db = SystemDB(DB_FILE)
        ST.planner = Planner(ST.db)
    except Exception:
        logger.exception("could not open database")
        return "SHBOXSEARCH"

    ST.sources = SourceManager(cfg_str(CFG["edd_path"]) or None)

    if not ST.db.get_meta("migrated"):
        _run_async(_first_run_migration, label="first-run import")

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
        _run_async(_rebuild_plan, label="loading plan")
    # These read the journals to establish fuel, the work-time model and where
    # we last were. Without them the panel shows "fuel: unknown" and the map
    # has no "last here" marker until the first jump of the session.
    _run_async(_bootstrap_session, label="reading journals")
    _request_route(delay=2.5)
    return "SHBOXSEARCH"


def plugin_stop() -> None:
    _route_window_close()
    _stats_window_close()
    _probe_window_close()
    _mining_window_close()
    with ST.lock:
        if ST.db:
            ST.db.close()
    logger.info("SHBOXSEARCH stopped")


# ============================================================================
# Background work
# ============================================================================

def _run_async(fn, *args, label: str = "working", **kw) -> None:
    def wrapper():
        ST.busy = True
        _set_status(label + " ...")
        try:
            fn(*args, **kw)
        except Exception:
            logger.exception("background task '%s' failed", label)
            _set_status("error - see log")
        finally:
            ST.busy = False
            _ui(_refresh)
    threading.Thread(target=wrapper, daemon=True, name="SHBOX-" + label).start()


def _fetch_sources() -> None:
    if not ST.center:
        return
    enabled = []
    if cfg_bool(CFG["src_edd"], True):
        enabled.append("edd")
    if cfg_bool(CFG["src_spansh"], True):
        enabled.append("spansh")
    if cfg_bool(CFG["src_edsm"], True):
        enabled.append("edsm")
    if not enabled:
        return
    if ST.cur_id64 and ST.cur_pos:
        ST.sources.set_reference(ST.cur_id64, ST.cur_pos)
    logger.info("querying sources %s for r=%.0f ly around %s",
                enabled, ST.radius, ST.center)
    for name, ok, why in ST.sources.status():
        logger.info("  source %-12s %-3s %s", name, "ok" if ok else "no", why)
    rows, used = ST.sources.fetch_all(ST.center, ST.radius, enabled,
                                      progress=lambda s: _set_status(s))
    with ST.lock:
        n = 0
        for r in rows:
            if ST.db.upsert(r.get("name"), r.get("x"), r.get("y"), r.get("z"),
                            id64=r.get("id64"), source=r.get("source", "external"),
                            commit=False):
                n += 1
            for extra in r.get("also") or []:
                ST.db.upsert(r.get("name"), source=extra, quality=Q_UNKNOWN,
                             commit=False)
        ST.db.cx.commit()
    logger.info("sources returned %d rows from %s -> %d new systems",
                len(rows), ", ".join(used) or "none", n)
    _set_status("%d new systems from %s" % (n, ", ".join(used) or "no source"))


def _rebuild_plan() -> None:
    if not (ST.center and ST.planner):
        return
    with ST.lock:
        plan = ST.planner.build(
            ST.center, ST.radius,
            masscodes=get_masscodes(),
            probe_depth=max(0, cfg_int(CFG["probe_depth"], 2)),
            include_empty=cfg_bool(CFG["include_empty"], True),
            include_tasks=cfg_bool(CFG["include_tasks"], True),
            origin=ST.cur_pos)
        ST.stats = ST.planner.statistics(plan)
    ST.flight = plan["flight"]
    ST.probe = plan["probe"]
    ST.plan_counts = plan["counts"]
    ST.plan_info = Planner.summary(plan)
    ST.stats_lines = Planner.stats_lines(ST.stats)
    _ui(_stats_window_refresh)
    try:
        with ST.lock:
            tri = tritium_systems(ST.db, ST.center, ST.radius)
        if tri:
            ST.stats_lines.append(
                "tritium: %d system%s with icy rings here (nearest %s at %.0f ly)"
                % (len(tri), "" if len(tri) == 1 else "s",
                   tri[0]["name"], min(t["dist"] for t in tri)))
        else:
            ST.stats_lines.append("tritium: none found in this sphere yet")
    except Exception:
        logger.exception("tritium summary failed")
    if ST.fuel.capacity:
        ST.stats_lines.append(ST.fuel.summary())
    for line in ST.stats_lines:
        logger.info("stats | %s", line)
    if ST.stats.get("finished") and not ST.finished_announced:
        ST.finished_announced = True
        logger.info("AREA COMPLETE: sphere r=%.0f ly around %s is exhausted",
                    ST.radius, ST.start_system)
        _set_status("AREA COMPLETE - move on, next sphere >= %.0f ly away"
                    % (ST.radius * 2.0))
    logger.info("plan rebuilt: %d flight targets, %d probes | %s",
                len(ST.flight), len(ST.probe), ST.plan_counts)


def _current_system_from_journal() -> Optional[Tuple[str, int, Tuple[float, float, float]]]:
    """
    Read the current system straight out of the newest journal file.

    EDMC synthesises StartUp when the game is already running, so a session
    that begins parked in a system never sees FSDJump or Location and the
    plugin would otherwise have no idea where it is. Scanning the newest
    journal backwards for the last location event answers it exactly - name,
    id64 and coordinates, no guessing.
    """
    import glob
    d = _journal_dir()
    if not d:
        return None
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))
    for fn in reversed(files[-3:]):
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line or '"StarSystem"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") not in ("FSDJump", "Location", "CarrierJump"):
                continue
            pos = e.get("StarPos") or []
            if e.get("StarSystem") and e.get("SystemAddress") and len(pos) >= 3:
                return (e["StarSystem"], e["SystemAddress"],
                        (pos[0], pos[1], pos[2]))
    return None


def _resolve_current_system() -> None:
    """Establish the current system if no jump has been seen this session."""
    if ST.cur_id64 or not ST.db:
        return
    found = _current_system_from_journal()
    if found:
        ST.cur_system, ST.cur_id64, ST.cur_pos = found
        logger.info("current system read from journal: %s", ST.cur_system)
        with ST.lock:
            ST.db.upsert(ST.cur_system, ST.cur_pos[0], ST.cur_pos[1],
                         ST.cur_pos[2], id64=ST.cur_id64, quality=Q_JOURNAL,
                         source="journal", visited=True)
        return
    with ST.lock:
        row = ST.db.cx.execute(
            "SELECT name, id64, x, y, z FROM systems WHERE visited=1 "
            "AND id64 IS NOT NULL ORDER BY visited_ts DESC LIMIT 1").fetchone()
    if row:
        ST.cur_system = row["name"]
        ST.cur_id64 = row["id64"]
        if row["x"] is not None:
            ST.cur_pos = (row["x"], row["y"], row["z"])
        logger.info("current system assumed from history: %s", ST.cur_system)


_route_lock = threading.Lock()
_route_last: List[float] = [0.0]
_route_pending = [False]


def _request_route(delay: float = 1.5) -> None:
    """
    Ask for a route rebuild, at most one at a time.

    A single arrival fires several events in quick succession - Location, the
    FSS sweep, then every SAAScanComplete - and each one used to trigger its
    own rebuild. The log showed four identical runs for one system. This
    collapses a burst into a single run shortly after it ends.
    """
    with _route_lock:
        if _route_pending[0]:
            _route_last[0] = time.time()
            return
        _route_pending[0] = True
        _route_last[0] = time.time()

    def waiter():
        while True:
            with _route_lock:
                quiet = time.time() - _route_last[0]
            if quiet >= delay:
                break
            time.sleep(0.25)
        with _route_lock:
            _route_pending[0] = False
        try:
            _rebuild_route()
        except Exception:
            logger.exception("route rebuild failed")

    threading.Thread(target=waiter, daemon=True, name="SHBOX-route").start()


def _rebuild_route() -> None:
    """Order the bodies of the current system into a short in-system route."""
    ST.route = None
    ST.route_lines = []
    _resolve_current_system()
    if not (ST.db and ST.cur_id64):
        logger.info("route | no current system known yet")
        return
    with ST.lock:
        rows = ST.db.bodies_of(ST.cur_id64)
    if not rows:
        # Nothing stored for this system - the scans may predate the plugin or
        # have happened while it was not running. Replay the recent journals
        # once and try again.
        logger.info("route | no bodies stored for %s, replaying recent journals",
                    ST.cur_system)
        d = _journal_dir()
        if d:
            with ST.lock:
                res = ST.db.import_journals(d, max_files=6)
            logger.info("route | replayed %s", res)
            with ST.lock:
                rows = ST.db.bodies_of(ST.cur_id64)
    if not rows:
        logger.info("route | %s has no scanned bodies yet - run a system scan",
                    ST.cur_system)
        _ui(_route_window_refresh)
        return
    bodies = bodies_from_rows(rows, now=time.time())
    for b in bodies.values():
        b.short = shorten(b.name, ST.cur_system or "")
    filters = [F_ALL] if cfg_bool(CFG["route_all"], False) else get_filters()
    route = plan_route(ST.cur_system or "", bodies, model=ST.cost_model,
                       filters=filters)
    ST.route_full = False
    if not route.stops and F_ALL not in filters:
        # Nothing outstanding - show the complete tour anyway rather than an
        # empty window. Useful when revisiting a system, and it makes clear
        # that the system really is finished rather than unknown.
        route = plan_route(ST.cur_system or "", bodies, model=ST.cost_model,
                           filters=[F_ALL])
        ST.route_full = True
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
    _ui(_route_window_refresh)


# ---------------------------------------------------------------------------
# In-system route window
# ---------------------------------------------------------------------------

_MONO_FAMILY = "Consolas" if sys.platform == "win32" else "TkFixedFont"
_MONO = (_MONO_FAMILY, 9)
_FONT_GROUP = (_MONO_FAMILY, 11, "bold")   # planetary system header
_FONT_BODY = (_MONO_FAMILY, 9)             # a planet
_FONT_MOON = (_MONO_FAMILY, 8)             # a moon, visually subordinate
_FONT_SMALL = (_MONO_FAMILY, 8)
# Markers that make the hierarchy readable at a glance
_MARK_PLANET = "\u25cf"    # filled circle - a planetary system heading
_MARK_BODY = "\u25cb"      # hollow circle - the planet itself
_MARK_MOON = "\u00b7"      # middle dot - a moon of that planet
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


def _theme_colours() -> Dict[str, str]:
    """
    Work out the host application's colours.

    EDMC's theme module registers widgets it created itself; a Toplevel a
    plugin opens is not part of that, and Tk gives new widgets its own
    defaults - black text on a light grey button, which is unreadable on the
    dark theme. So the colours are read live from the plugin frame, which does
    follow whatever theme is active.

    EDMC's own config is consulted first, because the frame can report an
    empty string before it has been mapped; the frame is the fallback, and a
    dark default the last resort.
    """
    bg = fg = ""

    # 1. EDMC's theme setting, if it exposes one
    try:
        idx = config.get_int("theme")
    except Exception:
        idx = None
    if idx is not None:
        try:
            bg = cfg_str("dark_background") if idx else ""
            fg = cfg_str("dark_text") if idx else ""
        except Exception:
            bg = fg = ""

    # 2. live values off the plugin frame
    if not bg and _frame is not None:
        for widget in (_frame, getattr(_frame, "master", None)):
            if widget is None:
                continue
            try:
                v = str(widget.cget("background"))
            except Exception:
                continue
            if v:
                bg = v
                break
    if not fg and _frame is not None:
        try:
            for child in _frame.winfo_children():
                try:
                    v = str(child.cget("foreground"))
                except Exception:
                    continue
                if v:
                    fg = v
                    break
        except Exception:
            pass

    # 3. a readable pair rather than Tk's defaults
    if not bg:
        bg = "#000000"
    if not fg or fg == bg:
        fg = "#ffffff" if _is_dark(bg) else "#000000"
    return {"bg": bg, "fg": fg}


def _is_dark(colour: str) -> bool:
    """Rough luminance test, so a fallback foreground is at least readable."""
    try:
        c = colour.strip()
        if c.startswith("#") and len(c) == 7:
            r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
            return (0.299 * r + 0.587 * g + 0.114 * b) < 128
    except Exception:
        pass
    return True


def _dim(colour: str, factor: float = 0.45) -> str:
    """A muted version of a colour, for disabled controls and finished stops."""
    try:
        c = colour.strip()
        if c.startswith("#") and len(c) == 7:
            r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
            return "#%02x%02x%02x" % (int(r * factor), int(g * factor),
                                      int(b * factor))
    except Exception:
        pass
    return "#7a7a7a"


def _apply_theme(widget, colours: Dict[str, str], is_text: bool = False,
                 is_button: bool = False) -> None:
    """
    Paint one widget in the host application's colours.

    Buttons need more than background and foreground. Tk keeps separate
    colours for the pressed and the disabled state, and on Windows a button
    left at its defaults draws black text on whatever background it was given
    - which is exactly the unreadable combination on a dark theme. All four
    are therefore set together.
    """
    bg, fg = colours.get("bg"), colours.get("fg")
    opts = {}
    if bg:
        opts["background"] = bg
    if (is_text or is_button) and fg:
        opts["foreground"] = fg
    if is_button:
        if bg:
            opts["activebackground"] = bg
            opts["highlightbackground"] = bg
        if fg:
            opts["activeforeground"] = fg
            opts["disabledforeground"] = _dim(fg)
        opts["relief"] = tk.FLAT
        opts["borderwidth"] = 1
        opts["highlightthickness"] = 1
    if not opts:
        return
    try:
        widget.configure(**opts)
        return
    except Exception:
        pass
    # some option combinations are rejected per widget class - set them singly
    for key, value in opts.items():
        try:
            widget.configure(**{key: value})
        except Exception:
            continue


def _theme_tree(widget, colours: Dict[str, str]) -> None:
    """Apply the colours to a widget and everything below it."""
    cls = widget.__class__.__name__
    _apply_theme(widget, colours,
                 is_text=cls in ("Label", "Checkbutton", "Entry"),
                 is_button=cls in ("Button", "Menubutton"))
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for child in children:
        _theme_tree(child, colours)


def _toggle_route_window() -> None:
    """Open or close the route window."""
    global _route_win
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
    _refresh()


def _route_window_open() -> None:
    """
    A separate window listing the in-system route.

    Copy and paste is pointless in here: bodies are picked in the system map,
    not typed. So the window is a checklist - tick a stop off and the remaining
    time updates. Only the external jump target is ever copied, from the main
    panel.
    """
    global _route_win, _route_head, _route_body
    if _frame is None:
        return
    _route_win = tk.Toplevel(_frame)
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
              command=lambda: _run_async(_rebuild_route, label="route")).pack(
        side=tk.LEFT)
    tk.Button(bar, text="map", command=_route_map_toggle).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="reset ticks", command=_route_reset).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="map", command=_toggle_map).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="size", command=_cycle_map_size).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="review", command=_route_review).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar, text="close", command=_route_window_close).pack(
        side=tk.LEFT, padx=(4, 0))

    _route_theme()
    _route_window_refresh()
    _fit_to_screen(_route_win)
    _refresh()


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
    _theme_tree(_route_win, _theme_colours())


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

    # Pick the projection plane from the data instead of assuming one.
    #
    # Orbits in a system are close to coplanar, but that plane is not the same
    # one in every system: measured over real systems, five of six have z
    # within a few light seconds of zero while x and y span thousands, and one
    # binary is the other way round. Projecting on a fixed X/Z therefore
    # collapsed most systems onto a single horizontal line. Dropping whichever
    # axis varies least keeps the spread in every case.
    def _spread(idx: int) -> float:
        vals = [p[idx] for p in pts]
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))

    spreads = [(_spread(i), i) for i in range(3)]
    flattest = min(spreads)[1]
    ax, ay = [i for i in range(3) if i != flattest][:2]

    rmax = max(math.sqrt(p[ax] ** 2 + p[ay] ** 2) for p in pts) or 1.0

    def project(p) -> Tuple[float, float]:
        u, v = p[ax], p[ay]
        r = math.sqrt(u * u + v * v)
        if r < 1e-9:
            return (cx, cy)
        # log radial scale so moons and outer giants both stay visible
        rr = math.log10(1.0 + r) / math.log10(1.0 + rmax)
        return (cx + (u / r) * rr * span, cy + (v / r) * rr * span)

    col = _theme_colours()
    fg = col.get("fg") or "#ff8000"
    dim = col.get("bg") or "#101010"

    # range rings
    for frac, lbl in ((1.0, "%.0f LS" % rmax), (0.5, "")):
        rr = math.log10(1.0 + rmax * frac) / math.log10(1.0 + rmax) * span
        _route_map.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                               outline=fg, width=1, dash=(2, 4))
        if lbl:
            _route_map.create_text(cx, cy - rr - 7, text=lbl, fill=fg,
                                   font=_FONT_SMALL)

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
                last_pos = project(st.body.pos)
                break

    # route legs
    prev = (cx, cy)
    for i, st in enumerate(route.stops):
        if not st.body.pos:
            continue
        p = project(st.body.pos)
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
        x, y = project(st.body.pos)
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
        x, y = project(st.body.pos)
        px, py, anchor = free_spot(x, y, 4.0)
        _route_map.create_text(px, py, text=st.body.short[:10], fill=fg,
                               anchor=anchor, font=_FONT_SMALL)

    if last_pos is not None:
        lx, ly = last_pos
        _route_map.create_oval(lx - 7, ly - 7, lx + 7, ly + 7,
                               outline=_MAP_LAST, width=2)
        _route_map.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                               fill=_MAP_LAST, outline=_MAP_LAST)
        _route_map.create_text(lx, ly + 12, text="last here", fill=_MAP_LAST,
                               font=_FONT_SMALL)


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
    _set_status("map size: %s" % nxt)


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
    _set_status("ticks cleared (%d)" % n)
    _route_window_refresh()
    _refresh()


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
            _route_progress_feedback()
            _ui(_route_window_refresh)
            _ui(_refresh)
            return


def _route_progress_feedback() -> None:
    """
    Compare the estimate against what actually happened.

    The first stop starts the clock. From then on the elapsed time is measured
    against the sum of the legs already ticked off, which is the only honest
    check the plugin can make on its own model - and it is the one that tells
    you whether the remaining minutes are worth anything.
    """
    route = ST.route
    if route is None or not ST.route_done:
        ST.route_feedback = ""
        return
    if ST.route_started is None:
        ST.route_started = time.time()
        ST.route_feedback = ""
        return
    elapsed = time.time() - ST.route_started
    planned = sum(s.leg_s for s in route.stops
                  if s.body.body_id in ST.route_done)
    if planned < 60 or elapsed < 60:
        ST.route_feedback = ""
        return
    ratio = elapsed / planned
    left = sum(s.leg_s for s in route.stops
               if s.body.body_id not in ST.route_done)
    ST.route_feedback = ("actual pace %.1fx the estimate - "
                         "remaining is more like %.0f min"
                         % (ratio, left * ratio / 60.0))
    logger.info("route | %s (elapsed %.0f min vs planned %.0f min)",
                ST.route_feedback, elapsed / 60.0, planned / 60.0)


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
        _route_progress_feedback()
    else:
        ST.route_done.discard(body_id)
    if ST.db and ST.cur_id64:
        try:
            with ST.lock:
                ST.db.set_route_done(ST.cur_id64, body_id, done)
        except Exception:
            logger.exception("could not store route tick")
    _route_window_refresh()
    _refresh()


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
    if _route_win is None or _route_body is None:
        return
    try:
        for w in _route_body.winfo_children():
            w.destroy()
    except Exception:
        pass
    _route_rows = []
    col = _theme_colours()

    route = ST.route
    if route is None or not route.stops:
        _route_head.set("%s\nnothing to fly here - scan the system first"
                        % (ST.cur_system or "no system"))
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
                _MARK_PLANET, st.body.short[:24], st.leg_ls,
                st.leg_s / 60.0, st.work)
            lone = tk.Label(row, text=text, anchor=tk.W, font=_FONT_GROUP)
            lone.pack(side=tk.LEFT)
            _apply_theme(row, col)
            _apply_theme(cb, col, is_text=True)
            _apply_theme(lone, col, is_text=True)
            _route_rows.append({"body_id": st.body.body_id, "var": var})
            continue
        # --- planet heading -------------------------------------------------
        hdr = tk.Frame(_route_body)
        hdr.grid(row=row_i, column=0, sticky=tk.EW, pady=(8 if row_i else 0, 1))
        row_i += 1
        moons = len(stops) - 1
        htxt = "%s  %s" % (_MARK_PLANET, label)
        if moons:
            htxt += "   +%d moon%s" % (moons, "" if moons == 1 else "s")
        if transfer >= 1.0:
            htxt += "   transfer %.0f LS, %.0f min" % (transfer,
                                                       stops[0].leg_s / 60.0)
        lbl = tk.Label(hdr, text=htxt, anchor=tk.W, font=_FONT_GROUP)
        lbl.pack(side=tk.LEFT)
        _apply_theme(hdr, col)
        _apply_theme(lbl, col, is_text=True)

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
            marker = _MARK_MOON if st.is_moon else _MARK_BODY
            text = "%s%s %-24s %7.0f LS %4.0f min  %s" % (
                indent, marker, st.body.short[:24], st.leg_ls,
                st.leg_s / 60.0, st.work)
            body_lbl = tk.Label(row, text=text, anchor=tk.W,
                                font=_FONT_MOON if st.is_moon else _FONT_BODY)
            body_lbl.pack(side=tk.LEFT)
            _apply_theme(row, col)
            _apply_theme(cb, col, is_text=True)
            _apply_theme(body_lbl, col, is_text=True)
            _route_rows.append({"body_id": st.body.body_id, "var": var})

    _route_theme()


def _measure_work(ev: str, entry: Dict[str, Any]) -> None:
    """
    Time the work at a body as it happens.

    These intervals are clean in a way supercruise timings are not: a surface
    scan is bracketed by arrival and SAAScanComplete, a sample by its own Log
    and Analyse events. Nothing can stretch them except the commander pausing,
    which the trimmed median then discards.
    """
    try:
        now = time.time()
        if ev == "SAAScanComplete":
            b = entry.get("BodyName")
            t0 = ST._arrive.pop(b, None) if b else None
            if t0 and 10 < now - t0 < 1800:
                ST.work_dss.append(now - t0)
        elif ev == "ScanOrganic":
            key = (entry.get("SystemAddress"), entry.get("Body"),
                   entry.get("Species"))
            kind = entry.get("ScanType")
            if kind in ("Log", "Sample"):
                ST._bio_log.setdefault(key, now)
            elif kind == "Analyse":
                t0 = ST._bio_log.pop(key, None)
                if t0 and 20 < now - t0 < 3600:
                    ST.work_bio.append(now - t0)
        total = len(ST.work_dss) + len(ST.work_bio)
        if total and total % 5 == 0:
            ST.cost_model = calibrate_work_from_journal(
                ST.work_dss, ST.work_bio, ST.work_approach, ST.cost_model)
            logger.info("work model recalibrated: %s", ST.cost_model.as_dict())
    except Exception:
        logger.exception("work measurement failed")


def _bootstrap_work_model() -> None:
    """Measure the work constants once from the existing journals."""
    import glob
    import calendar
    d = _journal_dir()
    if not d:
        return
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))[-30:]
    dss: List[float] = []
    bio: List[float] = []
    arrive: Dict[str, float] = {}
    blog: Dict[Tuple, float] = {}
    last_saa: Dict[int, float] = {}
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        ts = calendar.timegm(time.strptime(
                            e["timestamp"], "%Y-%m-%dT%H:%M:%SZ"))
                    except (ValueError, KeyError):
                        continue
                    v = e.get("event")
                    if v in ("ApproachBody", "SupercruiseExit"):
                        if e.get("Body"):
                            arrive[e["Body"]] = ts
                    elif v == "SAAScanComplete":
                        # Most mapping is done straight from supercruise with
                        # no ApproachBody at all, so the honest bracket is the
                        # gap between consecutive mappings in one system: it
                        # covers the transfer plus the probe run, which is
                        # exactly the per-body rate the estimate needs.
                        t0 = arrive.pop(e.get("BodyName"), None)
                        prev = last_saa.get(e.get("SystemAddress"))
                        if t0 and 10 < ts - t0 < 1800:
                            dss.append(ts - t0)
                        elif prev and 20 < ts - prev < 1800:
                            dss.append(ts - prev)
                        last_saa[e.get("SystemAddress")] = ts
                    elif v == "ScanOrganic":
                        key = (e.get("SystemAddress"), e.get("Body"),
                               e.get("Species"))
                        if e.get("ScanType") in ("Log", "Sample"):
                            blog.setdefault(key, ts)
                        elif e.get("ScanType") == "Analyse":
                            t0 = blog.pop(key, None)
                            if t0 and 20 < ts - t0 < 3600:
                                bio.append(ts - t0)
        except OSError:
            continue
    ST.work_dss, ST.work_bio = dss, bio
    before = ST.cost_model.as_dict()
    ST.cost_model = calibrate_work_from_journal(dss, bio, [], ST.cost_model)
    logger.info("work model from %d DSS and %d bio measurements: %s",
                len(dss), len(bio), ST.cost_model.as_dict())
    if before == ST.cost_model.as_dict():
        logger.info("work model unchanged - too few measurements yet")


def _bootstrap_session() -> None:
    """Establish fuel, work timings and last position from the journals."""
    try:
        _bootstrap_fuel()
    except Exception:
        logger.exception("fuel bootstrap failed")
    try:
        _bootstrap_work_model()
    except Exception:
        logger.exception("work model bootstrap failed")
    try:
        _bootstrap_last_body()
    except Exception:
        logger.exception("last position bootstrap failed")
    _ui(_refresh)


def _bootstrap_last_body() -> None:
    """
    Recover the last body we were at.

    The live position appears in no journal event, so the newest
    ApproachBody / SupercruiseExit / Touchdown is the closest thing to it.
    Read backwards so the first hit wins.
    """
    import glob
    d = _journal_dir()
    if not d:
        return
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))
    for fn in reversed(files[-3:]):
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line or '"BodyID"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") in ("ApproachBody", "SupercruiseExit",
                                  "Touchdown", "Liftoff",
                                  "SAAScanComplete") and e.get("BodyID") is not None:
                ST.last_body_id = e["BodyID"]
                ST.last_body_name = e.get("Body") or e.get("BodyName") or ""
                ST.last_body_sys = e.get("SystemAddress")
                logger.info("last known position: %s (body %d)",
                            ST.last_body_name or "?", ST.last_body_id)
                return
    logger.info("last position unknown - no body approach in recent journals")


def _bootstrap_fuel() -> None:
    """Read ship fuel figures out of the recent journals."""
    import glob
    d = _journal_dir()
    if not d:
        return
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))[-6:]
    used: List[Tuple[float, float]] = []
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    v = e.get("event")
                    if v == "Loadout":
                        if e.get("MaxJumpRange"):
                            ST.fuel.max_jump = float(e["MaxJumpRange"])
                        cap = (e.get("FuelCapacity") or {}).get("Main")
                        if cap:
                            ST.fuel.capacity = float(cap)
                    elif v == "FSDJump":
                        if e.get("FuelUsed") is not None:
                            used.append((float(e.get("JumpDist") or 0.0),
                                         float(e["FuelUsed"])))
                        if e.get("FuelLevel") is not None:
                            ST.fuel.level = float(e["FuelLevel"])
        except (OSError, TypeError, ValueError):
            continue
    ST.fuel.jumps = [(d, u) for d, u in used if d > 0.1 and u > 0.0]
    logger.info("fuel | %s", ST.fuel.summary())


def _plan_staging() -> None:
    """Work out where the carrier should go next, tritium permitting."""
    if not (ST.db and ST.planner and ST.center):
        _set_status("no active sphere")
        return
    with ST.lock:
        rows = best_staging(ST.db, ST.planner, ST.center, ST.radius,
                            get_masscodes())
    ST.staging = rows
    for line in staging_lines(rows):
        logger.info("carrier | %s", line)
    if rows:
        _set_status("next carrier spot: %s (%.0f ly, %d icy rings)"
                    % (rows[0]["name"], rows[0]["dist"], rows[0]["icy_rings"]))
    else:
        _set_status("no tritium system known far enough out yet")


def _recheck_route(reason: str) -> None:
    """
    After a pause, ask whether the planned order still holds.

    Bodies keep orbiting while the game is paused, landed or shut down. The
    effect is small over minutes - the worst case in the test data is 0.53 LS
    after 20 minutes - but it compounds: 3.2 LS after two hours and 15.2 LS
    after twelve, on a moon with a 32 hour period. Over an overnight break the
    near bodies of a tight system can genuinely reorder.

    So rather than rebuild blindly, the old and the new order are compared and
    the route is only replaced when it actually changed.
    """
    if not (ST.db and ST.cur_id64):
        return
    before = [s.body.body_id for s in ST.route.stops] if ST.route else []
    before_ls = ST.route.total_ls if ST.route else 0.0
    _rebuild_route()
    after = [s.body.body_id for s in ST.route.stops] if ST.route else []
    if not before or not after:
        return
    if before == after:
        logger.info("route | %s: order still optimal (%.0f LS)",
                    reason, before_ls)
        return
    delta = (ST.route.total_ls - before_ls)
    logger.info("route | %s: order changed, %.0f LS -> %.0f LS (%+.0f)",
                reason, before_ls, ST.route.total_ls, delta)
    _set_status("route re-ordered after %s (%+.0f LS)" % (reason, delta))


def _route_review() -> None:
    """
    Compare what actually happened against what the route suggested.

    The journal records every body you approached (ApproachBody) and every
    drop-out (SupercruiseExit), in order and with timestamps. Replaying that
    for the current system gives the real order flown, the real distance
    covered and the real time taken - which can be measured against the
    planned tour. That is honest feedback: not "you did it wrong", but "this
    is what the detour cost".
    """
    _run_async(_route_review_worker, label="review")


def _route_review_worker() -> None:
    if not (ST.db and ST.cur_id64 and ST.route and ST.route.stops):
        _set_status("no route to review")
        return
    visits = _actual_visits(ST.cur_id64)
    if not visits:
        logger.info("review | no approaches recorded for %s yet", ST.cur_system)
        _set_status("nothing flown here yet")
        return

    with ST.lock:
        rows = ST.db.bodies_of(ST.cur_id64)
    bodies = bodies_from_rows(rows)
    for b in bodies.values():
        b.short = shorten(b.name, ST.cur_system or "")
    resolve_positions(bodies)          # needed before any distance is measured
    by_name = {b.name: b for b in bodies.values()}

    # what was actually flown, in order, with real distances
    seq = [by_name[n] for n, _ in visits if n in by_name and by_name[n].pos]
    if len(seq) < 2:
        _set_status("only %d stop flown here so far" % len(seq))
        return
    actual_ls = 0.0
    prev = (0.0, 0.0, 0.0)
    for b in seq:
        actual_ls += math.dist(prev, b.pos)
        prev = b.pos
    actual_s = visits[-1][1] - visits[0][1]

    # the best possible tour over exactly those bodies
    subset = {b.body_id: b for b in seq}
    ideal = plan_route(ST.cur_system or "", subset, model=ST.cost_model,
                       only_work=False)
    ideal_ls = ideal.total_ls

    over = (100.0 * (actual_ls - ideal_ls) / ideal_ls) if ideal_ls > 1 else 0.0
    switches = _count_switches(seq, bodies)

    logger.info("review | %s: %d bodies flown", ST.cur_system, len(seq))
    logger.info("review | flown %.0f LS in %.0f min, %d planet changes",
                actual_ls, actual_s / 60.0, switches)
    logger.info("review | best possible over the same bodies %.0f LS (%+.0f%%)",
                ideal_ls, over)
    logger.info("review | order flown: %s",
                " -> ".join(b.short for b in seq[:12])
                + (" ..." if len(seq) > 12 else ""))
    if over > 25:
        logger.info("review | a shorter order existed: %s",
                    " -> ".join(s.body.short for s in ideal.stops[:12]))
        _set_status("review: %.0f LS flown, %.0f%% above the best order "
                    "(details in log)" % (actual_ls, over))
    else:
        _set_status("review: %.0f LS flown, within %.0f%% of the best order"
                    % (actual_ls, max(0.0, over)))


def _actual_visits(sys_id64: int) -> List[Tuple[str, float]]:
    """
    (body name, unix time) for every body approached in this system, in order.

    Read straight from the journals rather than kept in memory, so it also
    works for a system flown before the plugin was running.
    """
    import glob
    import calendar
    d = _journal_dir()
    if not d:
        return []
    files = sorted(glob.glob(os.path.join(d, "Journal.*.log"))
                   + glob.glob(os.path.join(d, "Journal_*.log")))[-8:]
    out: List[Tuple[str, float]] = []
    seen = set()
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"Body' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("SystemAddress") != sys_id64:
                        continue
                    if e.get("event") not in ("ApproachBody", "SupercruiseExit",
                                              "SAAScanComplete"):
                        continue
                    nm = e.get("Body") or e.get("BodyName")
                    if not nm or nm in seen:
                        continue
                    try:
                        ts = calendar.timegm(time.strptime(
                            e["timestamp"], "%Y-%m-%dT%H:%M:%SZ"))
                    except (KeyError, ValueError):
                        continue
                    seen.add(nm)
                    out.append((nm, float(ts)))
        except OSError:
            continue
    out.sort(key=lambda p: p[1])
    return out


def _count_switches(seq, bodies) -> int:
    """How often the flown order moved from one planetary system to another."""
    from sysroute import group_label
    n = 0
    last = None
    for b in seq:
        g = group_label(b)
        if last is not None and g != last:
            n += 1
        last = g
    return n
def _start_survey() -> None:
    """
    Free start  - the sphere is centred on the current system.
    Carrier start - the sphere is centred on the remembered fleet carrier,
                    so it stays put while you range around it.
    """
    use_carrier = bool(_carrier_var.get()) if _carrier_var else False
    if use_carrier:
        if not (ST.carrier and ST.carrier.get("coords")):
            _set_status("no carrier position known - dock at it once")
            return
        center = tuple(ST.carrier["coords"])
        label = ST.carrier["system"]
        origin_kind = "carrier"
    else:
        if not ST.cur_pos:
            _set_status("position unknown - jump first")
            return
        center = ST.cur_pos
        label = ST.cur_system
        origin_kind = "free"

    if ST.active and ST.center and ST.center != center:
        logger.info("survey re-centred: %s -> %s", ST.start_system, label)

    radius = float(_radius_var.get()) if _radius_var else 50.0

    with ST.lock:
        ov = ST.db.sphere_overlap(center, radius)
    if ov["volume_pct"] > 0.5:
        msg = ("overlap %.0f%% with earlier spheres (worst %s at %.0f ly, %.0f%%); "
               "%d of %d known systems already visited"
               % (ov["volume_pct"], ov["worst_label"] or "-",
                  ov["worst_distance"] or 0.0, ov["worst_pct"],
                  ov["visited"], ov["known"]))
        logger.info(msg)
        _set_status("overlap %.0f%% | %d systems already visited | move %.0f ly for none"
                    % (ov["volume_pct"], ov["visited"], ov["clear_distance"]))
    else:
        logger.info("fresh sphere, no overlap with earlier work")

    ST.center = center
    ST.start_system = label
    ST.radius = radius
    ST.active = True
    ST.finished_announced = False
    with ST.lock:
        ST.sphere_id = ST.db.record_sphere(center, radius, label, origin_kind)
        ST.db.save_survey(True, label, center, radius, get_masscodes())
    _run_async(_start_worker, label="starting survey")


def _start_worker() -> None:
    _fetch_sources()
    _rebuild_plan()


def _stop_survey() -> None:
    ST.active = False
    if ST.sphere_id and ST.stats.get("finished"):
        with ST.lock:
            ST.db.close_sphere(ST.sphere_id)
    with ST.lock:
        ST.db.save_survey(False, ST.start_system, ST.center, ST.radius, get_masscodes())
    ST.flight = []
    ST.probe = []
    _refresh()


# ============================================================================
# Target logic
# ============================================================================

def current_flight() -> Optional[Target]:
    return ST.flight[0] if ST.flight else None


def current_probe() -> Optional[Target]:
    return ST.probe[0] if ST.probe else None


def _probe_absent() -> None:
    """
    Button: the candidate does not exist according to the galaxy map.

    Because n2 runs contiguously from 0, a miss at -n proves that -n, -n-1,
    -n-2 ... do not exist either. The whole boxel is closed at once and every
    queued candidate above that number is dropped immediately.
    """
    t = current_probe()
    if not t:
        return
    with ST.lock:
        ST.db.mark_absent(t.name)
    dropped = 0
    if t.boxel_key is not None and t.n2 is not None:
        keep = []
        for q in ST.probe:
            if q.boxel_key == t.boxel_key and q.n2 is not None and q.n2 >= t.n2:
                dropped += 1
                continue
            keep.append(q)
        ST.probe = keep
    else:
        ST.probe.pop(0)
    logger.info("%s does not exist - boxel %s closed, %d further candidates dropped",
                t.name, t.boxel_key, max(0, dropped - 1))
    _set_status("%s does not exist - boxel closed (%d candidates dropped)"
                % (t.name, max(0, dropped - 1)))
    _refresh()
    _copy_probe()


def _boxel_done() -> None:
    """
    The galaxy map list for this boxel is fully accounted for. Close it in one
    go - every remaining candidate of that boxel leaves the queue. This is the
    cheap path: one prefix search plus one click retires a whole boxel.
    """
    t = current_probe()
    if not t or not t.boxel_key:
        return
    with ST.lock:
        end = ST.db.close_boxel(t.boxel_key)
    key = t.boxel_key
    before = len(ST.probe)
    ST.probe = [q for q in ST.probe if q.boxel_key != key]
    dropped = before - len(ST.probe)
    logger.info("boxel %s closed at n2=%d by hand, %d candidates dropped",
                key, end, dropped)
    _set_status("boxel %s done (%d candidates dropped)" % (key, dropped))
    _refresh()
    _copy_probe()


def _copy_prefix() -> None:
    """Copy the boxel search prefix - one paste lists the whole boxel."""
    t = current_probe()
    if t and t.boxel_key:
        _copy(t.boxel_key + "-")
    else:
        _set_status("no boxel prefix for this candidate")


def _probe_skip() -> None:
    if ST.probe:
        ST.probe.append(ST.probe.pop(0))
    _refresh()
    _copy_probe()


def _flight_skip() -> None:
    if ST.flight:
        ST.flight.append(ST.flight.pop(0))
    _refresh()
    _copy_flight()


def _copy(text: str) -> None:
    if not _frame or not text:
        return
    try:
        _frame.clipboard_clear()
        _frame.clipboard_append(text)
        _frame.update_idletasks()
        _set_status("copied: %s" % text)
    except Exception as e:
        logger.warning("clipboard: %s", e)


def _copy_flight() -> None:
    if cfg_bool(CFG["autocopy"], True):
        t = current_flight()
        if t:
            _copy(t.name)


def _copy_carrier() -> None:
    """Put the carrier system on the clipboard - the way home."""
    if ST.carrier and ST.carrier.get("system"):
        _copy(ST.carrier["system"])
    else:
        _set_status("no carrier system remembered yet")


_stats_win: Optional[tk.Toplevel] = None
_stats_body: Optional[tk.Frame] = None
_stats_scroll: Optional[tk.Canvas] = None


def _toggle_stats_window() -> None:
    global _stats_win
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
    _refresh()


def _stats_window_open() -> None:
    """Statistics in their own window, as tables, in the host's colours."""
    global _stats_win, _stats_body
    if _frame is None:
        return
    _stats_win = tk.Toplevel(_frame)
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
              command=lambda: _run_async(_rebuild_plan, label="stats")).pack(
        side=tk.LEFT)
    tk.Button(bar, text="close", command=_stats_window_close).pack(
        side=tk.LEFT, padx=(4, 0))
    _stats_window_refresh()
    _fit_to_screen(_stats_win)
    _refresh()


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
    col = _theme_colours()
    row_i = 0

    def table(title: str, rows: List[Tuple[str, str]]) -> None:
        nonlocal row_i
        head = tk.Label(_stats_body, text=title, anchor=tk.W, font=_FONT_GROUP)
        head.grid(row=row_i, column=0, columnspan=2, sticky=tk.W,
                  pady=(10 if row_i else 0, 2))
        _apply_theme(head, col, is_text=True)
        row_i += 1
        for label, value in rows:
            a = tk.Label(_stats_body, text="  " + label, anchor=tk.W, font=_MONO)
            b = tk.Label(_stats_body, text=value, anchor=tk.W, font=_MONO)
            a.grid(row=row_i, column=0, sticky=tk.W, padx=(8, 16))
            b.grid(row=row_i, column=1, sticky=tk.W)
            _apply_theme(a, col, is_text=True)
            _apply_theme(b, col, is_text=True)
            row_i += 1

    if ST.stats:
        for title, rows in Planner.stats_table(ST.stats):
            table(title, rows)

    # this sphere, in time
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
    if sphere_rows:
        table("This sphere", sphere_rows)

    # what it paid
    try:
        with ST.lock:
            e = ST.db.earnings()
        if e["sales"]:
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
            table("Earnings", rows)
    except Exception:
        logger.exception("earnings summary failed")

    # everything ever
    try:
        with ST.lock:
            lt = ST.db.lifetime()
        table("All time", [
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
        ])
    except Exception:
        logger.exception("lifetime statistics failed")

    _theme_tree(_stats_win, col)


def _toggle_stats() -> None:
    show = not cfg_bool(CFG["show_stats"], False)
    cfg_set(CFG["show_stats"], show)
    _refresh()


def _copy_probe() -> None:
    t = current_probe()
    if t:
        _copy(t.name)


def _resort_queues() -> None:
    """Re-rank both queues by distance from the commander's current position."""
    if not ST.cur_pos:
        return
    for q in (ST.flight, ST.probe):
        set_origin(q, ST.cur_pos)
        q.sort(key=lambda t: (int(t.dist_origin // 5), t.dist_origin))


def _prune_queues() -> None:
    """Drop completed targets from the head of both queues."""
    if not ST.db:
        return
    changed = False
    with ST.lock:
        while ST.flight:
            t = ST.flight[0]
            row = ST.db.system(t.name)
            done = False
            if t.kind == K_NEW:
                done = row is not None and bool(row["visited"])
            elif row is not None and row["id64"]:
                p = ST.db.system_progress(row["id64"])
                if t.kind == K_SCAN:
                    done = p["fss_complete"] or (
                        p["body_count"] and p["scanned"] >= p["body_count"])
                elif t.kind == K_DSS:
                    done = not p["dss_open"]
                elif t.kind == K_BIO:
                    done = not p["bio_open"]
            if not done:
                break
            ST.flight.pop(0)
            changed = True
        while ST.probe and ST.db.system(ST.probe[0].name) is not None:
            ST.probe.pop(0)
            changed = True
    if changed:
        _refresh()


# ============================================================================
# Journal / status
# ============================================================================

def journal_entry(cmdr: str, is_beta: bool, system: str, station: str,
                  entry: Dict[str, Any], state: Dict[str, Any]) -> None:
    if not ST.db:
        return
    ev = entry.get("event")
    try:
        # EDMC enriches NavRoute with the full Route array
        if ev == "NavRoute" and not cfg_bool(CFG["harvest_navroute"], True):
            return

        with ST.lock:
            ST.db.ingest_journal_event(entry)

        if ev == "SupercruiseEntry":
            ST._sc_start = (time.time(), 0.0)

        elif ev == "SupercruiseExit":
            if ST._sc_start and ST.cur_id64:
                dt = time.time() - ST._sc_start[0]
                with ST.lock:
                    rows = {r["name"]: r for r in ST.db.bodies_of(ST.cur_id64)}
                b = rows.get(entry.get("Body"))
                if b is not None and b["arrival_ls"] and 5 < dt < 3600:
                    ST.sc_segments.append((float(b["arrival_ls"]), dt))
                    if len(ST.sc_segments) % 8 == 0:
                        ST.cost_model = calibrate_from_journal(ST.sc_segments)
                        logger.info("supercruise model recalibrated: %s",
                                    ST.cost_model.as_dict())
            ST._sc_start = None

        if ev in ("FSDJump", "CarrierJump"):
            if ST._sys_enter is not None:
                spent = (time.time() - ST._sys_enter) / 60.0
                if 0.5 < spent < 180.0:      # ignore pauses and instant hops
                    ST.sys_minutes.append(spent)
                    del ST.sys_minutes[:-60]
            ST._sys_enter = time.time()

        if ev == "FSDJump" and entry.get("FuelUsed") is not None:
            try:
                ST.fuel.add_jump(entry.get("JumpDist"),
                                 entry.get("FuelUsed"))
                if entry.get("FuelLevel") is not None:
                    ST.fuel.level = float(entry["FuelLevel"])
                w = ST.fuel.warning()
                if w:
                    logger.info("fuel | %s", w)
            except (TypeError, ValueError):
                pass

        if ev in ("FSDJump", "Location", "CarrierJump"):
            if entry.get("SystemAddress") != ST.cur_id64:
                ST.route_done.clear()
                ST.route_started = None
                ST.route_feedback = ""
            ST.cur_system = entry.get("StarSystem")
            ST.cur_id64 = entry.get("SystemAddress")
            pos = entry.get("StarPos")
            if pos and len(pos) >= 3:
                ST.cur_pos = (pos[0], pos[1], pos[2])
            if ST.active:
                _prune_queues()
                _resort_queues()
                _ui(_copy_flight)
            _request_route()
            _ui(_refresh)

        elif ev in ("CarrierJump", "CarrierLocation", "CarrierStats") or (
                ev == "Docked" and entry.get("StationType") == "FleetCarrier"):
            with ST.lock:
                ST.carrier = ST.db.get_carrier()
            if ST.carrier:
                logger.info("fleet carrier now at %s", ST.carrier["system"])
                _set_status("carrier: %s" % ST.carrier["system"])
            _ui(_refresh)

        elif ev in ("ApproachBody", "Touchdown"):
            _route_auto_tick(entry.get("Body") or entry.get("BodyName"),
                             "approach" if ev == "ApproachBody" else "landed")

        elif ev == "Loadout":
            mj = entry.get("MaxJumpRange")
            if mj:
                ST.max_jump = float(mj)
                ST.fuel.max_jump = float(mj)
            cap = (entry.get("FuelCapacity") or {}).get("Main")
            if cap:
                ST.fuel.capacity = float(cap)

        elif ev == "StartUp":
            if entry.get("StarSystem"):
                ST.cur_system = entry["StarSystem"]
                ST.cur_id64 = entry.get("SystemAddress") or ST.cur_id64
                pos = entry.get("StarPos")
                if pos and len(pos) >= 3:
                    ST.cur_pos = (pos[0], pos[1], pos[2])
            _run_async(_recheck_route, "game restart", label="route recheck")
            route = state.get("NavRoute") if state else None
            if route and cfg_bool(CFG["harvest_navroute"], True):
                with ST.lock:
                    ST.db.ingest_journal_event({"event": "NavRoute",
                                                "Route": route.get("Route", [])})

        elif ev == "Liftoff":
            # Lifting off usually ends a pause spent on the surface.
            _run_async(_recheck_route, "lift-off", label="route recheck")

        elif ev == "ApproachBody":
            if entry.get("Body"):
                ST._arrive[entry["Body"]] = time.time()
            if entry.get("BodyID") is not None:
                ST.last_body_id = entry["BodyID"]
                ST.last_body_name = entry.get("Body") or ""
                ST.last_body_sys = entry.get("SystemAddress") or ST.cur_id64
                _ui(_route_window_refresh)

        elif ev in ("Scan", "SAAScanComplete", "SAASignalsFound", "FSSBodySignals",
                    "FSSDiscoveryScan", "FSSAllBodiesFound", "ScanOrganic"):
            _measure_work(ev, entry)
            if not ST.cur_id64 and entry.get("SystemAddress"):
                ST.cur_id64 = entry["SystemAddress"]
                ST.cur_system = (entry.get("StarSystem") or entry.get("SystemName")
                                 or ST.cur_system)
            if ST.active:
                _prune_queues()
            if ev in ("SAAScanComplete", "ScanOrganic"):
                _route_auto_tick(entry.get("BodyName") or entry.get("Body"),
                                 "mapped" if ev == "SAAScanComplete" else "sampled")
            if ev in ("FSSAllBodiesFound", "SAAScanComplete", "ScanOrganic",
                      "FSSBodySignals", "SAASignalsFound"):
                _request_route()
            _ui(_refresh)

        elif ev == "FSDTarget":
            nm = entry.get("Name")
            t = current_probe()
            if t and nm == t.name:
                _set_status("confirmed: %s" % nm)
                if ST.active:
                    _prune_queues()
            _ui(_refresh)

    except Exception:
        logger.exception("journal_entry(%s) failed", ev)


def dashboard_entry(cmdr: str, is_beta: bool, entry: Dict[str, Any]) -> None:
    """Status.json. The Destination field carries the id64 of any selected target."""
    if not ST.db or not cfg_bool(CFG["harvest_destination"], True):
        return
    try:
        fuel = entry.get("Fuel") or {}
        if fuel.get("FuelMain") is not None:
            try:
                ST.fuel.level = float(fuel["FuelMain"])
            except (TypeError, ValueError):
                pass
        dest = entry.get("Destination")
        if not dest:
            return
        a = dest.get("System")
        if not a or a == ST.last_dest_id64:
            return
        ST.last_dest_id64 = a
        with ST.lock:
            new = ST.db.ingest_status_destination(dest)
        if new:
            logger.info("new system confirmed via target selection: %s", new)
            _set_status("confirmed: %s" % new)
            if ST.active:
                _prune_queues()
        _ui(_refresh)
    except Exception:
        logger.exception("dashboard_entry failed")


# ============================================================================
# User interface
# ============================================================================

def _ui(fn) -> None:
    if _frame:
        try:
            _frame.after(0, fn)
        except Exception:
            pass


def _set_status(txt: str) -> None:
    ST.status = txt
    if _v_status:
        _ui(lambda: _v_status.set(txt))


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """
    The main panel, kept deliberately small.

    EDMC's window is shared with every other plugin, so this shows only what
    you act on between jumps: the next flight target, the next name to check,
    and where you are. Counters, fuel, statistics and the route list all live
    in their own windows, reachable from one row of buttons.
    """
    global _frame, _v_status, _v_target, _v_kind, _v_sys, _v_queue, _v_probe
    global _btn_start, _btn_absent, _btn_skip, _radius_var
    global _btn_fc, _btn_stats, _lbl_stats, _v_stats, _carrier_var
    global _btn_boxel, _btn_prefix, _btn_next, _v_route, _lbl_route, _btn_route
    global _v_fuel, _lbl_queue, _lbl_fuel

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)

    _v_status = tk.StringVar(value="ready")
    _v_target = tk.StringVar(value="-")
    _v_kind = tk.StringVar(value="survey inactive")
    _v_sys = tk.StringVar(value="-")
    _v_probe = tk.StringVar(value="-")
    _v_queue = tk.StringVar(value="")
    _v_stats = tk.StringVar(value="")
    _v_route = tk.StringVar(value="")
    _v_fuel = tk.StringVar(value="")
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
    lp.bind("<Button-1>", lambda e: _copy_probe())

    # 3  current system
    tk.Label(_frame, text="Here").grid(row=3, column=0, sticky=tk.W)
    tk.Label(_frame, textvariable=_v_sys, anchor=tk.W).grid(
        row=3, column=1, sticky=tk.EW)

    # 4  one row of buttons - everything else opens a window
    bar = tk.Frame(_frame)
    bar.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(3, 0))
    _btn_start = tk.Button(bar, text="Start", width=6, command=_on_start)
    _btn_start.pack(side=tk.LEFT)
    ttk.OptionMenu(bar, _radius_var, _radius_var.get(), *RADIUS_CHOICES).pack(
        side=tk.LEFT, padx=(3, 4))
    _btn_next = tk.Button(bar, text="copy", width=6, command=_copy_flight_click)
    _btn_next.pack(side=tk.LEFT)
    _btn_route = tk.Button(bar, text="route", width=6,
                           command=_toggle_route_window)
    _btn_route.pack(side=tk.LEFT, padx=(3, 0))
    _btn_stats = tk.Button(bar, text="info", width=6,
                           command=_toggle_stats_window)
    _btn_stats.pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(bar, text="probe", width=6,
              command=_toggle_probe_window).pack(side=tk.LEFT, padx=(3, 0))
    tk.Button(bar, text="mining", width=7,
              command=_toggle_mining_window).pack(side=tk.LEFT, padx=(3, 0))

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

    _refresh()
    theme.update(_frame)
    return _frame


# ---------------------------------------------------------------------------
# Probe window - the galaxy map checking controls, out of the main panel
# ---------------------------------------------------------------------------

_probe_win: Optional[tk.Toplevel] = None
_probe_head: Optional[tk.StringVar] = None


# ---------------------------------------------------------------------------
# Mining window - find a ring again, months later
# ---------------------------------------------------------------------------

_mine_win: Optional[tk.Toplevel] = None
_mine_body: Optional[tk.Frame] = None
_mine_mat: Optional[tk.StringVar] = None


def _toggle_mining_window() -> None:
    global _mine_win
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


def _mining_window_open() -> None:
    """
    Every ring hotspot we have ever scanned, searchable by material.

    Ring scans report their mining materials in SAASignalsFound alongside the
    biological ones - "Platinum x3", "Low Temp. Diamonds x5". Those were being
    discarded. Keeping them turns the survey into a mining atlas: when the
    carrier needs tritium or you want a platinum run, the answer is already in
    your own data.
    """
    global _mine_win, _mine_body, _mine_mat
    if _frame is None or ST.db is None:
        return
    _mine_win = tk.Toplevel(_frame)
    _mine_win.title("SHBOXSEARCH - mining hotspots")
    _mine_win.protocol("WM_DELETE_WINDOW", _mining_window_close)
    try:
        _mine_win.attributes("-topmost", cfg_bool(CFG["route_top"], True))
    except Exception:
        pass

    with ST.lock:
        mats = ST.db.hotspot_materials()
    names = ["(all)"] + [(m["label"] or m["material"]) for m in mats]
    _mine_mat = tk.StringVar(value=cfg_str(CFG["mine_mat"], names[0]))
    if _mine_mat.get() not in names:
        _mine_mat.set(names[0])

    bar = tk.Frame(_mine_win)
    bar.grid(row=0, column=0, sticky=tk.EW, padx=10, pady=(8, 4))
    tk.Label(bar, text="material").pack(side=tk.LEFT)
    ttk.OptionMenu(bar, _mine_mat, _mine_mat.get(), *names,
                   command=lambda *_: _mining_refresh()).pack(
        side=tk.LEFT, padx=(6, 0))
    tk.Button(bar, text="refresh", command=_mining_refresh).pack(
        side=tk.LEFT, padx=(6, 0))
    tk.Button(bar, text="close", command=_mining_window_close).pack(
        side=tk.LEFT, padx=(4, 0))

    _mine_body = tk.Frame(_mine_win)
    _mine_body.grid(row=1, column=0, sticky=tk.NSEW, padx=10, pady=(0, 8))
    _mining_refresh()
    _theme_tree(_mine_win, _theme_colours())
    _fit_to_screen(_mine_win)


def _mining_refresh() -> None:
    if _mine_win is None or _mine_body is None or ST.db is None:
        return
    try:
        for w in _mine_body.winfo_children():
            w.destroy()
    except Exception:
        pass
    col = _theme_colours()
    want = _mine_mat.get() if _mine_mat else "(all)"

    with ST.lock:
        mats = {(m["label"] or m["material"]): m["material"]
                for m in ST.db.hotspot_materials()}
        key = None if want == "(all)" else mats.get(want, want)
        rows = ST.db.find_hotspots(key, near=ST.cur_pos, limit=40)

    if not rows:
        lbl = tk.Label(_mine_body, anchor=tk.W, font=_MONO,
                       text="nothing scanned yet - map a ring with the DSS\n"
                            "and its materials land here automatically")
        lbl.grid(row=0, column=0, sticky=tk.W)
        _apply_theme(lbl, col, is_text=True)
        return

    head = tk.Label(_mine_body, font=_FONT_GROUP, anchor=tk.W,
                    text="%-26s %-26s %3s  %-10s %s"
                         % ("system", "ring", "x", "ring type", "distance"))
    head.grid(row=0, column=0, sticky=tk.W)
    _apply_theme(head, col, is_text=True)

    for i, h in enumerate(rows, 1):
        ring = str(h["body"] or "")
        sysname = str(h["system"])
        if ring.startswith(sysname):
            ring = ring[len(sysname):].strip()
        dist = ("%.0f ly" % h["dist"]) if h["dist"] is not None else "-"
        text = "%-26s %-26s %3d  %-10s %s" % (
            sysname[:26], ring[:26], h["count"],
            (h["ring_class"] or "")[:10], dist)
        if want == "(all)":
            text += "   " + str(h["material"])
        lbl = tk.Label(_mine_body, text=text, anchor=tk.W, font=_MONO)
        lbl.grid(row=i, column=0, sticky=tk.W)
        lbl.bind("<Button-1>", lambda e, n=sysname: _copy(n))
        _apply_theme(lbl, col, is_text=True)

    if _mine_mat:
        cfg_set(CFG["mine_mat"], want)


def _toggle_probe_window() -> None:
    global _probe_win
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
    global _probe_win, _btn_prefix, _btn_absent, _btn_boxel, _btn_skip
    if _probe_win is not None:
        try:
            _probe_win.destroy()
        except Exception:
            pass
    _probe_win = None
    _btn_prefix = _btn_absent = _btn_boxel = _btn_skip = None
    _refresh()


def _probe_window_open() -> None:
    global _probe_win, _probe_head
    if _frame is None:
        return
    _probe_win = tk.Toplevel(_frame)
    _probe_win.title("SHBOXSEARCH - galaxy map check")
    _probe_win.protocol("WM_DELETE_WINDOW", _probe_window_close)
    try:
        _probe_win.attributes("-topmost", cfg_bool(CFG["route_top"], True))
    except Exception:
        pass
    _probe_head = tk.StringVar(value="")
    tk.Label(_probe_win, textvariable=_probe_head, anchor=tk.W,
             justify=tk.LEFT, font=_MONO).grid(row=0, column=0, sticky=tk.EW,
                                               padx=10, pady=(8, 6))
    bar = tk.Frame(_probe_win)
    bar.grid(row=1, column=0, sticky=tk.EW, padx=10, pady=(0, 4))
    global _btn_prefix, _btn_absent, _btn_boxel, _btn_skip
    _btn_prefix = tk.Button(bar, text="copy prefix", command=_copy_prefix)
    _btn_prefix.pack(side=tk.LEFT)
    _btn_absent = tk.Button(bar, text="not there", command=_probe_absent)
    _btn_absent.pack(side=tk.LEFT, padx=(4, 0))
    _btn_boxel = tk.Button(bar, text="boxel done", command=_boxel_done)
    _btn_boxel.pack(side=tk.LEFT, padx=(4, 0))
    _btn_skip = tk.Button(bar, text="later", command=_probe_skip)
    _btn_skip.pack(side=tk.LEFT, padx=(4, 0))

    bar2 = tk.Frame(_probe_win)
    bar2.grid(row=2, column=0, sticky=tk.EW, padx=10, pady=(0, 8))
    tk.Button(bar2, text="replan",
              command=lambda: _run_async(_rebuild_plan, label="replanning")).pack(
        side=tk.LEFT)
    tk.Button(bar2, text="copy FC", command=_copy_carrier).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Button(bar2, text="carrier spot",
              command=lambda: _run_async(_plan_staging, label="staging")).pack(
        side=tk.LEFT, padx=(4, 0))
    tk.Checkbutton(bar2, text="carrier start", variable=_carrier_var,
                   command=_on_carrier_toggle).pack(side=tk.LEFT, padx=(8, 0))

    _probe_window_refresh()
    _theme_tree(_probe_win, _theme_colours())
    _refresh()


def _probe_window_refresh() -> None:
    if _probe_win is None or _probe_head is None:
        return
    p = current_probe()
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
            "prefix       %s-\n"
            "distance     %.1f ly   uncertainty +-%.0f ly\n"
            "this boxel   %d candidate%s   odds %s\n"
            "queue        %d probes (gap %d, probe %d, empty %d)"
            % (p.name, p.boxel_key or "?", p.dist_origin, p.uncertainty,
               same, "" if same == 1 else "s", odds, len(ST.probe),
               c.get(K_GAP, 0), c.get(K_PROBE, 0), c.get(K_EMPTY, 0)))


def _on_carrier_toggle() -> None:
    cfg_set(CFG["carrier_start"], bool(_carrier_var.get()))
    _refresh()


def _copy_flight_click() -> None:
    t = current_flight()
    if t:
        _copy(t.name)


def _on_start() -> None:
    if ST.active:
        _stop_survey()
    else:
        _start_survey()


def _refresh() -> None:
    if not _frame:
        return
    try:
        t = current_flight()
        if t:
            _v_target.set("%s   %.1f ly" % (t.name, t.dist_origin))
            _v_kind.set("%s %s" % (KIND_SHORT.get(t.kind, t.kind),
                                   t.detail or LABEL.get(t.kind, "")))
        else:
            _v_target.set("-")
            _v_kind.set("no flight targets left" if ST.active else "survey inactive")

        _probe_window_refresh()

        p = current_probe()
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
                    pr = ST.db.system_progress(ST.cur_id64)
                bits = []
                if pr["body_count"]:
                    bits.append("FSS %d/%d" % (pr["scanned"], pr["body_count"]))
                if pr["dss_open"]:
                    bits.append("DSS %d" % len(pr["dss_open"]))
                if pr["bio_open"]:
                    bits.append("Bio %d" % len(pr["bio_open"]))
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
        for b in (_btn_absent, _btn_skip, _btn_boxel, _btn_prefix):
            if b is None:
                continue
            try:
                b.config(state=state)
            except tk.TclError:
                pass
        if _btn_next:
            _btn_next.config(state=tk.NORMAL if ST.flight else tk.DISABLED)
        if _btn_route:
            _btn_route.config(text="route x" if _route_win is not None else "route")
        if _btn_stats:
            _btn_stats.config(text="info x" if _stats_win is not None else "info")
    except Exception:
        logger.exception("UI refresh failed")


# ============================================================================
# Preferences
# ============================================================================

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
    _p["show_route"] = tk.IntVar(value=1 if cfg_bool(CFG["show_route"], True) else 0)
    field(right, "right", "", nb.Checkbutton(
        right, text="keep windows on top", variable=_p["route_top"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="draw the system map", variable=_p["route_map"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="route every body", variable=_p["route_all"]))
    field(right, "right", "", nb.Checkbutton(
        right, text="show the route line in the panel", variable=_p["show_route"]))

    _p["panel_fuel"] = tk.IntVar(value=1 if cfg_bool(CFG["panel_fuel"], False) else 0)
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
        ("Run first import", lambda: _run_async(_first_run_migration,
                                                label="first-run import")),
        ("Replay journals", lambda: _run_async(_import_journals, label="journals")),
        ("Import JSON", lambda: _run_async(_import_json, label="JSON import")),
        ("Export plan (CSV)", _export_csv),
        ("Boxel prefixes", _export_prefixes),
        ("Self test", lambda: _run_async(_selftest, label="self test")),
    ]
    for i, (text, cmd) in enumerate(buttons):
        tk.Button(tools, text=text, command=cmd).grid(
            row=1 + i // 3, column=i % 3, sticky=tk.W, padx=(0, 6), pady=2)

    info = nb.Frame(f)
    info.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
    jd = _journal_dir()
    car = ST.db.get_carrier() if ST.db else None
    lines = [
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
        cfg_set(CFG["edd_path"], _p["eddpath"].get())
        cfg_set(CFG["harvest_navroute"], bool(_p["navroute"].get()))
        cfg_set(CFG["harvest_destination"], bool(_p["dest"].get()))
        cfg_set(CFG["autocopy"], bool(_p["autocopy"].get()))
        cfg_set(CFG["carrier_start"], bool(_p["carrier_start"].get()))
        cfg_set(CFG["show_route"], bool(_p["show_route"].get()))
        cfg_set(CFG["route_all"], bool(_p["route_all"].get()))
        cfg_set(CFG["route_top"], bool(_p["route_top"].get()))
        cfg_set(CFG["route_map"], bool(_p["route_map"].get()))
        cfg_set(CFG["map_size"], _p["map_size"].get())
        cfg_set(CFG["panel_fuel"], bool(_p["panel_fuel"].get()))
        cfg_set(CFG["panel_queue"], bool(_p["panel_queue"].get()))
        global _MAP_W, _MAP_H
        _MAP_W = _MAP_H = _MAP_SIZES.get(_p["map_size"].get(), 480)
        picked = [k for k, v in _p.get("filters", {}).items() if v.get()]
        cfg_set(CFG["filters"], ",".join(picked) if picked else F_OUTSTANDING)
        _request_route(delay=0.2)
        if _carrier_var:
            _carrier_var.set(_p["carrier_start"].get())
        cfg_set(CFG["debug"], bool(_p["debug"].get()))
        logger.setLevel(logging.DEBUG if _p["debug"].get() else logging.INFO)
        ST.sources = SourceManager(_p["eddpath"].get() or None)
        if _radius_var:
            _radius_var.set(_p["radius"].get())
        if ST.active:
            _run_async(_rebuild_plan, label="Plan")
    except Exception:
        logger.exception("could not save settings")


# ============================================================================
# Maintenance
# ============================================================================

def _journal_dir() -> Optional[str]:
    """Journal folder: EDMC's own setting first, then the default paths."""
    for getter in ("get_str", "get"):
        try:
            v = getattr(config, getter)("journaldir")
            if v and os.path.isdir(v):
                return v
        except Exception:
            pass
    for attr in ("default_journal_dir", "default_journal_dir_path"):
        try:
            v = getattr(config, attr, None)
            if callable(v):
                v = v()
            if v and os.path.isdir(str(v)):
                return str(v)
        except Exception:
            pass
    for p in (r"%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous",
              r"%HOMEPATH%\Saved Games\Frontier Developments\Elite Dangerous"):
        q = os.path.expandvars(p)
        if os.path.isdir(q):
            return q
    return None


def _import_journals(max_files: int = 0) -> None:
    d = _journal_dir()
    if not d:
        _set_status("journal folder not found")
        logger.warning("journal folder not found")
        return

    def prog(i, total, fn):
        _set_status("journals %d/%d" % (i, total))

    with ST.lock:
        res = ST.db.import_journals(d, max_files=max_files, progress=prog)
    logger.info("journals replayed: %s", res)
    _set_status("journals: %d files, %d lines, %d events"
                % (res["files"], res["lines"], res["events"]))
    if ST.active:
        _rebuild_plan()


def _first_run_migration() -> None:
    """
    Runs once on first start. Replaces calling migrate.py, so no system-wide
    Python installation is needed - EDMC ships its own interpreter.
    """
    logger.info("first-run import starting")
    _set_status("first-run import: JSON")
    _import_json()
    _set_status("first-run import: journals")
    _import_journals()
    with ST.lock:
        st = ST.db.stats()
        ST.db.set_meta("migrated", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    logger.info("first-run import finished: %s", st)
    _rebuild_route()
    _set_status("first-run import done: %d systems, %d bodies"
                % (st["systems"], st["bodies"]))


def _selftest() -> None:
    """Verify the procgen maths. Result goes to the EDMC log."""
    import io
    import contextlib
    import procgen
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fails = procgen._selftest()
    for line in buf.getvalue().splitlines():
        logger.info("selftest | %s", line)
    with ST.lock:
        st = ST.db.stats()
    logger.info("selftest | database: %s", st)
    _set_status("self test: %s (details in log)"
                % ("passed" if fails == 0 else "%d failures" % fails))


def _import_json() -> None:
    ok_total = 0
    for fn, fn2 in (("neareststars.json", "import_neareststars"),
                    ("survey_state.json", "import_survey_state")):
        p = os.path.join(_PLUGIN_DIR, fn)
        if os.path.exists(p):
            with ST.lock:
                a, b = getattr(ST.db, fn2)(p)
            ok_total += a
            logger.info("%s -> %d / %d", fn, a, b)
    _set_status("JSON import: %d records" % ok_total)


def _export_csv() -> None:
    if not (ST.center and ST.planner):
        _set_status("no active survey")
        return
    p = filedialog.asksaveasfilename(defaultextension=".csv",
                                     initialfile="shboxsearch_plan.csv")
    if not p:
        return
    with ST.lock:
        plan = ST.planner.build(ST.center, ST.radius, masscodes=get_masscodes(),
                                probe_depth=cfg_int(CFG["probe_depth"], 2),
                                include_empty=cfg_bool(CFG["include_empty"], True))
    n = Planner.export_csv(plan, p)
    _set_status("%d targets written to %s" % (n, os.path.basename(p)))


def _export_prefixes() -> None:
    if not (ST.center and ST.planner):
        _set_status("no active survey")
        return
    p = filedialog.asksaveasfilename(defaultextension=".txt",
                                     initialfile="boxel_praefixe.txt")
    if not p:
        return
    with ST.lock:
        plan = ST.planner.build(ST.center, ST.radius, masscodes=get_masscodes(),
                                probe_depth=cfg_int(CFG["probe_depth"], 2),
                                include_empty=cfg_bool(CFG["include_empty"], True))
    rows = Planner.boxel_prefixes(plan, limit=100000)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# One prefix per boxel. Paste into the galaxy map search;\n"
                "# the result list shows every system of that boxel.\n")
        for pref, d, n in rows:
            f.write("%-32s  %7.1f ly  open %d\n" % (pref, d, n))
    _set_status("%d prefixes written to %s" % (len(rows), os.path.basename(p)))
