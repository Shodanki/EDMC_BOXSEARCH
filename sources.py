# -*- coding: utf-8 -*-
"""
sources.py - external system sources for SHBOXSEARCH v4
=======================================================
Every source returns the same shape:

    [{"name": str, "x": float, "y": float, "z": float, "id64": int|None}, ...]

Ordered by priority (lower = preferred):

  10  EDDiscovery  local EDDSystem.sqlite, no rate limit, very complete
  20  Spansh       daily galaxy dump index, usually more complete than EDSM
  30  EDSM         sphere API, 100 ly radius cap, leaky-bucket rate limit

Important: NONE of these knows about undiscovered systems. They only hold
what the community has uploaded. The undiscovered part comes from
boxelplan.py plus the in-game galaxy map.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
from typing import Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

EDSM_SPHERE = "https://www.edsm.net/api-v1/sphere-systems"
EDSM_CUBE = "https://www.edsm.net/api-v1/cube-systems"
SPANSH_SEARCH = "https://spansh.co.uk/api/systems/search"
USER_AGENT = "SHBOXSEARCH/4.0 (EDMC plugin)"

ProgressCB = Optional[Callable[[str], None]]


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


class Source:
    name = "?"
    priority = 99

    def available(self) -> Tuple[bool, str]:
        return False, "not implemented"

    def fetch(self, center: Sequence[float], radius: float,
              progress: ProgressCB = None) -> List[Dict]:
        return []


# ---------------------------------------------------------------------------
# EDSM
# ---------------------------------------------------------------------------

class EDSMSource(Source):
    name = "EDSM"
    priority = 30
    MAX_SPHERE = 100.0     # API limit
    MAX_CUBE = 200.0       # API limit (edge length)

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.s = requests.Session() if requests else None
        if self.s:
            self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    def available(self) -> Tuple[bool, str]:
        return (True, "ready") if self.s else (False, "requests module missing")

    def _parse(self, data, out: Dict[str, Dict]) -> None:
        if isinstance(data, dict):
            data = data.get("systems") or []
        if not isinstance(data, list):
            return
        for s in data:
            c = s.get("coords")
            if not c:
                continue
            out[s["name"]] = {"name": s["name"], "x": float(c["x"]), "y": float(c["y"]),
                              "z": float(c["z"]), "id64": s.get("id64")}

    def fetch(self, center, radius, progress: ProgressCB = None) -> List[Dict]:
        if not self.s:
            return []
        out: Dict[str, Dict] = {}
        if radius <= self.MAX_SPHERE:
            calls = [(center, radius)]
        else:
            # cover the sphere with 100 ly sub-spheres on a 100 ly grid
            step = self.MAX_SPHERE
            calls = []
            n = int(math.ceil(radius / step))
            for i in range(-n, n + 1):
                for j in range(-n, n + 1):
                    for k in range(-n, n + 1):
                        c = (center[0] + i * step, center[1] + j * step,
                             center[2] + k * step)
                        if _dist(c, center) <= radius + step * 0.87:
                            calls.append((c, step))
        for idx, (c, r) in enumerate(calls, 1):
            if progress:
                progress("EDSM %d/%d" % (idx, len(calls)))
            try:
                resp = self.s.get(EDSM_SPHERE, timeout=self.timeout, params={
                    "x": c[0], "y": c[1], "z": c[2], "radius": r, "showCoordinates": 1,
                    "showId": 1})
                if resp.status_code == 429:
                    logger.warning("EDSM rate limit hit, aborting")
                    break
                resp.raise_for_status()
                self._parse(resp.json(), out)
            except Exception as e:
                logger.warning("EDSM query failed: %s", e)
        return [v for v in out.values() if _dist((v["x"], v["y"], v["z"]), center) <= radius]


# ---------------------------------------------------------------------------
# Spansh
# ---------------------------------------------------------------------------

class SpanshSource(Source):
    name = "Spansh"
    priority = 20
    PAGE = 500

    def __init__(self, timeout: int = 40):
        self.timeout = timeout
        self.s = requests.Session() if requests else None
        if self.s:
            self.s.headers.update({"User-Agent": USER_AGENT,
                                   "Content-Type": "application/json",
                                   "Accept": "application/json"})

    def available(self) -> Tuple[bool, str]:
        return (True, "ready (index up to 48 h old)") if self.s else (False, "requests module missing")

    def fetch(self, center, radius, progress: ProgressCB = None) -> List[Dict]:
        if not self.s:
            return []
        out: Dict[str, Dict] = {}
        page = 0
        while True:
            body = {
                "filters": {"distance": {"min": "0", "max": str(radius)}},
                "sort": [{"distance": {"direction": "asc"}}],
                "size": self.PAGE, "page": page,
                "reference_coords": {"x": center[0], "y": center[1], "z": center[2]},
            }
            if progress:
                progress("Spansh page %d" % (page + 1))
            try:
                r = self.s.post(SPANSH_SEARCH, data=json.dumps(body), timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.warning("Spansh query failed: %s", e)
                break
            results = data.get("results") or data.get("systems") or []
            if not results:
                break
            for s in results:
                nm = s.get("name")
                if not nm or s.get("x") is None:
                    continue
                out[nm] = {"name": nm, "x": float(s["x"]), "y": float(s["y"]),
                           "z": float(s["z"]), "id64": s.get("id64") or s.get("id")}
            if len(results) < self.PAGE:
                break
            page += 1
            if page > 400:      # safety net
                break
        return list(out.values())


# ---------------------------------------------------------------------------
# EDDiscovery - local system database
# ---------------------------------------------------------------------------

class EDDiscoverySource(Source):
    """
    Reads EDDSystem.sqlite directly, read-only.

    EDDiscovery's schema has changed several times across releases
    (coordinates stored as scaled integers, shifting column names). The
    schema is therefore detected at runtime and the coordinate transform is
    calibrated against a system whose exact position is already known.
    """

    name = "EDDiscovery"
    priority = 10

    CANDIDATE_PATHS = [
        r"%LOCALAPPDATA%\EDDiscovery\EDDSystem.sqlite",
        r"%LOCALAPPDATA%\EDDiscovery\EDDSystems.sqlite",
        r"%APPDATA%\EDDiscovery\EDDSystem.sqlite",
    ]
    # (scale, offset) - EDD stores x as int((x*scale)+offset)
    TRANSFORMS = [(128.0, 0x1000000), (128.0, 0), (1.0, 0)]

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._autodetect()
        self.table: Optional[str] = None
        self.cols: Dict[str, str] = {}
        self.scale = 128.0
        self.offset = 0x1000000
        self.calibrated = False
        self.reason = "not checked yet"
        self.ref_id64: Optional[int] = None
        self.ref_coords: Optional[Sequence[float]] = None

    def set_reference(self, id64: Optional[int],
                      coords: Optional[Sequence[float]]) -> None:
        """Supply a system with an exact position (from FSDJump) for verification."""
        if id64 and coords and (id64, tuple(coords)) != (self.ref_id64,
                                                         tuple(self.ref_coords or ())):
            self.ref_id64, self.ref_coords = id64, tuple(coords)
            self.calibrated = False

    def _autodetect(self) -> Optional[str]:
        for p in self.CANDIDATE_PATHS:
            q = os.path.expandvars(p)
            if os.path.exists(q):
                return q
        return None

    def _connect(self) -> Optional[sqlite3.Connection]:
        if not self.path or not os.path.exists(self.path):
            return None
        try:
            uri = "file:%s?mode=ro" % self.path.replace("?", "%3f").replace("#", "%23")
            cx = sqlite3.connect(uri, uri=True, timeout=5.0)
            cx.row_factory = sqlite3.Row
            return cx
        except Exception as e:
            logger.warning("cannot open EDD database: %s", e)
            return None

    def _introspect(self, cx: sqlite3.Connection) -> bool:
        for (tbl,) in cx.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            try:
                info = cx.execute("PRAGMA table_info(%s)" % tbl).fetchall()
            except Exception:
                continue
            names = {r[1].lower(): r[1] for r in info}
            if {"x", "y", "z"} <= set(names):
                idcol = None
                for cand in ("systemaddress", "id64", "edsmid", "sectorid"):
                    if cand in names:
                        idcol = names[cand]
                        if cand != "sectorid":
                            break
                self.table = tbl
                self.cols = {"x": names["x"], "y": names["y"], "z": names["z"],
                             "id": idcol or ""}
                return True
        return False

    def _plausible(self, cx: sqlite3.Connection, scale: float, off: int,
                   limit: int = 500) -> bool:
        """A transform is plausible when a sample of rows lands inside the galaxy."""
        try:
            rows = cx.execute("SELECT %s,%s,%s FROM %s LIMIT %d"
                              % (self.cols["x"], self.cols["y"], self.cols["z"],
                                 self.table, limit)).fetchall()
        except Exception:
            return False
        if not rows:
            return False
        seen = set()
        for r in rows:
            try:
                v = [(float(r[i]) - off) / scale for i in range(3)]
            except (TypeError, ValueError):
                return False
            if not (-70000 <= v[0] <= 70000 and -30000 <= v[1] <= 30000
                    and -30000 <= v[2] <= 80000):
                return False
            seen.add(round(v[0], 1))
        return len(seen) > 1        # not a column of constants

    def calibrate(self, known_coords: Optional[Sequence[float]] = None,
                  known_id64: Optional[int] = None) -> Tuple[bool, str]:
        """
        Detect the table and the coordinate transform.

        Two stages: first every candidate transform is checked against a
        sample of rows for plausibility, then - if the caller supplies a
        system with an exact position from the journal - the winner is
        verified against that system.
        """
        cx = self._connect()
        if cx is None:
            self.reason = "EDDSystem.sqlite not found"
            return False, self.reason
        try:
            if not self._introspect(cx):
                self.reason = "no table with x/y/z columns"
                return False, self.reason

            candidates = [t for t in self.TRANSFORMS if self._plausible(cx, *t)]
            if not candidates:
                self.reason = "no plausible coordinate transform for table %s" % self.table
                return False, self.reason

            # verification against a system whose exact position we know
            if known_id64 and known_coords and self.cols.get("id"):
                row = cx.execute(
                    "SELECT %s,%s,%s FROM %s WHERE %s=? LIMIT 1"
                    % (self.cols["x"], self.cols["y"], self.cols["z"],
                       self.table, self.cols["id"]), (known_id64,)).fetchone()
                if row:
                    for scale, off in candidates:
                        got = [(float(row[i]) - off) / scale for i in range(3)]
                        if all(abs(got[i] - known_coords[i]) < 0.2 for i in range(3)):
                            self.scale, self.offset = scale, off
                            self.calibrated = True
                            self.reason = ("table %s, scale /%g offset %d (verified)"
                                           % (self.table, scale, off))
                            return True, self.reason
                    self.reason = ("table %s: id64 %d found but no transform matches"
                                   % (self.table, known_id64))
                    return False, self.reason

            self.scale, self.offset = candidates[0]
            self.calibrated = True
            self.reason = ("table %s, scale /%g offset %d (unverified)"
                           % (self.table, self.scale, self.offset))
            return True, self.reason
        finally:
            cx.close()

    def available(self) -> Tuple[bool, str]:
        if not self.path:
            return False, "EDDSystem.sqlite not found"
        if not self.calibrated:
            return self.calibrate(self.ref_coords, self.ref_id64)
        return True, self.reason

    def fetch(self, center, radius, progress: ProgressCB = None) -> List[Dict]:
        cx = self._connect()
        if cx is None or not self.table:
            return []
        if progress:
            progress("EDDiscovery database")
        try:
            lo = [int((center[i] - radius) * self.scale + self.offset) for i in range(3)]
            hi = [int((center[i] + radius) * self.scale + self.offset) for i in range(3)]
            sel = "%s,%s,%s" % (self.cols["x"], self.cols["y"], self.cols["z"])
            if self.cols.get("id"):
                sel += ",%s" % self.cols["id"]
            q = ("SELECT %s FROM %s WHERE %s BETWEEN ? AND ? AND %s BETWEEN ? AND ? "
                 "AND %s BETWEEN ? AND ?" % (sel, self.table, self.cols["x"],
                                             self.cols["y"], self.cols["z"]))
            out = []
            for r in cx.execute(q, (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])):
                x = (r[0] - self.offset) / self.scale
                y = (r[1] - self.offset) / self.scale
                z = (r[2] - self.offset) / self.scale
                if _dist((x, y, z), center) > radius:
                    continue
                out.append({"name": None, "x": x, "y": y, "z": z,
                            "id64": r[3] if len(r) > 3 else None})
            return out
        except Exception as e:
            logger.warning("EDD query failed: %s", e)
            return []
        finally:
            cx.close()


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SourceManager:
    def __init__(self, edd_path: Optional[str] = None):
        self.sources: Dict[str, Source] = {
            "edd": EDDiscoverySource(edd_path),
            "spansh": SpanshSource(),
            "edsm": EDSMSource(),
        }

    def set_reference(self, id64: Optional[int],
                      coords: Optional[Sequence[float]]) -> None:
        edd = self.sources.get("edd")
        if isinstance(edd, EDDiscoverySource):
            edd.set_reference(id64, coords)

    def status(self) -> List[Tuple[str, bool, str]]:
        out = []
        for key, s in sorted(self.sources.items(), key=lambda kv: kv[1].priority):
            ok, why = s.available()
            out.append((s.name, ok, why))
        return out

    def fetch_all(self, center, radius, enabled: Sequence[str],
                  progress: ProgressCB = None) -> Tuple[List[Dict], List[str]]:
        """Query every enabled source and merge the results."""
        merged: Dict[str, Dict] = {}
        by_id: Dict[int, Dict] = {}
        used: List[str] = []
        for key in sorted(enabled, key=lambda k: self.sources[k].priority
                          if k in self.sources else 99):
            src = self.sources.get(key)
            if src is None:
                continue
            ok, _ = src.available()
            if not ok:
                continue
            try:
                rows = src.fetch(center, radius, progress)
            except Exception as e:
                logger.warning("%s: %s", src.name, e)
                continue
            used.append("%s (%d)" % (src.name, len(rows)))
            logger.info("source %s returned %d rows", src.name, len(rows))
            for r in rows:
                r["source"] = src.name
                if r.get("name"):
                    prev = merged.get(r["name"])
                    if prev is None:
                        merged[r["name"]] = r
                    else:
                        # keep the first hit but remember every source that has it
                        prev.setdefault("also", []).append(src.name)
                elif r.get("id64"):
                    by_id.setdefault(r["id64"], r)
        # unnamed hits (EDD) are only taken when the id64 is not known yet
        known_ids = {v.get("id64") for v in merged.values() if v.get("id64")}
        for i, r in by_id.items():
            if i not in known_ids:
                merged["#%d" % i] = r
        return list(merged.values()), used
