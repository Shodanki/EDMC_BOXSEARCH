# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Read-only access to the plugin database.

The plugin (EDMC) writes in WAL mode while we read. Every query opens a short
read-only connection (`mode=ro`), so the FIS can never lock or damage the
data, and a missing database simply yields empty answers.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

EXTERNAL_DBS = ("EDDiscovery", "Spansh", "EDSM")
# C1 (plugin 4.8): exploration per commander. The plugin sets this meta key
# once its journal replay sorted the history by FID; before that (and for an
# older plugin database) everything is the shared view, as up to 4.7.
CMDR_READY = "upgrade_48_cmdr"
MAIN = "main"            # fid=MAIN: the main commander (survey, statistics)


def _json(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._bio_cache: Optional[tuple] = None   # (mtime, rows)
        # C1: the main commander from the FIS settings ("" = automatic: the
        # plugin's choice, else the suggestion) - survey and statistics
        self.main_setting = ""

    # ------------------------------------------------------------ plumbing
    @property
    def exists(self) -> bool:
        return bool(self.path) and os.path.exists(self.path)

    def connect(self) -> sqlite3.Connection:
        uri = "file:%s?mode=ro" % self.path.replace("\\", "/")
        cx = sqlite3.connect(uri, uri=True, timeout=2.0, check_same_thread=False)
        cx.row_factory = sqlite3.Row
        return cx

    def query(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        if not self.exists:
            return []
        cx = self.connect()
        try:
            return cx.execute(sql, args).fetchall()
        finally:
            cx.close()

    def one(self, sql: str, args: tuple = ()) -> Optional[sqlite3.Row]:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def mtime(self) -> float:
        """Newest change of the database including its WAL file."""
        t = 0.0
        for p in (self.path, self.path + "-wal"):
            try:
                t = max(t, os.path.getmtime(p))
            except OSError:
                pass
        return t

    # ------------------------------------------------------------- systems
    def system_by_id64(self, id64: int) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM systems WHERE id64=?", (int(id64),))

    def system_by_name(self, name: str) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM systems WHERE name=? COLLATE NOCASE", (name,))

    def bodies_of(self, id64: int) -> List[sqlite3.Row]:
        return self.query("SELECT * FROM bodies WHERE sys_id64=?", (int(id64),))

    def body(self, id64: int, body_id: int) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM bodies WHERE sys_id64=? AND body_id=?",
                        (int(id64), int(body_id)))

    def hotspots_of(self, id64: int, body_id: Optional[int] = None) -> List[sqlite3.Row]:
        if body_id is None:
            return self.query("SELECT * FROM hotspots WHERE sys_id64=?", (int(id64),))
        return self.query("SELECT * FROM hotspots WHERE sys_id64=? AND body_id=?",
                          (int(id64), int(body_id)))

    # ------------------------------------------------- atlas (plugin 4.3)
    def has_table(self, name: str) -> bool:
        try:
            return self.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (name,)) is not None
        except sqlite3.Error:
            return False

    _BEST_SYS = ("LEFT JOIN (SELECT id64, name, x, y, z, MAX(quality) q FROM systems "
                 "GROUP BY id64) s ON s.id64 = ")

    def signals_of(self, id64: int, body_id: Optional[int] = None) -> List[sqlite3.Row]:
        """Body signals, DSS genera, codex and pickup-marked sites (plugin 4.3)."""
        if not self.has_table("signals"):
            return []
        if body_id is None:
            return self.query("SELECT * FROM signals WHERE sys_id64=?", (int(id64),))
        return self.query("SELECT * FROM signals WHERE sys_id64=? AND body_id=?",
                          (int(id64), int(body_id)))

    def materials_at(self, id64: int, body_name: Optional[str] = None) -> List[sqlite3.Row]:
        """Materials picked up in a system / at a body (plugin 4.3)."""
        if not self.has_table("material_finds"):
            return []
        sql = ("SELECT material, MAX(label) label, MAX(category) category, body_name, "
               "SUM(count) count, MAX(ts) last FROM material_finds WHERE sys_id64=?")
        args: list = [int(id64)]
        if body_name is not None:
            sql += " AND body_name=?"
            args.append(body_name)
        return self.query(sql + " GROUP BY material, body_name ORDER BY count DESC", tuple(args))

    def atlas_signals(self, kind: Optional[str] = None) -> List[sqlite3.Row]:
        if not self.has_table("signals"):
            return []
        sql = ("SELECT g.*, s.name sys_name, s.x, s.y, s.z FROM signals g "
               + self._BEST_SYS + "g.sys_id64")
        return self.query(sql + (" WHERE g.kind=?" if kind else ""), (kind,) if kind else ())

    def atlas_materials(self, material: Optional[str] = None) -> List[sqlite3.Row]:
        if not self.has_table("material_finds"):
            return []
        sql = ("SELECT m.material, MAX(m.label) label, MAX(m.category) category, m.body_name, "
               "m.sys_id64, s.name sys_name, s.x, s.y, s.z, SUM(m.count) count, MAX(m.ts) last "
               "FROM material_finds m " + self._BEST_SYS + "m.sys_id64")
        if material:
            sql += " WHERE m.material=?"
        return self.query(sql + " GROUP BY m.material, m.sys_id64, m.body_name",
                          (material,) if material else ())

    # ground finds worth coming back to (same kinds as the plugin's atlas tab)
    FIND_KINDS = ("codex", "bio_analyse", "settlement", "screenshot")

    def atlas_rings(self, material: Optional[str] = None) -> List[sqlite3.Row]:
        if not self.has_table("hotspots"):
            return []
        sql = ("SELECT h.*, s.name sys_name, s.x, s.y, s.z FROM hotspots h "
               + self._BEST_SYS + "h.sys_id64")
        return self.query(sql + (" WHERE h.material=?" if material else ""),
                          (material,) if material else ())

    def atlas_finds(self, kind: Optional[str] = None) -> List[sqlite3.Row]:
        """One row per thing per body, latest position, with a count."""
        if not self.has_table("surface_marks"):
            return []
        kinds = [kind] if kind else list(self.FIND_KINDS)
        sql = ("SELECT m.kind, m.label, MAX(m.detail) detail, m.body_name, m.sys_id64, "
               "s.name sys_name, s.x, s.y, s.z, COUNT(*) count, MAX(m.ts) last, m.lat, m.lon "
               "FROM surface_marks m " + self._BEST_SYS + "m.sys_id64 "
               "WHERE m.kind IN (%s) GROUP BY m.kind, m.sys_id64, m.body_name, m.label"
               % ",".join("?" * len(kinds)))
        return self.query(sql, tuple(kinds))

    # M1: bodies with biological signals (the plugin imported all journals)
    def atlas_bio(self, kind: Optional[str] = None) -> List[sqlite3.Row]:
        """All bodies with bio signals; open/done is decided by the model
        (codex-only genera such as Brain Trees never count as analysed)."""
        if not self.has_table("bodies"):
            return []
        return self.query("SELECT b.sys_id64, b.body_id, b.name body_name, b.sig_bio, b.organics, "
                          "b.genuses, b.bio_species, 1 count, s.name sys_name, s.x, s.y, s.z "
                          "FROM bodies b " + self._BEST_SYS + "b.sys_id64 WHERE b.sig_bio > 0")

    def atlas_kinds(self, view: str) -> List[sqlite3.Row]:
        """What the second picker offers per atlas view, with counts."""
        if view == "rings" and self.has_table("hotspots"):
            return self.query("SELECT material key, MAX(label) label, COUNT(*) n "
                              "FROM hotspots GROUP BY material ORDER BY n DESC")
        if view == "materials" and self.has_table("material_finds"):
            return self.query("SELECT material key, MAX(label) label, MAX(category) category, "
                              "COUNT(DISTINCT sys_id64 || '/' || IFNULL(body_name,'')) n "
                              "FROM material_finds GROUP BY material ORDER BY category, label")
        if view == "finds" and self.has_table("surface_marks"):
            return self.query("SELECT kind key, kind label, COUNT(DISTINCT sys_id64 || '/' || "
                              "body_name || '/' || label) n FROM surface_marks WHERE kind IN "
                              "(%s) GROUP BY kind" % ",".join("?" * len(self.FIND_KINDS)),
                              tuple(self.FIND_KINDS))
        if view == "signals" and self.has_table("signals"):
            return self.query("SELECT kind key, MAX(label) label, COUNT(*) n FROM signals "
                              "GROUP BY kind ORDER BY n DESC")
        return []

    def body_ids(self, id64s) -> Dict[tuple, int]:
        """(id64, body name) -> body_id for a set of systems."""
        ids = sorted({int(i) for i in id64s if i is not None})
        out: Dict[tuple, int] = {}
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]
            for r in self.query("SELECT sys_id64, name, body_id FROM bodies WHERE sys_id64 IN "
                                "(%s) AND name IS NOT NULL" % ",".join("?" * len(part)),
                                tuple(part)):
                out[(r["sys_id64"], r["name"])] = r["body_id"]
        return out

    # ------------------------------------------------ surface (plugin 4.4)
    def surface_track(self, id64: int, body: str) -> List[sqlite3.Row]:
        if not self.has_table("surface_track"):
            return []
        return self.query("SELECT * FROM surface_track WHERE sys_id64=? AND body_name=? "
                          "ORDER BY ts", (int(id64), body))

    def settlements_of(self, id64: int) -> List[sqlite3.Row]:
        """M10: settlements approached in a system (ApproachSettlement marks)."""
        if not self.has_table("surface_marks"):
            return []
        return self.query("SELECT body_name, label, lat, lon, MAX(ts) ts FROM surface_marks "
                          "WHERE sys_id64=? AND kind='settlement' GROUP BY body_name, label",
                          (id64,))

    def surface_marks(self, id64: int, body: str) -> List[sqlite3.Row]:
        if not self.has_table("surface_marks"):
            return []
        return self.query("SELECT * FROM surface_marks WHERE sys_id64=? AND body_name=? "
                          "ORDER BY ts", (int(id64), body))

    def surface_last_body(self) -> Optional[sqlite3.Row]:
        """The body with the most recent mark - shown when not on a body now."""
        if not self.has_table("surface_marks"):
            return None
        return self.one("SELECT sys_id64, body_name FROM surface_marks "
                        "WHERE lat IS NOT NULL ORDER BY ts DESC LIMIT 1")

    def body_by_name(self, id64: int, name: str) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM bodies WHERE sys_id64=? AND name=?", (int(id64), name))

    def last_visited(self) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM systems WHERE visited=1 AND visited_ts IS NOT NULL "
                        "ORDER BY visited_ts DESC LIMIT 1")

    def bio_training_rows(self) -> List[sqlite3.Row]:
        """Every body with analysed species (what biopredict learns from).

        Cached until the database changes - the model only moves when a new
        organism is analysed."""
        mt = self.mtime()
        with self._lock:
            if self._bio_cache and self._bio_cache[0] == mt:
                return self._bio_cache[1]
        rows = self.query("SELECT * FROM bodies WHERE bio_species IS NOT NULL")
        with self._lock:
            self._bio_cache = (mt, rows)
        return rows

    def shell_regions(self, now: Optional[float] = None) -> Dict[str, list]:
        """I1: the regions each source (edd / spansh / edsm) delivered
        completely and that are still valid - where 'in no database' may be
        said. Empty for an older plugin database."""
        if not self.has_table("fetched_shells"):
            return {}
        now = time.time() if now is None else now
        out: Dict[str, list] = {}
        for r in self.query("SELECT service, cx, cy, cz, r_min, r_max FROM fetched_shells"
                            " WHERE expires_at>?", (now,)):
            out.setdefault(r["service"], []).append(
                (r["cx"], r["cy"], r["cz"], r["r_min"], r["r_max"]))
        return out

    @staticmethod
    def known_sources(row: Optional[sqlite3.Row]) -> List[str]:
        if row is None:
            return []
        srcs = set((row["sources"] or "").split(","))
        return [s for s in EXTERNAL_DBS if s in srcs]

    # -------------------------------------------------------------- boxels
    def boxel(self, key: str) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM boxels WHERE key=?", (key,))

    def systems_with_prefix(self, prefix: str) -> List[sqlite3.Row]:
        # names like "Synuefe UC-J b42-3": prefix "Synuefe UC-J b42-"
        esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return self.query("SELECT * FROM systems WHERE name LIKE ? ESCAPE '\\'",
                          (esc + "%",))

    def absent_all(self) -> List[sqlite3.Row]:
        """Names checked in the galaxy map and found not to exist."""
        return self.query("SELECT name, boxel, ts FROM absent ORDER BY name")

    def absent_in(self, key: str) -> List[sqlite3.Row]:
        return self.query("SELECT * FROM absent WHERE boxel=?", (key,))

    # -------------------------------------------------------------- survey
    def survey(self) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM survey WHERE id=1")

    def spheres(self) -> List[sqlite3.Row]:
        return self.query("SELECT * FROM spheres ORDER BY id")

    def systems_in_sphere(self, cx: float, cy: float, cz: float, r: float,
                          fid: Optional[str] = MAIN) -> List[Any]:
        """Systems of the survey sphere; visited / FSS complete as the main
        commander (default) or the given FID explored them (C1)."""
        rows = self.query(
            "SELECT name, id64, x, y, z, quality, visited, fss_complete, sources, body_count "
            "FROM systems WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? "
            "AND z BETWEEN ? AND ? "
            "AND (x-?)*(x-?)+(y-?)*(y-?)+(z-?)*(z-?) <= ?",
            (cx - r, cx + r, cy - r, cy + r, cz - r, cz + r,
             cx, cx, cy, cy, cz, cz, r * r))
        return self.with_visits(rows, fid)

    # ------------------------------------------------ commanders (C1, 4.8)
    def cmdr_ready(self) -> bool:
        """Plugin 4.8+ with its per-commander history filled (one replay)."""
        if not self.has_table("cmdr_bodies"):
            return False
        return self.one("SELECT 1 FROM meta WHERE k=?", (CMDR_READY,)) is not None

    def commanders(self) -> List[Dict[str, Any]]:
        if not self.has_table("commanders"):
            return []
        return [dict(r) for r in self.query(
            "SELECT c.fid, c.name, c.carrier, c.last_seen, "
            "(SELECT COUNT(*) FROM cmdr_logins l WHERE l.fid=c.fid) logins, "
            "(SELECT COUNT(*) FROM cmdr_systems s WHERE s.fid=c.fid "
            " AND s.visited_ts IS NOT NULL) systems FROM commanders c")]

    def suggest_main(self) -> Optional[str]:
        """The commander with an own carrier, else most sessions, else most systems."""
        best = sorted(self.commanders(), key=lambda c: (c["carrier"], c["logins"], c["systems"],
                                                        c["last_seen"] or ""), reverse=True)
        return best[0]["fid"] if best else None

    def main_fid(self) -> Optional[str]:
        """The main commander: the FIS setting, else the plugin's, else the suggestion."""
        if self.main_setting:
            return self.main_setting
        if not self.has_table("commanders"):
            return None
        r = self.one("SELECT v FROM meta WHERE k='main_fid'")
        return (r["v"] if r is not None and r["v"] else None) or self.suggest_main()

    def commander_name(self, fid: Optional[str]) -> Optional[str]:
        if not fid or not self.has_table("commanders"):
            return None
        r = self.one("SELECT name FROM commanders WHERE fid=?", (fid,))
        return r["name"] if r is not None else None

    def view_fid(self, fid: Optional[str]) -> Optional[str]:
        """MAIN -> the main commander's FID; None (shared view, anyone) while
        the plugin has no per-commander history."""
        if fid == MAIN:
            fid = self.main_fid()
        return str(fid) if fid and self.cmdr_ready() else None

    def with_visits(self, rows, fid: Optional[str] = MAIN) -> List[Any]:
        """System rows with visited / fss_complete of one commander."""
        fid = self.view_fid(fid)
        if not fid or not rows:
            return list(rows)
        mine = {r["sys_id64"]: r for r in self.query(
            "SELECT sys_id64, visited_ts, fss_complete FROM cmdr_systems WHERE fid=?", (fid,))}
        out = []
        for r in rows:
            d = dict(r)
            m = mine.get(d.get("id64"))
            d["visited"] = 1 if m is not None and m["visited_ts"] else 0
            d["fss_complete"] = m["fss_complete"] if m is not None else 0
            if "visited_ts" in d:
                d["visited_ts"] = m["visited_ts"] if m is not None else None
            out.append(d)
        return out

    def system_for(self, row, fid: Optional[str]) -> Any:
        """One system row as `fid` explored it (None row stays None)."""
        if row is None:
            return None
        return self.with_visits([row], fid)[0]

    def bodies_for(self, id64: int, fid: Optional[str]) -> List[Any]:
        """Bodies with this commander's scanned / mapped / first discovery /
        species analysed; knowledge (classes, signals, rings) stays shared."""
        rows = self.bodies_of(id64)
        fid = self.view_fid(fid)
        if not fid:
            return rows
        own = {r["body_id"]: r for r in self.query(
            "SELECT * FROM cmdr_bodies WHERE fid=? AND sys_id64=?", (fid, int(id64)))}
        out = []
        for r in rows:
            d = dict(r)
            o = own.get(d["body_id"])
            d["scanned"] = o["scanned"] if o else 0
            d["mapped"] = o["mapped"] if o else 0
            d["organics"] = o["organics"] if o else 0
            d["bio_species"] = o["bio_species"] if o else None
            for k in ("was_discovered", "was_mapped", "was_footfalled"):
                if o is not None and o[k] is not None:
                    d[k] = o[k]
            out.append(d)
        return out

    def explorers(self, id64: Optional[int], but: Optional[str] = None) -> List[str]:
        """C1 'also explored by': names of the commanders who were here."""
        if not id64 or not self.has_table("cmdr_systems"):
            return []
        rows = self.query("SELECT s.fid, c.name FROM cmdr_systems s LEFT JOIN commanders c "
                          "ON c.fid=s.fid WHERE s.sys_id64=? AND s.visited_ts IS NOT NULL "
                          "ORDER BY s.visited_ts", (int(id64),))
        return [r["name"] or r["fid"] for r in rows if r["fid"] != but]

    def boxel_counts(self) -> Dict[str, int]:
        row = self.one("SELECT COUNT(*) AS n, SUM(complete) AS done FROM boxels")
        if row is None:
            return {"total": 0, "complete": 0}
        return {"total": row["n"] or 0, "complete": row["done"] or 0}

    def meta(self) -> Dict[str, str]:
        return {r["k"]: r["v"] for r in self.query("SELECT k, v FROM meta")}

    # -------------------------------------------------------------- health
    def health(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"path": self.path, "exists": self.exists}
        if not self.exists:
            return out
        try:
            cx = self.connect()
            try:
                out["schema"] = (cx.execute("SELECT v FROM meta WHERE k='schema'")
                                 .fetchone() or [None])[0]
                for t in ("systems", "bodies", "boxels"):
                    out[t] = cx.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                out["journal_mode"] = cx.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                cx.close()
            out["ok"] = True
        except sqlite3.Error as exc:
            out["ok"] = False
            out["error"] = str(exc)
        return out


__all__ = ["Database", "EXTERNAL_DBS", "CMDR_READY", "MAIN", "_json"]
