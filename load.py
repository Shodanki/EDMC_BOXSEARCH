# SHBOXSEARCH — systematic box/sphere explorer for EDMC
# v1.4.1 — Post-jump fallback copy; double-jump robustness; keep EDSM cube-tiling
#           + local-distance; prefer Local JSON; persist; stable clipboard; themed UI.
# MIT License © 2025

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests
import tkinter as tk

# --- EDMC helpers
from config import config
import myNotebook as nb  # EDMC themed widgets
from monitor import monitor

PLUGIN_NAME = "SHBOXSEARCH"
VERSION = "1.4.1"
UA = f"{PLUGIN_NAME}/{VERSION} (EDMC)"

# ---------------------------
# EDSM endpoints / limits (public, no auth/token required)
# ---------------------------
EDSM_BASE = "https://www.edsm.net"
EDSM_CUBE = f"{EDSM_BASE}/api-v1/cube-systems"
EDSM_SYSTEM = f"{EDSM_BASE}/api-v1/system"
CUBE_MAX = 200  # docs: size is edge length in ly, max 200
HTTP_TIMEOUT = 15

# ---------------------------
# Config keys & defaults (typed)
# ---------------------------
CFG_ENABLED = f"{PLUGIN_NAME}.enabled"      # bool
CFG_DEBUG = f"{PLUGIN_NAME}.debug"          # bool
CFG_RADIUS = f"{PLUGIN_NAME}.radius"        # int ly
CFG_SRC = f"{PLUGIN_NAME}.source"           # 'auto' | 'edsm' | 'local'
CFG_LOCAL_PATH = f"{PLUGIN_NAME}.localpath" # path to local neareststars.json
CFG_AUTOCOPY = f"{PLUGIN_NAME}.autocopy"    # bool: auto-copy next target to clipboard

DEFAULTS: Dict[str, Any] = {
    CFG_ENABLED: True,
    CFG_DEBUG: False,
    CFG_RADIUS: 50,
    CFG_SRC: "auto",
    CFG_LOCAL_PATH: "",
    CFG_AUTOCOPY: True,
}

PLUGIN_DIR: Optional[str] = None
STATE_PATH: Optional[str] = None

# ---------------------------
# State model
# ---------------------------
@dataclass
class WorkItem:
    name: str
    id64: Optional[int]
    distance: float
    coords: Optional[Tuple[float, float, float]]

@dataclass
class PluginState:
    start_system: Optional[str] = None
    start_coords: Optional[Tuple[float, float, float]] = None
    radius_ly: int = 50
    source: str = "auto"
    queue: List[WorkItem] = field(default_factory=list)
    visited_ids: set[int] = field(default_factory=set)
    visited_names: set[str] = field(default_factory=set)
    current_target: Optional[WorkItem] = None
    running: bool = False

STATE = PluginState()

# current location snapshot
CUR_NAME: Optional[str] = None
CUR_ADDR: Optional[int] = None

# UI vars
_root: Optional[tk.Frame] = None
_status: Optional[tk.StringVar] = None
_target: Optional[tk.StringVar] = None
_current: Optional[tk.StringVar] = None
_queue_count: Optional[tk.StringVar] = None
_radius_var: Optional[tk.StringVar] = None
_src_var: Optional[tk.StringVar] = None

# ---------------------------
# Logging helpers
# ---------------------------

def _mlog(level: str, msg: str):
    try:
        import EDMCLogging
        lg = EDMCLogging.get_main_logger()
        getattr(lg, level.lower())(f"<{PLUGIN_NAME}> {msg}")
    except Exception:
        print(f"<{PLUGIN_NAME}> {level}: {msg}")

def _info(msg: str):
    _mlog("INFO", msg)

def _dbg(msg: str):
    try:
        enabled = config.get_bool(CFG_DEBUG)
    except Exception:
        enabled = bool(config.get(CFG_DEBUG))
    if enabled:
        _mlog("DEBUG", msg)

# ---------------------------
# EDSM client wrappers
# ---------------------------
_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept": "application/json"})


def _edsm_get(url: str, params: Dict[str, Any]):
    try:
        _dbg(f"GET {url} params={params}")
        r = _session.get(url, params=params, timeout=HTTP_TIMEOUT)
        _dbg(f"HTTP {r.status_code} body={r.text[:220]!r}")
        if r.status_code != 200:
            _info(f"EDSM HTTP {r.status_code} @ {url}")
            return None
        return r.json()
    except Exception as ex:
        _info(f"EDSM GET error: {ex}")
        return None


def _coords_for(name: str) -> Optional[Tuple[float, float, float]]:
    data = _edsm_get(EDSM_SYSTEM, {"systemName": name, "showCoordinates": 1})
    if isinstance(data, dict) and data.get("coords"):
        c = data["coords"]
        return float(c["x"]), float(c["y"]), float(c["z"])
    return None


def _resolve_by_id64(addr: int) -> Optional[Tuple[str, Optional[Tuple[float, float, float]]]]:
    data = _edsm_get(EDSM_SYSTEM, {"systemId64": int(addr), "showCoordinates": 1})
    if not isinstance(data, dict):
        return None
    nm = data.get("name")
    crd = None
    if data.get("coords"):
        c = data["coords"]
        crd = (float(c["x"]), float(c["y"]), float(c["z"]))
    if nm:
        return nm, crd
    return None

# ---------------------------
# Local JSON provider (EDDiscovery/EDDicovery export)
# ---------------------------
import json as _json

def _load_local_neighbors(path: str, center_coords: Optional[Tuple[float, float, float]]) -> List[WorkItem]:
    try:
        if not path or not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as ex:
        _info(f"Local JSON read error: {ex}")
        return []

    items: List[WorkItem] = []
    for row in (data or {}).get("Nearest", []) or []:
        n = row.get("Name")
        if not n:
            continue
        try:
            x = float(row.get("X")); y = float(row.get("Y")); z = float(row.get("Z"))
            crd = (x, y, z)
            dist = math.dist(crd, center_coords) if center_coords else 0.0
            items.append(WorkItem(name=n, id64=None, distance=dist, coords=crd))
        except Exception:
            continue
    _info(f"Local JSON provider -> {len(items)} systems ({os.path.basename(path)})")
    return items

# ---------------------------
# Bootstrap helpers
# ---------------------------

def _read_monitor(tag: str = "") -> bool:
    """Pull current system/address from EDMC's monitor.state. If only id64 is
    known, resolve name+coords via EDSM immediately."""
    global CUR_NAME, CUR_ADDR
    st = getattr(monitor, 'state', {}) or {}
    name = st.get('StarSystem') or st.get('System')
    addr = st.get('SystemAddress') or st.get('SystemAddress64')
    changed = False
    if addr and addr != CUR_ADDR:
        try:
            CUR_ADDR = int(addr)
        except Exception:
            CUR_ADDR = None
        changed = True
    if name and name != CUR_NAME:
        CUR_NAME = name
        changed = True
    if (not CUR_NAME) and isinstance(CUR_ADDR, int):
        resolved = _resolve_by_id64(CUR_ADDR)
        if resolved:
            CUR_NAME, coords = resolved
            changed = True
            _info(f"Resolved current by id64: {CUR_NAME} ({CUR_ADDR})")
    if changed and _current is not None and CUR_NAME:
        _current.set(CUR_NAME)
    if changed:
        _info(f"Detected current system [{tag}]: {CUR_NAME} ({CUR_ADDR})")
    return changed

# ---------------------------
# Persistence
# ---------------------------

def _persist_write():
    if not STATE_PATH:
        return
    try:
        data = {
            "start_system": STATE.start_system,
            "start_coords": STATE.start_coords,
            "radius_ly": STATE.radius_ly,
            "source": STATE.source,
            "queue": [w.__dict__ for w in STATE.queue],
            "visited_ids": list(STATE.visited_ids),
            "visited_names": list(STATE.visited_names),
        }
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _dbg("State persisted")
    except Exception as ex:
        _info(f"Persist write error: {ex}")


def _persist_read():
    if not STATE_PATH or not os.path.isfile(STATE_PATH):
        return False
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        STATE.start_system = data.get("start_system")
        sc = data.get("start_coords")
        if sc:
            STATE.start_coords = tuple(sc)
        STATE.radius_ly = int(data.get("radius_ly", STATE.radius_ly))
        STATE.source = data.get("source", STATE.source)
        STATE.queue = [WorkItem(**w) for w in data.get("queue", [])]
        STATE.visited_ids = set(int(i) for i in data.get("visited_ids", []))
        STATE.visited_names = set(data.get("visited_names", []))
        STATE.current_target = STATE.queue[0] if STATE.queue else None
        _dbg("State restored from disk")
        return True
    except Exception as ex:
        _info(f"Persist read error: {ex}")
        return False


def _persist_reset():
    try:
        if STATE_PATH and os.path.isfile(STATE_PATH):
            os.remove(STATE_PATH)
            _info("Persisted state cleared")
    except Exception:
        pass

# ---------------------------
# Planner helpers (EDSM cube tiling)
# ---------------------------

def _effective_source() -> str:
    src = (STATE.source or "auto").lower()
    if src not in ("auto", "edsm", "local"):
        src = "auto"
    if src == "auto":
        p = config.get_str(CFG_LOCAL_PATH) if hasattr(config, 'get_str') else (config.get(CFG_LOCAL_PATH) or "")
        if p and os.path.isfile(p):
            return "local"
        # look beside plugin
        if PLUGIN_DIR:
            guess = os.path.join(PLUGIN_DIR, 'neareststars.json')
            if os.path.isfile(guess):
                config.set(CFG_LOCAL_PATH, guess)
                return "local"
        return "edsm"
    return src


def _ensure_center() -> Tuple[Optional[str], Optional[Tuple[float, float, float]]]:
    if not STATE.start_system and (CUR_NAME or CUR_ADDR is not None):
        STATE.start_system = CUR_NAME
        if not STATE.start_system and isinstance(CUR_ADDR, int):
            resolved = _resolve_by_id64(CUR_ADDR)
            if resolved:
                nm, crd = resolved
                STATE.start_system = nm
                STATE.start_coords = crd
    name = STATE.start_system
    coords = STATE.start_coords
    if not coords and name:
        coords = _coords_for(name)
        if coords:
            STATE.start_coords = coords
            _dbg(f"Center resolved: {name} -> {coords}")
    return name, coords


def _cube_once(center_coords: Tuple[float, float, float], size: int) -> List[WorkItem]:
    x, y, z = center_coords
    p: Dict[str, Any] = {"x": x, "y": y, "z": z, "size": int(size), "showCoordinates": 1, "showId": 1}
    data = _edsm_get(EDSM_CUBE, p) or []
    out: List[WorkItem] = []
    for row in data or []:
        n = row.get("name")
        if not n:
            continue
        c = row.get("coords")
        crd = (float(c["x"]), float(c["y"]), float(c["z"])) if c else None
        out.append(WorkItem(name=n, id64=row.get("id64") or row.get("id"), distance=0.0, coords=crd))
    return out


def _cube_tiled(center: Tuple[float, float, float], radius: int) -> List[WorkItem]:
    """Tile the space with cubes (<=200 ly edge) to cover a sphere of 'radius' around 'center'.
    Compute distances locally and filter <= radius."""
    R = max(1, int(radius))
    S = min(max(20, min(2 * R, CUBE_MAX)), CUBE_MAX)  # tile edge length
    half = S / 2.0
    cx, cy, cz = center

    # Determine extents to cover sphere
    minx, maxx = cx - R, cx + R
    miny, maxy = cy - R, cy + R
    minz, maxz = cz - R, cz + R

    tiles: List[Tuple[float, float, float]] = []
    x0 = minx + half
    while x0 <= maxx + 1e-6:
        y0 = miny + half
        while y0 <= maxy + 1e-6:
            z0 = minz + half
            while z0 <= maxz + 1e-6:
                tiles.append((x0, y0, z0))
                z0 += S
            y0 += S
        x0 += S

    results: Dict[Tuple[str, Optional[int]], WorkItem] = {}
    for (tx, ty, tz) in tiles:
        batch = _cube_once((tx, ty, tz), S)
        _info(f"EDSM cube tile @ ({tx:.1f},{ty:.1f},{tz:.1f}) size={S} -> {len(batch)}")
        for w in batch:
            key = (w.name, w.id64)
            if key in results:
                continue
            if not w.coords:
                continue
            w.distance = math.dist(w.coords, center)
            if w.distance <= R + 1e-6:
                results[key] = w
    return list(results.values())

# ---------------------------
# Build queue
# ---------------------------

def _build_queue():
    # if we already have a queue from persistence, keep it (only clean visited)
    if STATE.queue:
        _advance_after_visit(save=False)
        if STATE.current_target:
            _copy_target_to_clipboard()
            _persist_write()
            _info(f"Resumed queue: {len(STATE.queue)} systems")
            return

    name, coords = _ensure_center()
    if not (name or coords):
        _info("No center available — open game / Detect system.")
        return

    radius = STATE.radius_ly
    src = _effective_source()

    items: List[WorkItem] = []

    if src == "local":
        p = config.get_str(CFG_LOCAL_PATH) if hasattr(config, 'get_str') else (config.get(CFG_LOCAL_PATH) or "")
        if not p and PLUGIN_DIR:
            p = os.path.join(PLUGIN_DIR, 'neareststars.json')
        items = _load_local_neighbors(p, coords)
        if coords and radius:
            items = [w for w in items if (w.coords and math.dist(w.coords, coords) <= radius + 1e-6)]
    else:
        if not coords:
            coords = _coords_for(name)
        if coords:
            items = _cube_tiled(coords, radius)
        else:
            items = []

    # Deduplicate and drop self
    uniq: List[WorkItem] = []
    seen: set = set()
    for it in items:
        key = ("id", it.id64) if it.id64 is not None else ("name", it.name)
        if key in seen:
            continue
        if name and it.name == name:
            continue
        seen.add(key)
        uniq.append(it)

    # Sort by distance if available, else name
    uniq.sort(key=lambda w: (w.distance if w.distance else float('inf'), w.name))

    STATE.queue = uniq
    STATE.current_target = uniq[0] if uniq else None
    _update_counters()
    _copy_target_to_clipboard()
    _persist_write()

    hint = ""
    if src == "edsm" and not uniq:
        hint = " Tip: Load a local neareststars.json from EDDiscovery in Settings."
    _info(f"Queue built: {len(uniq)} systems; center={name} r={radius} src={src}{hint}")
    _set_status(f"Queue size: {len(uniq)}.{hint}")

# ---------------------------
# Live recognition & progress
# ---------------------------

def _advance_after_visit(save: bool = True):
    STATE.queue = [w for w in STATE.queue if ((w.id64 is None or w.id64 not in STATE.visited_ids) and (w.name not in STATE.visited_names))]
    STATE.current_target = STATE.queue[0] if STATE.queue else None
    _update_counters()
    if save:
        _persist_write()


def _recognize_current_if_relevant():
    if not STATE.running:
        return
    if not (CUR_NAME or CUR_ADDR is not None):
        return
    if CUR_ADDR is not None:
        STATE.visited_ids.add(int(CUR_ADDR))
    if CUR_NAME:
        STATE.visited_names.add(CUR_NAME)
    _advance_after_visit(save=True)
    _copy_target_to_clipboard()
    _info(f"Visited: {CUR_NAME} ({CUR_ADDR}); remaining={len(STATE.queue)}")

# ---------------------------
# UI helpers & callbacks
# ---------------------------

def _update_counters():
    if _queue_count is not None:
        _queue_count.set(str(len(STATE.queue)))
    if _target is not None:
        _target.set(STATE.current_target.name if STATE.current_target else "—")


def _copy_target_to_clipboard():
    try:
        try:
            ac = config.get_bool(CFG_AUTOCOPY)
        except Exception:
            ac = bool(config.get(CFG_AUTOCOPY))
        if not ac:
            return
        if not _root or not STATE.current_target or not STATE.current_target.name:
            return
        _root.clipboard_clear()
        _root.clipboard_append(STATE.current_target.name)
        _root.update()
        _info(f"Copied to clipboard: {STATE.current_target.name}")
    except Exception as ex:
        _info(f"Clipboard error: {ex}")


def _get_clipboard_text() -> str:
    try:
        return (_root.clipboard_get() if _root else "")
    except Exception:
        return ""


def _fallback_recheck():
    """Run shortly after a jump to fix any race with delayed NavRoute/FSDTarget or double jumps."""
    if not STATE.running:
        return
    intended = STATE.queue[0].name if STATE.queue else ""
    if intended:
        current_clip = _get_clipboard_text().strip()
        if current_clip != intended:
            _copy_target_to_clipboard()
            _info(f"Re-copied to clipboard (fallback): {intended}")

# ---------------------------
# UI callbacks
# ---------------------------

def _set_status(msg: str):
    if _status is not None:
        _status.set(msg)
    _info(msg)


def _on_detect():
    changed = _read_monitor("detect")
    if not changed:
        if CUR_NAME:
            _set_status(f"Current system: {CUR_NAME}")
        else:
            _set_status("Could not detect current system (yet).")


def _on_start():
    try:
        enabled = config.get_bool(CFG_ENABLED)
    except Exception:
        enabled = bool(config.get(CFG_ENABLED))
    if not enabled:
        _set_status("Plugin disabled in settings.")
        return

    try:
        STATE.radius_ly = max(1, int(float(_radius_var.get()))) if _radius_var else int(config.get_int(CFG_RADIUS))
    except Exception:
        try:
            STATE.radius_ly = int(config.get_int(CFG_RADIUS))
        except Exception:
            STATE.radius_ly = DEFAULTS[CFG_RADIUS]

    try:
        STATE.source = (_src_var.get() if _src_var else (config.get_str(CFG_SRC) if hasattr(config,'get_str') else config.get(CFG_SRC))) or "auto"
    except Exception:
        STATE.source = config.get(CFG_SRC) or "auto"

    _read_monitor("start")
    if CUR_NAME:
        STATE.start_system = CUR_NAME
        STATE.start_coords = None  # resolve fresh if needed
    elif isinstance(CUR_ADDR, int):
        resolved = _resolve_by_id64(CUR_ADDR)
        if resolved:
            nm, crd = resolved
            STATE.start_system = nm
            STATE.start_coords = crd
            _info(f"Center set by id64: {nm} ({CUR_ADDR})")
    if not (STATE.start_system or STATE.start_coords):
        _set_status("No center. Click Detect system first.")
        return

    STATE.running = True
    _set_status(f"Start: {STATE.start_system} r={STATE.radius_ly} src={_effective_source()}")
    threading.Thread(target=_build_queue, daemon=True).start()


def _on_stop():
    STATE.running = False
    _set_status("Stopped (progress preserved).")
    _persist_write()


def _on_reset():
    STATE.running = False
    STATE.queue.clear()
    STATE.current_target = None
    STATE.visited_ids.clear()
    STATE.visited_names.clear()
    _update_counters()
    _persist_reset()
    _set_status("Reset: cleared saved list and progress.")


def _on_test():
    name, coords = _ensure_center()
    if not (name or coords):
        _set_status("No center for test.")
        return
    src = _effective_source()
    if src == "local":
        p = config.get_str(CFG_LOCAL_PATH) if hasattr(config, 'get_str') else (config.get(CFG_LOCAL_PATH) or "")
        if not p and PLUGIN_DIR:
            p = os.path.join(PLUGIN_DIR, 'neareststars.json')
        items = _load_local_neighbors(p, coords)
        _set_status(f"Local JSON OK: {len(items)} systems in file")
        return
    # EDSM cube probe 50 ly
    if not coords:
        coords = _coords_for(name)
    if coords:
        got = _cube_tiled(coords, 50)
        if got:
            _set_status(f"EDSM OK: {len(got)} systems within 50 ly (cube tiling)")
            return
    _set_status("EDSM returned no neighbours — load a local neareststars.json in Settings → SHBOXSEARCH.")

# ---------------------------
# EDMC hooks
# ---------------------------

def plugin_start3(plugin_dir: str):
    global PLUGIN_DIR, STATE_PATH
    PLUGIN_DIR = plugin_dir
    STATE_PATH = os.path.join(plugin_dir, "state.json")

    for k, v in DEFAULTS.items():
        try:
            if isinstance(v, bool):
                if config.get_bool(k) is None:
                    config.set(k, bool(v))
            elif isinstance(v, int):
                try:
                    current = config.get_int(k)
                except Exception:
                    current = config.get(k)
                if current is None:
                    config.set(k, int(v))
            else:
                try:
                    current = config.get_str(k)
                except Exception:
                    current = config.get(k)
                if current is None:
                    config.set(k, str(v))
        except Exception:
            try:
                if isinstance(v, bool):
                    config.set(k, bool(v))
                elif isinstance(v, int):
                    config.set(k, int(v))
                else:
                    config.set(k, str(v))
            except Exception as ex:
                _info(f"Default init skipped for {k}: {ex}")

    # Attempt to restore previous session
    _persist_read()
    _info(f"{PLUGIN_NAME} v{VERSION} loaded")
    return PLUGIN_NAME


def plugin_prefs(parent, cmdr: str, is_beta: bool):
    frame = nb.Frame(parent)

    # Enable / Debug
    try:
        en = tk.BooleanVar(value=config.get_bool(CFG_ENABLED))
    except Exception:
        en = tk.BooleanVar(value=bool(config.get(CFG_ENABLED)))
    nb.Checkbutton(frame, text="Enable SHBOXSEARCH", variable=en, command=lambda: config.set(CFG_ENABLED, bool(en.get()))).grid(sticky=tk.W, padx=5, pady=3)

    try:
        dbg = tk.BooleanVar(value=config.get_bool(CFG_DEBUG))
    except Exception:
        dbg = tk.BooleanVar(value=bool(config.get(CFG_DEBUG)))
    nb.Checkbutton(frame, text="Debug logging", variable=dbg, command=lambda: config.set(CFG_DEBUG, bool(dbg.get()))).grid(sticky=tk.W, padx=5, pady=3)

    # Source
    nb.Label(frame, text="Data source").grid(sticky=tk.W, padx=5, pady=3)
    try:
        src_val = config.get_str(CFG_SRC) or "auto"
    except Exception:
        src_val = config.get(CFG_SRC) or "auto"
    src = tk.StringVar(value=src_val)
    def _apply_src(*_):
        val = (src.get() or "auto").lower()
        if val not in ("auto", "edsm", "local"):
            val = "auto"
        config.set(CFG_SRC, val)
    nb.OptionMenu(frame, src, src.get(), "auto", "edsm", "local", command=lambda *_: _apply_src()).grid(sticky=tk.W, padx=5)

    # Local path
    nb.Label(frame, text="Local JSON (neareststars.json)").grid(sticky=tk.W, padx=5, pady=3)
    try:
        path_val = config.get_str(CFG_LOCAL_PATH) or ""
    except Exception:
        path_val = config.get(CFG_LOCAL_PATH) or ""
    path_var = tk.StringVar(value=path_val)
    def _apply_path(*_):
        config.set(CFG_LOCAL_PATH, path_var.get())
    ent = nb.Entry(frame, textvariable=path_var, width=48)
    ent.grid(sticky=tk.W, padx=5)
    path_var.trace_add('write', _apply_path)

    # Radius
    nb.Label(frame, text="Default radius (ly)").grid(sticky=tk.W, padx=5, pady=3)
    try:
        r_default = config.get_int(CFG_RADIUS)
    except Exception:
        r_default = config.get(CFG_RADIUS) or DEFAULTS[CFG_RADIUS]
    rad = tk.StringVar(value=str(r_default))
    def _apply_radius(*_):
        try:
            r = max(1, int(float(rad.get())))
            config.set(CFG_RADIUS, int(r))
        except Exception:
            pass
    ent2 = nb.Entry(frame, textvariable=rad, width=8)
    ent2.grid(sticky=tk.W, padx=5)
    rad.trace_add('write', _apply_radius)

    # Auto-copy
    try:
        ac = tk.BooleanVar(value=config.get_bool(CFG_AUTOCOPY))
    except Exception:
        ac = tk.BooleanVar(value=bool(config.get(CFG_AUTOCOPY)))
    nb.Checkbutton(frame, text="Auto-copy next target to clipboard", variable=ac, command=lambda: config.set(CFG_AUTOCOPY, bool(ac.get()))).grid(sticky=tk.W, padx=5, pady=3)

    return frame


def prefs_changed(cmdr: str, is_beta: bool):
    _info("Preferences saved")


def plugin_app(parent):
    global _root, _status, _target, _current, _queue_count, _radius_var, _src_var
    _root = nb.Frame(parent)

    r = 0
    nb.Label(_root, text=f"{PLUGIN_NAME} v{VERSION}").grid(row=r, column=0, sticky=tk.W)

    r += 1
    _current = tk.StringVar(value="(unknown)")
    nb.Label(_root, text="Current system:").grid(row=r, column=0, sticky=tk.W)
    nb.Label(_root, textvariable=_current).grid(row=r, column=1, sticky=tk.W)

    r += 1
    nb.Label(_root, text="Radius (ly):").grid(row=r, column=0, sticky=tk.W)
    try:
        r_default = config.get_int(CFG_RADIUS)
    except Exception:
        r_default = config.get(CFG_RADIUS) or DEFAULTS[CFG_RADIUS]
    _radius_var = tk.StringVar(value=str(r_default))
    nb.Entry(_root, textvariable=_radius_var, width=8).grid(row=r, column=1, sticky=tk.W)

    r += 1
    nb.Label(_root, text="Source:").grid(row=r, column=0, sticky=tk.W)
    try:
        s_val = config.get_str(CFG_SRC) or "auto"
    except Exception:
        s_val = config.get(CFG_SRC) or "auto"
    _src_var = tk.StringVar(value=s_val)
    nb.OptionMenu(_root, _src_var, _src_var.get(), "auto", "edsm", "local").grid(row=r, column=1, sticky=tk.W)

    r += 1
    nb.Label(_root, text="Next target:").grid(row=r, column=0, sticky=tk.W)
    _target = tk.StringVar(value="—")
    nb.Label(_root, textvariable=_target).grid(row=r, column=1, sticky=tk.W)

    r += 1
    nb.Label(_root, text="Queue size:").grid(row=r, column=0, sticky=tk.W)
    _queue_count = tk.StringVar(value="0")
    nb.Label(_root, textvariable=_queue_count).grid(row=r, column=1, sticky=tk.W)

    r += 1
    btns = nb.Frame(_root)
    btns.grid(row=r, column=0, columnspan=2, sticky=tk.W, pady=4)
    nb.Button(btns, text="Detect system", command=_on_detect).grid(row=0, column=0, padx=2)
    nb.Button(btns, text="Start", command=_on_start).grid(row=0, column=1, padx=2)
    nb.Button(btns, text="Stop", command=_on_stop).grid(row=0, column=2, padx=2)
    nb.Button(btns, text="Reset", command=_on_reset).grid(row=0, column=3, padx=2)
    nb.Button(btns, text="Test Source", command=_on_test).grid(row=0, column=4, padx=2)

    r += 1
    _status = tk.StringVar(value="Ready.")
    nb.Label(_root, textvariable=_status, wraplength=420, justify=tk.LEFT).grid(row=r, column=0, columnspan=2, sticky=tk.W, pady=4)

    _persist_read()
    _update_counters()
    _read_monitor("panel")
    if STATE.current_target:
        _copy_target_to_clipboard()
    _set_status("Panel ready")
    return _root

# ---------------------------
# Journal hook
# ---------------------------

def journal_entry(cmdr: str, is_beta: bool, system: str, station: str, entry: Dict[str, Any], state: Dict[str, Any]):
    try:
        ev = entry.get('event')
        _dbg(f"journal: {ev}")
        if ev in ("StartUp", "LoadGame"):
            _read_monitor(ev)
        elif ev in ("Location", "FSDJump"):
            global CUR_NAME, CUR_ADDR
            name = entry.get('StarSystem') or system
            addr = entry.get('SystemAddress') or state.get('SystemAddress')
            if addr is not None:
                try:
                    CUR_ADDR = int(addr)
                except Exception:
                    CUR_ADDR = None
            if name:
                CUR_NAME = name
            elif CUR_ADDR is not None:
                res = _resolve_by_id64(CUR_ADDR)
                if res:
                    CUR_NAME, _ = res
            if _current is not None and CUR_NAME:
                _current.set(CUR_NAME)
            _dbg(f"Now at {CUR_NAME} ({CUR_ADDR}) running={STATE.running}")
            _recognize_current_if_relevant()
            # Fallback recheck after a short delay to cover fast successive jumps or NavRoute lag
            try:
                if _root is not None:
                    _root.after(1500, _fallback_recheck)
            except Exception:
                pass
        elif ev in ("NavRoute", "FSDTarget"):
            # Keep clipboard aligned with our queue if the user changed target manually
            if STATE.running and STATE.current_target:
                _copy_target_to_clipboard()
        elif ev == "Shutdown":
            _persist_write()
            STATE.running = False
    except Exception as ex:
        _info(f"journal_entry error: {ex}")
