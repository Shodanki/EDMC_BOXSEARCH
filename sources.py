# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
sources.py - external system sources for SHBOXSEARCH v4
=======================================================
Every source returns the same shape:

    [{"name": str, "x": float, "y": float, "z": float, "id64": int|None}, ...]

Ordered by priority (lower = preferred):

  10  EDDiscovery  local EDDSystem.sqlite, no rate limit, very complete
  20  Spansh       daily galaxy dump index, usually more complete than EDSM
  30  EDSM         sphere API, 100 ly radius cap, leaky-bucket rate limit

EDSM and Spansh are asked only through netgate.Gateway: one request at a
time, paced, Retry-After and rate-limit headers followed, honest User-Agent,
every attempt recorded.

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
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from netgate import Gateway
from procgen import id64_matches_position
from shells import edsm_queries, in_shell

logger = logging.getLogger(__name__)

EDSM_SPHERE = "https://www.edsm.net/api-v1/sphere-systems"
EDSM_SYSTEMS = "https://www.edsm.net/api-v1/systems"      # I1 route check: by name
EDSM_CUBE = "https://www.edsm.net/api-v1/cube-systems"
SPANSH_SEARCH = "https://spansh.co.uk/api/systems/search"

ProgressCB = Optional[Callable[[str], None]]


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


class Source:
    name = "?"
    priority = 99
    # did the last fetch deliver the whole region? Only then is the shell
    # remembered as fetched (local-first: shells.py)
    last_ok = False
    # True when the answer was cut at a page cap (still remembered: asking
    # again would only hit the same cap)
    truncated = False

    def available(self) -> Tuple[bool, str]:
        return False, "not implemented"

    def fetch(self, center: Sequence[float], radius: float,
              progress: ProgressCB = None, r_min: float = 0.0) -> List[Dict]:
        """Systems with r_min <= distance from center <= radius."""
        return []


# ---------------------------------------------------------------------------
# EDSM
# ---------------------------------------------------------------------------

class EDSMSource(Source):
    name = "EDSM"
    priority = 30
    MAX_SPHERE = 100.0     # API limit
    MAX_CUBE = 200.0       # API limit (edge length)

    def __init__(self, gateway: Gateway, timeout: int = 30):
        self.gw = gateway
        self.timeout = timeout

    def available(self) -> Tuple[bool, str]:
        return self.gw.status("edsm")

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

    def lookup(self, names: Sequence[str]) -> Optional[Dict[str, Dict]]:
        """
        I1 route check: ONE request for several systems by name
        (systemName[] repeated). Returns {lower-case name: row} of those EDSM
        knows - with coordinates where it has them - or None when EDSM was
        not asked (offline, resting, daily cap) or the answer failed.
        """
        names = [n for n in names if n]
        if not names:
            return {}
        resp = self.gw.request("edsm", "GET", EDSM_SYSTEMS, "systems", timeout=self.timeout,
                               params={"systemName[]": list(names), "showCoordinates": 1,
                                       "showId": 1},
                               headers={"Accept": "application/json"})
        if resp is None:
            return None
        try:
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("EDSM route check failed: %s", e)
            return None
        if isinstance(data, dict):           # EDSM answers {} when it knows none
            data = data.get("systems") or []
        out: Dict[str, Dict] = {}
        for s in data if isinstance(data, list) else []:
            if not isinstance(s, dict) or not s.get("name"):
                continue
            c = s.get("coords") or {}
            row = {"name": s["name"], "id64": s.get("id64"), "source": self.name}
            if c:
                row.update(x=float(c["x"]), y=float(c["y"]), z=float(c["z"]))
            out[s["name"].lower()] = row
        return out

    def fetch(self, center, radius, progress: ProgressCB = None,
              r_min: float = 0.0) -> List[Dict]:
        """One request (minRadius/radius) for a shell up to 100 ly; beyond,
        100 ly spheres that cover the shell (shells.edsm_queries). Every
        answer is cut back to the shell, so EDSM and Spansh deliver the
        same space."""
        self.last_ok = False
        out: Dict[str, Dict] = {}
        calls = edsm_queries(center, r_min, radius)
        complete = True
        for idx, (c, qmin, qmax) in enumerate(calls, 1):
            if progress:
                progress("EDSM %d/%d" % (idx, len(calls)))
            params = {"x": round(c[0], 2), "y": round(c[1], 2), "z": round(c[2], 2),
                      "radius": round(qmax, 1), "showCoordinates": 1, "showId": 1}
            if qmin > 0:
                params["minRadius"] = round(qmin, 1)
            resp = self.gw.request("edsm", "GET", EDSM_SPHERE, "sphere-systems",
                                   timeout=self.timeout, params=params,
                                   headers={"Accept": "application/json"})
            if resp is None:
                # offline, resting or no network: stop asking EDSM for now
                complete = False
                break
            try:
                resp.raise_for_status()
                self._parse(resp.json(), out)
            except Exception as e:
                complete = False
                logger.warning("EDSM query failed: %s", e)
        self.last_ok = complete
        return [v for v in out.values()
                if in_shell((v["x"], v["y"], v["z"]), center, r_min, radius)]


# ---------------------------------------------------------------------------
# Spansh
# ---------------------------------------------------------------------------

class SpanshSource(Source):
    name = "Spansh"
    priority = 20
    PAGE = 500
    # per shell: 10 000 systems, far more than a 25 ly shell holds outside
    # the core (fair use)
    MAX_PAGES = 20

    def __init__(self, gateway: Gateway, timeout: int = 40):
        self.gw = gateway
        self.timeout = timeout

    def available(self) -> Tuple[bool, str]:
        ok, why = self.gw.status("spansh")
        return ok, (why + ", index up to 48 h old") if ok else why

    def fetch(self, center, radius, progress: ProgressCB = None,
              r_min: float = 0.0) -> List[Dict]:
        self.last_ok = False
        self.truncated = False
        out: Dict[str, Dict] = {}
        page = 0
        complete = False
        while True:
            body = {
                "filters": {"distance": {"min": str(r_min), "max": str(radius)}},
                "sort": [{"distance": {"direction": "asc"}}],
                "size": self.PAGE, "page": page,
                "reference_coords": {"x": center[0], "y": center[1], "z": center[2]},
            }
            if progress:
                progress("Spansh page %d" % (page + 1))
            r = self.gw.request("spansh", "POST", SPANSH_SEARCH, "systems/search",
                                data=json.dumps(body), timeout=self.timeout,
                                headers={"Content-Type": "application/json",
                                         "Accept": "application/json"})
            if r is None:
                # offline, resting or no network: stop asking Spansh for now
                break
            try:
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.warning("Spansh query failed: %s", e)
                break
            results = data.get("results") or data.get("systems") or []
            if not results:
                complete = True
                break
            for s in results:
                nm = s.get("name")
                if not nm or s.get("x") is None:
                    continue
                out[nm] = {"name": nm, "x": float(s["x"]), "y": float(s["y"]),
                           "z": float(s["z"]), "id64": s.get("id64") or s.get("id")}
            if len(results) < self.PAGE:
                complete = True
                break
            page += 1
            if page >= self.MAX_PAGES:
                logger.warning("Spansh: shell %.0f-%.0f ly cut at %d systems "
                               "(%d pages) - fair use cap", r_min, radius,
                               len(out), page)
                self.truncated = True
                complete = True        # remembered: asking again hits the cap too
                break
        self.last_ok = complete
        return [v for v in out.values()
                if in_shell((v["x"], v["y"], v["z"]), center, r_min, radius)]


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

    # Current EDD layout (verified against EDDSystem.sqlite, Nov 2026):
    #   SystemTable(edsmid, sectorid, nameid, x, y, z, info)   x/y/z = ly * 128
    #   Sectors(id, gridid, name)    Names(id, Name)
    # nameid for a procgen name carries the name itself:
    #   bit 61 set (0x2000...)  standard name:
    #       n2 bits 0-15, n1 bits 16-23, mass code bits 24-27,
    #       L3 bits 28-32, L2 bits 33-37, L1 bits 38-42 (letters 1-based)
    #   bit 60 set (0x1000...)  catalogue number ("HIP 31330", "EXO 1846-031"):
    #       value bits 0-37, digit count bits 42-45, dash position bits
    #       38-41 (0 = none, 1 = before the first digit ...) - as in
    #       EDDiscovery's EliteNameClassifier.cs
    #   otherwise               id into Names; the sector ("TYC", "2MASS") is
    #       the prefix unless it is "NoSectorName" (Sol, "15 Sagittarii")
    # edsmid: in the files EDDiscovery builds from Spansh's data (checked
    # 13.11.2026: 40 878 of 40 878 sampled rows) it is the SystemAddress
    # (id64). Older files held EDSM's own numbers there, which is why the
    # generic path, taking it for an id64 blindly, returned nothing usable
    # before 4.1. Since 4.10 a row's edsmid counts as its id64 only when the
    # row's position lies inside the boxel that number names
    # (procgen.id64_matches_position).
    STD_MARKER = 1 << 61
    NUM_MARKER = 1 << 60
    NUM_MASK = (1 << 38) - 1
    NO_SECTOR = "NoSectorName"

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._autodetect()
        self.table: Optional[str] = None
        self.mode = "generic"
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
        tables = {r[0].lower(): r[0] for r in cx.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "systemtable" in tables and "sectors" in tables:
            info = cx.execute("PRAGMA table_info(%s)" % tables["systemtable"]).fetchall()
            names = {r[1].lower(): r[1] for r in info}
            if {"x", "y", "z", "nameid", "sectorid"} <= set(names):
                self.table = tables["systemtable"]
                self.mode = "edd2"
                self.cols = {"x": names["x"], "y": names["y"], "z": names["z"],
                             "id": "", "nameid": names["nameid"],
                             "sectorid": names["sectorid"],
                             "key": names.get("edsmid", "")}
                self.has_names = "names" in tables
                return True
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
            return self._calibrate(cx, known_coords, known_id64)
        except sqlite3.Error as e:
            # EDDiscovery running and writing - try again next time
            self.reason = "EDD database busy (%s)" % e
            return False, self.reason
        finally:
            cx.close()

    def _calibrate(self, cx, known_coords, known_id64) -> Tuple[bool, str]:
        if not self._introspect(cx):
            self.reason = "no table with x/y/z columns"
            return False, self.reason

        candidates = [t for t in self.TRANSFORMS if self._plausible(cx, *t)]
        if not candidates:
            self.reason = "no plausible coordinate transform for table %s" % self.table
            return False, self.reason

        if self.mode == "edd2":
            # no SystemAddress column - verify by position instead: the
            # system we are in must sit at exactly its journal coordinates
            self.scale, self.offset = candidates[0]
            self.calibrated = True
            self.reason = "EDD %s, scale /%g (unverified)" % (self.table, self.scale)
            if known_coords:
                q = [int(round(known_coords[i] * self.scale + self.offset))
                     for i in range(3)]
                row = cx.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s BETWEEN ? AND ? AND %s "
                    "BETWEEN ? AND ? AND %s BETWEEN ? AND ?"
                    % (self.table, self.cols["x"], self.cols["z"], self.cols["y"]),
                    (q[0] - 2, q[0] + 2, q[2] - 2, q[2] + 2,
                     q[1] - 2, q[1] + 2)).fetchone()
                if row and row[0]:
                    self.reason = ("EDD %s, scale /%g (verified at current system)"
                                   % (self.table, self.scale))
            return True, self.reason

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

    def available(self) -> Tuple[bool, str]:
        if not self.path:
            return False, "EDDSystem.sqlite not found"
        if not self.calibrated:
            return self.calibrate(self.ref_coords, self.ref_id64)
        return True, self.reason

    FRESH_DAYS = 2.0       # EDD this new counts as "current" (user, 10.11.)

    def freshness(self) -> Tuple[Optional[str], Optional[float]]:
        """(data source, Unix time of its last system update) from EDD's
        Register table - e.g. ("SPANSH", 1762725599.0). (None, None) when
        unknown or the file is busy."""
        cx = self._connect()
        if cx is None:
            return None, None
        try:
            reg = {r[0]: r for r in cx.execute("SELECT * FROM Register").fetchall()}
        except sqlite3.Error:
            return None, None
        finally:
            cx.close()

        def text(key: str) -> Optional[str]:
            row = reg.get(key)
            if not row:
                return None
            for v in tuple(row)[1:]:
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return None

        src = text("DBSource")
        stamp = text("EDSMLastSystems")
        ts = None
        if stamp:
            for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ",
                        "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                try:
                    ts = datetime.strptime(stamp, fmt).replace(
                        tzinfo=timezone.utc).timestamp()
                    break
                except ValueError:
                    continue
        return (src.upper() if src else None), ts

    def is_current(self, source: str, now: Optional[float] = None) -> bool:
        """Does EDD hold the given service's data, updated within FRESH_DAYS?
        Then that service need not be asked for the same systems again."""
        src, ts = self.freshness()
        now = time.time() if now is None else now
        return bool(src == source.upper() and ts
                    and 0 <= now - ts <= self.FRESH_DAYS * 86400.0)

    @classmethod
    def with_sector(cls, sector: Optional[str], rest: str) -> str:
        if sector and sector != cls.NO_SECTOR:
            return "%s %s" % (sector, rest)
        return rest

    @classmethod
    def decode_numeric(cls, nameid: int, sector: Optional[str]) -> Optional[str]:
        """Catalogue name ("HIP 31330", "EXO 1846-031") from a bit-60 nameid."""
        if nameid is None or not (nameid & cls.NUM_MARKER) or nameid & cls.STD_MARKER:
            return None
        digits = (nameid >> 42) & 0xF
        dash = (nameid >> 38) & 0xF
        num = str(nameid & cls.NUM_MASK).zfill(digits)
        if dash > 0:
            num = num[:dash - 1] + "-" + num[dash - 1:]
        return cls.with_sector(sector, num)

    @classmethod
    def decode_nameid(cls, nameid: int, sector: Optional[str]) -> Optional[str]:
        """Rebuild a procgen or catalogue name from EDD's packed nameid, or
        None (then it is an id into Names)."""
        if nameid is not None and nameid & cls.NUM_MARKER \
                and not nameid & cls.STD_MARKER:
            return cls.decode_numeric(nameid, sector)
        if not sector or nameid is None or not (nameid & cls.STD_MARKER):
            return None
        v = nameid & ~cls.STD_MARKER
        n2 = v & 0xFFFF
        n1 = (v >> 16) & 0xFF
        mc = (v >> 24) & 0xF
        l3 = (v >> 28) & 0x1F
        l2 = (v >> 33) & 0x1F
        l1 = (v >> 38) & 0x1F
        if mc > 7 or not (1 <= l1 <= 26 and 1 <= l2 <= 26 and 1 <= l3 <= 26):
            return None
        core = "%s%s-%s %s" % (chr(64 + l1), chr(64 + l2), chr(64 + l3), "abcdefgh"[mc])
        if n1:
            return "%s %s%d-%d" % (sector, core, n1, n2)
        return "%s %s%d" % (sector, core, n2)

    def _edd2_rows(self, cx: sqlite3.Connection, rows, center=None,
                   radius: float = 0.0) -> List[Dict]:
        """Rows (x, y, z, sectorid, nameid[, key]) -> system dicts with the
        name decoded and, where the row's key is provably its id64, the id64."""
        sector_ids = {r[3] for r in rows}
        sectors: Dict[int, str] = {}
        for sid in sector_ids:
            s = cx.execute("SELECT name FROM Sectors WHERE id=?", (sid,)).fetchone()
            if s:
                sectors[sid] = s[0]
        out = []
        skipped = 0
        for r in rows:
            x = (r[0] - self.offset) / self.scale
            y = (r[1] - self.offset) / self.scale
            z = (r[2] - self.offset) / self.scale
            if center is not None and _dist((x, y, z), center) > radius:
                continue
            nameid = r[4]
            name = self.decode_nameid(nameid, sectors.get(r[3]))
            if name is None and getattr(self, "has_names", False) \
                    and nameid is not None and not (nameid & (self.STD_MARKER
                                                              | self.NUM_MARKER)):
                n = cx.execute("SELECT Name FROM Names WHERE id=?", (nameid,)).fetchone()
                name = self.with_sector(sectors.get(r[3]), n[0]) if n else None
            if not name:
                skipped += 1
                continue
            key = r[5] if len(r) > 5 else None
            id64 = int(key) if key and id64_matches_position(key, (x, y, z)) else None
            out.append({"name": name, "x": x, "y": y, "z": z, "id64": id64})
        if skipped:
            logger.info("EDD: %d systems without a decodable name skipped", skipped)
        return out

    def lookup_id64(self, ids: Sequence[int]) -> Optional[List[Dict]]:
        """
        The systems of these id64s that EDDiscovery's file holds - local,
        read only, by primary key (4.10). The planner asks this for its
        probe candidates: a boxel reaches beyond the sphere, and so do its
        "gaps" - most of them EDD knows, just outside the radius it was read
        to. A row counts only when its position lies in the id64's boxel.
        None when the file cannot be asked now (missing, busy, another
        layout) - then the same ids are asked again later.
        """
        ids = [int(i) for i in ids if i]
        if not ids:
            return []
        if not self.calibrated or self.mode != "edd2" or not self.cols.get("key"):
            return None
        cx = self._connect()
        if cx is None:
            return None
        c = self.cols
        out: List[Dict] = []
        try:
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                q = ("SELECT %s,%s,%s,%s,%s,%s FROM %s WHERE %s IN (%s)"
                     % (c["x"], c["y"], c["z"], c["sectorid"], c["nameid"], c["key"],
                        self.table, c["key"], ",".join("?" * len(part))))
                rows = cx.execute(q, part).fetchall()
                out += [r for r in self._edd2_rows(cx, rows) if r["id64"]]
        except sqlite3.Error as e:
            logger.info("EDD lookup by id64 not possible now: %s", e)
            return None
        finally:
            cx.close()
        return out

    def _fetch_edd2(self, cx: sqlite3.Connection, center, radius) -> List[Dict]:
        c = self.cols
        lo = [int((center[i] - radius) * self.scale + self.offset) for i in range(3)]
        hi = [int((center[i] + radius) * self.scale + self.offset) for i in range(3)]
        key = (",%s" % c["key"]) if c.get("key") else ""
        q = ("SELECT %s,%s,%s,%s,%s%s FROM %s WHERE %s BETWEEN ? AND ? "
             "AND %s BETWEEN ? AND ? AND %s BETWEEN ? AND ?"
             % (c["x"], c["y"], c["z"], c["sectorid"], c["nameid"], key, self.table,
                c["x"], c["z"], c["y"]))
        rows = cx.execute(q, (lo[0], hi[0], lo[2], hi[2], lo[1], hi[1])).fetchall()
        return self._edd2_rows(cx, rows, center, radius)

    def fetch(self, center, radius, progress: ProgressCB = None,
              r_min: float = 0.0) -> List[Dict]:
        rows = self._fetch_ball(center, radius, progress)
        self.last_ok = bool(self.table)
        if r_min > 0:
            rows = [r for r in rows
                    if in_shell((r["x"], r["y"], r["z"]), center, r_min, radius)]
        return rows

    def _fetch_ball(self, center, radius, progress: ProgressCB = None) -> List[Dict]:
        cx = self._connect()
        if cx is None or not self.table:
            return []
        if progress:
            progress("EDDiscovery database")
        if self.mode == "edd2":
            try:
                return self._fetch_edd2(cx, center, radius)
            except Exception as e:
                logger.warning("EDD query failed: %s", e)
                return []
            finally:
                cx.close()
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
    def __init__(self, edd_path: Optional[str] = None,
                 gateway: Optional[Gateway] = None):
        # one gateway for the whole plugin: pass it in so that pacing and
        # rests survive a rebuilt SourceManager (preferences changed)
        self.gateway = gateway or Gateway()
        self.sources: Dict[str, Source] = {
            "edd": EDDiscoverySource(edd_path),
            "spansh": SpanshSource(self.gateway),
            "edsm": EDSMSource(self.gateway),
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
                  progress: ProgressCB = None,
                  r_min: float = 0.0) -> Tuple[List[Dict], List[str]]:
        """Query every enabled source for the shell r_min..radius and merge
        the results. Afterwards last_ok[key] says whether a source delivered
        the whole shell, last_count[key] how many systems it had."""
        self.last_ok: Dict[str, bool] = {}
        self.last_count: Dict[str, int] = {}
        merged: Dict[str, Dict] = {}
        by_id: Dict[int, Dict] = {}
        used: List[str] = []
        for key in sorted(enabled, key=lambda k: self.sources[k].priority
                          if k in self.sources else 99):
            src = self.sources.get(key)
            if src is None:
                continue
            self.last_ok[key] = False
            ok, _ = src.available()
            if not ok:
                continue
            try:
                rows = src.fetch(center, radius, progress, r_min=r_min)
            except Exception as e:
                logger.warning("%s: %s", src.name, e)
                continue
            self.last_ok[key] = bool(src.last_ok)
            self.last_count[key] = len(rows)
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


def _selftest() -> int:
    """python sources.py - EDD name decoding, no files, no network."""
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    E = EDDiscoverySource
    cases = [
        (0x1000140000007a62, "HIP", "HIP 31330"),        # values from EDDSystem.sqlite
        (0x1000100000000956, "HR", "HR 2390"),
        ((1 << 60) | (7 << 42) | (5 << 38) | 1846031, "EXO", "EXO 1846-031"),
        ((1 << 60) | (6 << 42) | 4321, "HD", "HD 004321"),
    ]
    for nid, sec, want in cases:
        got = E.decode_nameid(nid, sec)
        check(got == want, "catalogue name %s (got %s)" % (want, got))
    std = (1 << 61) | (19 << 38) | (8 << 33) | (10 << 28) | (1 << 24) | 1
    check(E.decode_nameid(std, "Synuefe") == "Synuefe SH-J b1",
          "procgen name still decoded")
    check(E.decode_nameid(12345, "TYC") is None, "Names id is left to the Names table")
    check(E.with_sector("TYC", "3996-1327-1") == "TYC 3996-1327-1"
          and E.with_sector(E.NO_SECTOR, "15 Sagittarii") == "15 Sagittarii",
          "Names entries get their sector, except NoSectorName")
    # EDD freshness from its Register table (layout as in EDDSystem.sqlite)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "EDDSystem.sqlite")
        cx = sqlite3.connect(path)
        cx.execute("CREATE TABLE Register (ID TEXT PRIMARY KEY, ValueInt INTEGER,"
                   " ValueDouble DOUBLE, ValueString TEXT, ValueBlob BLOB)")
        cx.execute("INSERT INTO Register VALUES ('DBSource', NULL, NULL, 'SPANSH', NULL)")
        cx.execute("INSERT INTO Register VALUES ('EDSMLastSystems', NULL, NULL,"
                   " '11/09/2026 21:59:59', NULL)")
        cx.commit()
        cx.close()
        e = EDDiscoverySource(path)
        src, ts = e.freshness()
        check(src == "SPANSH" and ts == 1794261599.0, "EDD source and last update read")
        check(e.is_current("spansh", now=ts + 86400) and not e.is_current("edsm", now=ts + 86400),
              "EDD one day old holds Spansh's data, not EDSM's")
        check(not e.is_current("spansh", now=ts + 3 * 86400), "three days old: not current")
    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
