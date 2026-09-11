# -*- coding: utf-8 -*-
"""
sysdb.py - persistent database for SHBOXSEARCH v4
=================================================
Holds systems, bodies, signals, scan progress, boxel knowledge and the
negative cache. Replaces neareststars.json + survey_state.json as the
storage layer.

Data integrity
--------------
Every coordinate carries a quality level. A lower-quality write NEVER
overwrites a higher-quality one, so no source (external API, estimate) can
ever degrade exact journal data.

    Q_JOURNAL   40  FSDJump / Location / NavRoute        exact, game client
    Q_EXTERNAL  30  EDSM / Spansh / EDDiscovery          exact, community
    Q_CONFIRMED 20  FSDTarget / Status.json Destination  existence proven
    Q_ESTIMATE  10  derived from name or id64            boxel centre
    Q_UNKNOWN    0

Standard library only.
"""

from __future__ import annotations

import calendar
import json
import math
import os
import sqlite3
import time
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from procgen import (MASSCODES, SectorRegistry, decode_id64, make_name,
                     parse_boxel_only, parse_name)

Q_UNKNOWN = 0
Q_ESTIMATE = 10
Q_CONFIRMED = 20
Q_EXTERNAL = 30
Q_JOURNAL = 40

SCHEMA_VERSION = 2

# Body classes that are always worth mapping (DSS)
VALUABLE_CLASSES = {
    "Earthlike body", "Water world", "Ammonia world",
    "High metal content body", "Metal rich body",
}

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS systems (
    name        TEXT PRIMARY KEY,
    id64        INTEGER,
    x REAL, y REAL, z REAL,
    quality     INTEGER NOT NULL DEFAULT 0,
    source      TEXT,
    sources     TEXT,          -- every source that reported it, comma separated
    star_class  TEXT,
    visited     INTEGER NOT NULL DEFAULT 0,
    visited_ts  TEXT,
    body_count  INTEGER,          -- from FSSDiscoveryScan / FSSAllBodiesFound
    nonbody_count INTEGER,
    fss_complete  INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT,
    updated     TEXT
);
CREATE INDEX IF NOT EXISTS ix_sys_id64 ON systems(id64);
CREATE INDEX IF NOT EXISTS ix_sys_xyz  ON systems(x, y, z);
CREATE INDEX IF NOT EXISTS ix_sys_vis  ON systems(visited);

CREATE TABLE IF NOT EXISTS bodies (
    sys_id64    INTEGER NOT NULL,
    body_id     INTEGER NOT NULL,
    name        TEXT,
    kind        TEXT,             -- Star / Planet / Ring / BaryCentre
    planet_class TEXT,
    terraform   TEXT,
    landable    INTEGER,
    was_discovered INTEGER,       -- NULL = unknown
    was_mapped  INTEGER,
    scanned     INTEGER NOT NULL DEFAULT 0,
    mapped      INTEGER NOT NULL DEFAULT 0,
    sig_bio     INTEGER NOT NULL DEFAULT 0,
    sig_geo     INTEGER NOT NULL DEFAULT 0,
    arrival_ls  REAL,
    parent_id   INTEGER,
    sma REAL, ecc REAL, inc REAL, peri REAL, node REAL, mean_anom REAL, period REAL,
    ring_classes TEXT, ring_mass REAL, star_type TEXT, scan_ts REAL,
    organics    INTEGER NOT NULL DEFAULT 0,
    genuses     TEXT,
    updated     TEXT,
    PRIMARY KEY (sys_id64, body_id)
);
CREATE INDEX IF NOT EXISTS ix_bod_sys ON bodies(sys_id64);

CREATE TABLE IF NOT EXISTS absent (
    name  TEXT PRIMARY KEY,
    boxel TEXT,
    n2    INTEGER,
    ts    TEXT
);
CREATE INDEX IF NOT EXISTS ix_absent_boxel ON absent(boxel);

CREATE TABLE IF NOT EXISTS boxels (
    key      TEXT PRIMARY KEY,
    sector   TEXT,
    mc       INTEGER,
    n2_max   INTEGER,
    n2_end   INTEGER,
    complete INTEGER NOT NULL DEFAULT 0,
    updated  TEXT
);

CREATE TABLE IF NOT EXISTS sectors (
    name TEXT PRIMARY KEY,
    sx INTEGER, sy INTEGER, sz INTEGER
);

CREATE TABLE IF NOT EXISTS survey (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    active       INTEGER NOT NULL DEFAULT 0,
    start_system TEXT,
    cx REAL, cy REAL, cz REAL,
    radius       REAL,
    masscodes    TEXT,
    started      TEXT,
    updated      TEXT
);

CREATE TABLE IF NOT EXISTS spheres (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    label    TEXT,
    cx REAL, cy REAL, cz REAL,
    radius   REAL,
    origin   TEXT,            -- 'free' or 'carrier'
    started  TEXT,
    closed   TEXT
);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def _epoch(stamp: Optional[str]) -> Optional[float]:
    """Journal timestamp to unix seconds - the epoch of the orbital elements."""
    if not stamp:
        return None
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class SystemDB:
    """All writes are idempotent and commit-safe."""

    def __init__(self, path: str):
        self.path = path
        self.cx = sqlite3.connect(path, check_same_thread=False, timeout=15.0)
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(SCHEMA)
        self._migrate()
        self.cx.execute("INSERT OR IGNORE INTO meta(k,v) VALUES ('schema',?)",
                        (str(SCHEMA_VERSION),))
        self.cx.commit()
        self.sectors = SectorRegistry()
        self._load_sectors()

    def _migrate(self) -> None:
        """Add columns introduced after the first release, in place."""
        have = {r[1] for r in self.cx.execute("PRAGMA table_info(systems)")}
        if "sources" not in have:
            self.cx.execute("ALTER TABLE systems ADD COLUMN sources TEXT")
            self.cx.execute("UPDATE systems SET sources=source WHERE sources IS NULL")
            self.cx.commit()
        bhave = {r[1] for r in self.cx.execute("PRAGMA table_info(bodies)")}
        for col, typ in (("arrival_ls", "REAL"), ("parent_id", "INTEGER"),
                         ("sma", "REAL"), ("ecc", "REAL"), ("inc", "REAL"),
                         ("peri", "REAL"), ("node", "REAL"),
                         ("mean_anom", "REAL"), ("period", "REAL"),
                         ("ring_classes", "TEXT"), ("ring_mass", "REAL"),
                         ("star_type", "TEXT"), ("scan_ts", "REAL")):
            if col not in bhave:
                self.cx.execute("ALTER TABLE bodies ADD COLUMN %s %s" % (col, typ))
        self.cx.commit()

    # ------------------------------------------------------------------ util
    def close(self) -> None:
        try:
            self.cx.commit()
            self.cx.close()
        except Exception:
            pass

    def get_meta(self, k: str, default: Optional[str] = None) -> Optional[str]:
        r = self.cx.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set_meta(self, k: str, v: str) -> None:
        self.cx.execute("INSERT OR REPLACE INTO meta(k,v) VALUES (?,?)", (k, str(v)))
        self.cx.commit()

    # ---------------------------------------------------------------- sectors
    def _load_sectors(self) -> None:
        for r in self.cx.execute("SELECT name, sx, sy, sz FROM sectors"):
            self.sectors.load_dict({r["name"]: (r["sx"], r["sy"], r["sz"])})

    def learn_sector(self, name: str, id64: Optional[int] = None,
                     coords: Optional[Sequence[float]] = None) -> None:
        p = parse_name(name)
        if p is None:
            return
        before = self.sectors.index_of(p.sector)
        ok = False
        if id64:
            ok = self.sectors.learn_from_id64(name, id64)
        if not ok and coords and coords[0] is not None:
            ok = self.sectors.learn_from_coords(name, *coords)
        idx = self.sectors.index_of(p.sector)
        if idx and idx != before:
            self.cx.execute("INSERT OR REPLACE INTO sectors(name,sx,sy,sz) VALUES (?,?,?,?)",
                            (p.sector, int(idx[0]), int(idx[1]), int(idx[2])))

    def name_from_id64(self, id64: int) -> Optional[str]:
        """Rebuild the procgen name from an id64 alone (sector must be known)."""
        try:
            d = decode_id64(id64)
            sect = self.sectors.name_of(d["sector_idx"])
            if not sect:
                return None
            return make_name(sect, d["mc"], d["boxel"], d["n2"])
        except Exception:
            return None

    # ---------------------------------------------------------------- systems
    def upsert(self, name: Optional[str], x: Optional[float] = None,
               y: Optional[float] = None, z: Optional[float] = None,
               id64: Optional[int] = None, quality: int = Q_EXTERNAL,
               source: str = "?", star_class: Optional[str] = None,
               visited: Optional[bool] = None, commit: bool = True) -> bool:
        """Insert or improve. Downgrades are discarded."""
        if not name and id64:
            name = self.name_from_id64(id64)
        name = (name or "").strip()
        if not name:
            return False

        if x is None and id64:
            try:
                d = decode_id64(id64)
                x, y, z = d["center"]
                quality = min(quality, Q_ESTIMATE) if quality > Q_CONFIRMED else quality
            except Exception:
                pass

        row = self.cx.execute("SELECT * FROM systems WHERE name=?", (name,)).fetchone()
        now = _now()
        changed = False

        if row is None:
            self.cx.execute(
                "INSERT INTO systems(name,id64,x,y,z,quality,source,sources,"
                "star_class,visited,visited_ts,first_seen,updated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, id64, x, y, z, quality, source, source, star_class,
                 1 if visited else 0, now if visited else None, now, now))
            changed = True
        else:
            sets: List[str] = []
            args: List[object] = []
            if id64 and not row["id64"]:
                sets.append("id64=?"); args.append(id64)
            if x is not None and quality >= (row["quality"] or 0):
                if (row["x"] is None or quality > (row["quality"] or 0)
                        or abs((row["x"] or 0) - x) > 1e-6):
                    sets += ["x=?", "y=?", "z=?", "quality=?", "source=?"]
                    args += [x, y, z, quality, source]
            if star_class and not row["star_class"]:
                sets.append("star_class=?"); args.append(star_class)
            if visited and not row["visited"]:
                sets += ["visited=1", "visited_ts=?"]; args.append(now)
            have = set((row["sources"] or "").split(",")) - {""}
            if source and source not in have:
                have.add(source)
                sets.append("sources=?"); args.append(",".join(sorted(have)))
            if sets:
                sets.append("updated=?"); args.append(now); args.append(name)
                self.cx.execute("UPDATE systems SET %s WHERE name=?" % ",".join(sets), args)
                changed = True

        self.cx.execute("DELETE FROM absent WHERE name=?", (name,))
        self.learn_sector(name, id64=id64, coords=(x, y, z) if x is not None else None)
        self._touch_boxel(name)
        if commit:
            self.cx.commit()
        return changed

    def system_by_id64(self, id64: int) -> Optional[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM systems WHERE id64=?", (id64,)).fetchone()

    def system(self, name: str) -> Optional[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM systems WHERE name=?", (name,)).fetchone()

    def sphere(self, center: Sequence[float], radius: float,
               min_quality: int = 0) -> List[sqlite3.Row]:
        cx0, cy0, cz0 = center
        rows = self.cx.execute(
            "SELECT * FROM systems WHERE quality>=? AND x BETWEEN ? AND ? "
            "AND y BETWEEN ? AND ? AND z BETWEEN ? AND ?",
            (min_quality, cx0 - radius, cx0 + radius, cy0 - radius,
             cy0 + radius, cz0 - radius, cz0 + radius)).fetchall()
        r2 = radius * radius
        out = [r for r in rows if r["x"] is not None
               and (r["x"] - cx0) ** 2 + (r["y"] - cy0) ** 2 + (r["z"] - cz0) ** 2 <= r2]
        return out

    # ------------------------------------------------------------ negative cache
    def mark_absent(self, name: str) -> None:
        name = name.strip()
        p = parse_name(name)
        self.cx.execute(
            "INSERT OR REPLACE INTO absent(name,boxel,n2,ts) VALUES (?,?,?,?)",
            (name, p.boxel_key if p else None, p.n2 if p else None, _now()))
        if p:
            self._touch_boxel(name, n2_end=p.n2)
        self.cx.commit()

    def unmark_absent(self, name: str) -> None:
        self.cx.execute("DELETE FROM absent WHERE name=?", (name.strip(),))
        self.cx.commit()

    def absent_set(self) -> Set[str]:
        return {r[0] for r in self.cx.execute("SELECT name FROM absent")}

    # ------------------------------------------------------------------ boxel
    def _touch_boxel(self, name: str, n2_end: Optional[int] = None) -> None:
        p = parse_name(name)
        if p is None:
            # "Synuefe XV-C d12" - boxel designation without a running number.
            # Frontier drops the number when a boxel holds exactly one system,
            # so the boxel is complete and needs no probing.
            bo = parse_boxel_only(name)
            if bo:
                sector, mc, _boxel, key = bo
                self.cx.execute(
                    "INSERT OR REPLACE INTO boxels(key,sector,mc,n2_max,n2_end,"
                    "complete,updated) VALUES (?,?,?,?,?,?,?)",
                    (key, sector, mc, -1, 0, 1, _now()))
            return
        row = self.cx.execute("SELECT n2_max,n2_end FROM boxels WHERE key=?",
                              (p.boxel_key,)).fetchone()
        known_here = self.system(name) is not None or n2_end is None
        n2_max = row["n2_max"] if row and row["n2_max"] is not None else -1
        if n2_end is None:
            n2_max = max(n2_max, p.n2)
        end = row["n2_end"] if row else None
        if n2_end is not None and (end is None or n2_end < end):
            end = n2_end
        complete = 1 if (end is not None and n2_max >= end - 1) else 0
        self.cx.execute(
            "INSERT OR REPLACE INTO boxels(key,sector,mc,n2_max,n2_end,complete,updated)"
            " VALUES (?,?,?,?,?,?,?)",
            (p.boxel_key, p.sector, p.mc, n2_max, end, complete, _now()))

    def known_n2(self, boxel_key: str) -> Set[int]:
        """Every n2 known for one boxel."""
        out: Set[int] = set()
        for (nm,) in self.cx.execute("SELECT name FROM systems WHERE name LIKE ?",
                                     (boxel_key + "-%",)):
            p = parse_name(nm)
            if p and p.boxel_key == boxel_key:
                out.add(p.n2)
        return out

    def close_boxel(self, boxel_key: str) -> int:
        """
        Declare a boxel finished after seeing its full list in the galaxy map.
        The end is set just above the highest known n2, so every remaining
        candidate for that boxel disappears at once. Returns that end value.
        """
        known = self.known_n2(boxel_key)
        end = (max(known) + 1) if known else 0
        row = self.cx.execute("SELECT sector, mc FROM boxels WHERE key=?",
                              (boxel_key,)).fetchone()
        sector = row["sector"] if row else None
        mc = row["mc"] if row else None
        if sector is None:
            p = parse_name(boxel_key + "-0")
            if p:
                sector, mc = p.sector, p.mc
        self.cx.execute(
            "INSERT OR REPLACE INTO boxels(key,sector,mc,n2_max,n2_end,complete,"
            "updated) VALUES (?,?,?,?,?,1,?)",
            (boxel_key, sector, mc, max(known) if known else -1, end, _now()))
        self.cx.commit()
        return end

    def boxel_end(self, key: str) -> Optional[int]:
        r = self.cx.execute("SELECT n2_end FROM boxels WHERE key=?", (key,)).fetchone()
        return r["n2_end"] if r else None

    def boxel_n2_map(self) -> Dict[str, Set[int]]:
        """boxel_key -> set of known n2 values. Called once per plan run."""
        out: Dict[str, Set[int]] = {}
        for (nm,) in self.cx.execute("SELECT name FROM systems"):
            p = parse_name(nm)
            if p:
                out.setdefault(p.boxel_key, set()).add(p.n2)
        return out

    # ------------------------------------------------------------- scan state
    def _body_upsert(self, sys_id64: int, body_id: int, commit: bool = True,
                     **fields) -> None:
        if sys_id64 is None or body_id is None:
            return
        row = self.cx.execute(
            "SELECT 1 FROM bodies WHERE sys_id64=? AND body_id=?",
            (sys_id64, body_id)).fetchone()
        if row is None:
            self.cx.execute("INSERT INTO bodies(sys_id64,body_id,updated) VALUES (?,?,?)",
                            (sys_id64, body_id, _now()))
        if fields:
            cols, args = [], []
            for k, v in fields.items():
                if v is None:
                    continue
                cols.append("%s=?" % k); args.append(v)
            if cols:
                cols.append("updated=?"); args.append(_now())
                args += [sys_id64, body_id]
                self.cx.execute("UPDATE bodies SET %s WHERE sys_id64=? AND body_id=?"
                                % ",".join(cols), args)
        if commit:
            self.cx.commit()

    def system_progress(self, id64: Optional[int]) -> Dict[str, object]:
        """What is still outstanding in this system?"""
        empty = {"body_count": None, "scanned": 0, "mapped": 0, "fss_complete": False,
                 "dss_open": [], "bio_open": [], "new_discoveries": 0, "valuable": []}
        if not id64:
            return empty
        s = self.system_by_id64(id64)
        rows = self.cx.execute("SELECT * FROM bodies WHERE sys_id64=?", (id64,)).fetchall()
        scanned = sum(1 for r in rows if r["scanned"])
        mapped = sum(1 for r in rows if r["mapped"])
        dss_open, bio_open, valuable = [], [], []
        for r in rows:
            worth = (r["sig_bio"] or 0) > 0 or (r["planet_class"] in VALUABLE_CLASSES) \
                or (r["terraform"] or "") == "Terraformable"
            if r["kind"] == "Planet" and worth and not r["mapped"]:
                dss_open.append(r["name"] or "Body %d" % r["body_id"])
            if (r["sig_bio"] or 0) > 0 and (r["organics"] or 0) == 0:
                bio_open.append(r["name"] or "Body %d" % r["body_id"])
            if r["planet_class"] in VALUABLE_CLASSES or (r["terraform"] or "") == "Terraformable":
                valuable.append((r["name"], r["planet_class"], r["terraform"]))
        return {
            "body_count": s["body_count"] if s else None,
            "scanned": scanned,
            "mapped": mapped,
            "fss_complete": bool(s["fss_complete"]) if s else False,
            "dss_open": dss_open,
            "bio_open": bio_open,
            "new_discoveries": sum(1 for r in rows if r["was_discovered"] == 0),
            "valuable": valuable,
        }

    def unfinished_systems(self, center: Sequence[float], radius: float
                           ) -> List[Dict[str, object]]:
        """Visited systems inside the sphere that still have work outstanding."""
        out = []
        for r in self.sphere(center, radius):
            if not r["visited"] or not r["id64"]:
                continue
            p = self.system_progress(r["id64"])
            need_fss = (p["body_count"] is not None
                        and p["scanned"] < p["body_count"] and not p["fss_complete"])
            if need_fss or p["dss_open"] or p["bio_open"]:
                dist = math.dist((r["x"], r["y"], r["z"]), tuple(center))
                out.append({"name": r["name"], "id64": r["id64"], "dist": dist,
                            "fss": (p["scanned"], p["body_count"]),
                            "dss": p["dss_open"], "bio": p["bio_open"]})
        out.sort(key=lambda d: d["dist"])
        return out

    # -------------------------------------------------------------- ingestion
    def ingest_journal_event(self, entry: dict) -> int:
        """Process one journal event. Returns the number of records touched."""
        ev = entry.get("event")
        n = 0
        try:
            if ev in ("FSDJump", "Location", "CarrierJump"):
                pos = entry.get("StarPos")
                if entry.get("StarSystem") and pos and len(pos) >= 3:
                    self.upsert(entry["StarSystem"], pos[0], pos[1], pos[2],
                                id64=entry.get("SystemAddress"), quality=Q_JOURNAL,
                                source="journal", visited=True)
                    n += 1

            elif ev == "FSDTarget":
                nm = entry.get("Name") or entry.get("StarSystem")
                self.upsert(nm, id64=entry.get("SystemAddress"), quality=Q_CONFIRMED,
                            source="fsdtarget", star_class=entry.get("StarClass"))
                n += 1

            elif ev == "StartJump" and entry.get("JumpType") == "Hyperspace":
                nm = entry.get("StarSystem")
                if nm:
                    self.upsert(nm, id64=entry.get("SystemAddress"),
                                quality=Q_CONFIRMED, source="startjump",
                                star_class=entry.get("StarClass"))
                    n += 1

            elif ev in ("NavRoute", "Route"):
                for hop in entry.get("Route") or []:
                    pos = hop.get("StarPos")
                    if hop.get("StarSystem") and pos and len(pos) >= 3:
                        self.upsert(hop["StarSystem"], pos[0], pos[1], pos[2],
                                    id64=hop.get("SystemAddress"), quality=Q_JOURNAL,
                                    source="navroute", star_class=hop.get("StarClass"),
                                    commit=False)
                        n += 1
                self.cx.commit()

            elif ev == "FSSDiscoveryScan":
                a = entry.get("SystemAddress")
                self.upsert(entry.get("SystemName"), id64=a, quality=Q_CONFIRMED,
                            source="fss")
                self.cx.execute(
                    "UPDATE systems SET body_count=?, nonbody_count=?, updated=? WHERE id64=?",
                    (entry.get("BodyCount"), entry.get("NonBodyCount"), _now(), a))
                self.cx.commit(); n += 1

            elif ev == "FSSAllBodiesFound":
                a = entry.get("SystemAddress")
                self.upsert(entry.get("SystemName"), id64=a, quality=Q_CONFIRMED,
                            source="fss")
                self.cx.execute(
                    "UPDATE systems SET body_count=?, fss_complete=1, updated=? WHERE id64=?",
                    (entry.get("Count"), _now(), a))
                self.cx.commit(); n += 1

            elif ev in ("Scan", "ScanBaryCentre"):
                a = entry.get("SystemAddress")
                if a:
                    self.upsert(entry.get("StarSystem"), id64=a, quality=Q_CONFIRMED,
                                source="scan")
                    kind = ("Star" if entry.get("StarType") else
                            "Planet" if entry.get("PlanetClass") is not None else
                            "BaryCentre" if ev == "ScanBaryCentre" else "Other")
                    parent = None
                    for pr in (entry.get("Parents") or []):
                        if isinstance(pr, dict) and pr:
                            parent = list(pr.values())[0]
                            break
                    rings = entry.get("Rings") or []
                    ring_cls = ",".join(sorted({r.get("RingClass") for r in rings
                                                if r.get("RingClass")})) or None
                    ring_mass = sum(float(r.get("MassMT") or 0.0)
                                    for r in rings
                                    if r.get("RingClass") == "eRingClass_Icy")
                    self._body_upsert(
                        a, entry.get("BodyID"),
                        scan_ts=_epoch(entry.get("timestamp")),
                        ring_classes=ring_cls,
                        ring_mass=ring_mass or None,
                        star_type=entry.get("StarType"),
                        arrival_ls=entry.get("DistanceFromArrivalLS"),
                        parent_id=parent,
                        sma=entry.get("SemiMajorAxis"),
                        ecc=entry.get("Eccentricity"),
                        inc=entry.get("OrbitalInclination"),
                        peri=entry.get("Periapsis"),
                        node=entry.get("AscendingNode"),
                        mean_anom=entry.get("MeanAnomaly"),
                        period=entry.get("OrbitalPeriod"),
                        name=entry.get("BodyName"), kind=kind,
                        planet_class=entry.get("PlanetClass"),
                        terraform=entry.get("TerraformState"),
                        landable=1 if entry.get("Landable") else 0,
                        was_discovered=(1 if entry.get("WasDiscovered") else 0)
                        if "WasDiscovered" in entry else None,
                        was_mapped=(1 if entry.get("WasMapped") else 0)
                        if "WasMapped" in entry else None,
                        scanned=1)
                    n += 1

            elif ev == "SAAScanComplete":
                a = entry.get("SystemAddress")
                if a:
                    self._body_upsert(a, entry.get("BodyID"),
                                      name=entry.get("BodyName"), mapped=1)
                    n += 1

            elif ev in ("SAASignalsFound", "FSSBodySignals"):
                a = entry.get("SystemAddress")
                if a:
                    bio = geo = 0
                    for sig in entry.get("Signals") or []:
                        t = (sig.get("Type") or "")
                        c = sig.get("Count", 0)
                        if "Biological" in t:
                            bio += c
                        elif "Geological" in t:
                            geo += c
                    gen = ",".join(g.get("Genus_Localised") or g.get("Genus", "")
                                   for g in entry.get("Genuses") or []) or None
                    self._body_upsert(a, entry.get("BodyID"),
                                      name=entry.get("BodyName"),
                                      sig_bio=bio or None, sig_geo=geo or None,
                                      genuses=gen)
                    n += 1

            elif ev == "ScanOrganic":
                a = entry.get("SystemAddress")
                bid = entry.get("Body")
                if a and bid is not None and entry.get("ScanType") == "Analyse":
                    cur = self.cx.execute(
                        "SELECT organics FROM bodies WHERE sys_id64=? AND body_id=?",
                        (a, bid)).fetchone()
                    self._body_upsert(a, bid, organics=(cur["organics"] if cur else 0) + 1)
                    n += 1

            elif ev in ("CarrierJump", "CarrierLocation"):
                nm = entry.get("StarSystem")
                pos = entry.get("StarPos")
                a = entry.get("SystemAddress")
                if nm:
                    if pos and len(pos) >= 3:
                        self.upsert(nm, pos[0], pos[1], pos[2], id64=a,
                                    quality=Q_JOURNAL, source="carrier",
                                    visited=(ev == "CarrierJump"))
                    else:
                        self.upsert(nm, id64=a, quality=Q_CONFIRMED, source="carrier")
                    self.set_carrier(nm, a,
                                     tuple(pos[:3]) if pos and len(pos) >= 3 else None)
                    n += 1

            elif ev == "CarrierStats":
                self.set_meta("carrier_callsign", entry.get("Callsign") or "")
                self.set_meta("carrier_name", entry.get("Name") or "")

            elif ev == "Docked" and entry.get("StationType") == "FleetCarrier":
                nm = entry.get("StarSystem")
                if nm:
                    self.set_carrier(nm, entry.get("SystemAddress"),
                                     callsign=entry.get("StationName"))
                    n += 1

            elif ev == "CodexEntry":
                self.upsert(entry.get("System"), id64=entry.get("SystemAddress"),
                            quality=Q_CONFIRMED, source="codex")
                n += 1
        except Exception:
            raise
        return n

    def ingest_status_destination(self, dest: dict) -> Optional[str]:
        """
        Status.json -> Destination. The selected destination carries the id64
        even for systems that appear in no database at all; the name is
        rebuilt from it. Returns the system name if newly confirmed.
        """
        a = dest.get("System")
        if not a:
            return None
        nm = self.name_from_id64(a)
        if not nm:
            return None
        existed = self.system(nm) is not None
        self.upsert(nm, id64=a, quality=Q_CONFIRMED, source="destination")
        return None if existed else nm

    def ingest_external(self, systems: Iterable[dict], source: str) -> int:
        n = 0
        for s in systems:
            if self.upsert(s.get("name"), s.get("x"), s.get("y"), s.get("z"),
                           id64=s.get("id64"), quality=Q_EXTERNAL, source=source,
                           commit=False):
                n += 1
        self.cx.commit()
        return n

    # --------------------------------------------------------------- survey
    def save_survey(self, active: bool, start_system: Optional[str],
                    center: Optional[Sequence[float]], radius: float,
                    masscodes: Sequence[int]) -> None:
        c = tuple(center) if center else (None, None, None)
        self.cx.execute(
            "INSERT OR REPLACE INTO survey(id,active,start_system,cx,cy,cz,radius,"
            "masscodes,started,updated) VALUES (1,?,?,?,?,?,?,?,"
            "COALESCE((SELECT started FROM survey WHERE id=1),?),?)",
            (1 if active else 0, start_system, c[0], c[1], c[2], radius,
             ",".join(str(m) for m in masscodes), _now(), _now()))
        self.cx.commit()

    def load_survey(self) -> Optional[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM survey WHERE id=1").fetchone()

    # --------------------------------------------------------------- carrier
    def set_carrier(self, name: str, id64: Optional[int] = None,
                    coords: Optional[Sequence[float]] = None,
                    callsign: Optional[str] = None,
                    label: Optional[str] = None) -> None:
        """Remember where the fleet carrier is parked."""
        if not name:
            return
        if coords is None:
            row = self.system(name)
            if row and row["x"] is not None:
                coords = (row["x"], row["y"], row["z"])
            elif id64:
                try:
                    coords = decode_id64(id64)["center"]
                except Exception:
                    coords = None
        self.set_meta("carrier_system", name)
        if id64:
            self.set_meta("carrier_id64", id64)
        if coords:
            self.set_meta("carrier_pos", ",".join("%.5f" % c for c in coords))
        if callsign:
            self.set_meta("carrier_callsign", callsign)
        if label:
            self.set_meta("carrier_name", label)
        self.set_meta("carrier_updated", _now())

    def get_carrier(self) -> Optional[Dict[str, object]]:
        nm = self.get_meta("carrier_system")
        if not nm:
            return None
        pos = self.get_meta("carrier_pos")
        coords = None
        if pos:
            try:
                coords = tuple(float(v) for v in pos.split(","))
            except ValueError:
                coords = None
        if coords is None:
            row = self.system(nm)
            if row and row["x"] is not None:
                coords = (row["x"], row["y"], row["z"])
        i = self.get_meta("carrier_id64")
        return {"system": nm, "coords": coords,
                "id64": int(i) if i else None,
                "callsign": self.get_meta("carrier_callsign"),
                "name": self.get_meta("carrier_name"),
                "updated": self.get_meta("carrier_updated")}

    # -------------------------------------------------------------- spheres
    def record_sphere(self, center: Sequence[float], radius: float,
                      label: Optional[str], origin: str = "free") -> int:
        """Store a survey sphere in the history. Returns its id."""
        cur = self.cx.execute(
            "SELECT id FROM spheres WHERE ABS(cx-?)<0.01 AND ABS(cy-?)<0.01 "
            "AND ABS(cz-?)<0.01 AND ABS(radius-?)<0.01",
            (center[0], center[1], center[2], radius)).fetchone()
        if cur:
            return cur["id"]
        c = self.cx.execute(
            "INSERT INTO spheres(label,cx,cy,cz,radius,origin,started) "
            "VALUES (?,?,?,?,?,?,?)",
            (label, center[0], center[1], center[2], radius, origin, _now()))
        self.cx.commit()
        return c.lastrowid

    def close_sphere(self, sphere_id: int) -> None:
        self.cx.execute("UPDATE spheres SET closed=? WHERE id=?", (_now(), sphere_id))
        self.cx.commit()

    def list_spheres(self) -> List[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM spheres ORDER BY id").fetchall()

    @staticmethod
    def _lens_volume(r1: float, r2: float, d: float) -> float:
        """Volume shared by two spheres."""
        if d >= r1 + r2:
            return 0.0
        if d <= abs(r1 - r2):
            return 4.0 / 3.0 * math.pi * min(r1, r2) ** 3
        return (math.pi * (r1 + r2 - d) ** 2
                * (d * d + 2 * d * r2 - 3 * r2 * r2 + 2 * d * r1
                   + 6 * r1 * r2 - 3 * r1 * r1) / (12.0 * d))

    def sphere_overlap(self, center: Sequence[float], radius: float,
                       exclude_id: Optional[int] = None) -> Dict[str, object]:
        """
        How much does a planned sphere repeat previous work?
        Volume share plus the number of systems already visited inside it.
        """
        own = 4.0 / 3.0 * math.pi * radius ** 3
        worst = None
        union = 0.0
        for r in self.list_spheres():
            if exclude_id is not None and r["id"] == exclude_id:
                continue
            d = math.dist((r["cx"], r["cy"], r["cz"]), tuple(center))
            v = self._lens_volume(radius, r["radius"], d)
            if v <= 0:
                continue
            union += v
            if worst is None or v > worst[1]:
                worst = (r, v, d)
        rows = self.sphere(center, radius)
        visited = sum(1 for x in rows if x["visited"])
        return {
            "volume_pct": min(100.0, 100.0 * union / own) if own else 0.0,
            "worst_pct": (100.0 * worst[1] / own) if worst else 0.0,
            "worst_label": (worst[0]["label"] or "sphere %d" % worst[0]["id"]) if worst else None,
            "worst_distance": worst[2] if worst else None,
            "known": len(rows),
            "visited": visited,
            "clear_distance": radius * 2.0,
        }

    def bodies_of(self, sys_id64: int) -> List[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM bodies WHERE sys_id64=?",
                               (sys_id64,)).fetchall()

    # --------------------------------------------------------- source coverage
    EXTERNAL_SOURCES = ("EDDiscovery", "Spansh", "EDSM")

    def source_coverage(self, center: Sequence[float], radius: float
                        ) -> Dict[str, object]:
        """
        How well do the public databases agree about this region?

        A system that only one of three sources knows is a symptom of thin
        reporting - and thin reporting is exactly where undiscovered systems
        hide. The disagreement rate is therefore a usable prospecting signal.
        """
        rows = self.sphere(center, radius)
        by_count = {0: 0, 1: 0, 2: 0, 3: 0}
        per_source = {k: 0 for k in self.EXTERNAL_SOURCES}
        only_one = []
        for r in rows:
            have = {v for v in (r["sources"] or "").split(",") if v}
            ext = have & set(self.EXTERNAL_SOURCES)
            for e in ext:
                per_source[e] += 1
            by_count[min(3, len(ext))] = by_count.get(min(3, len(ext)), 0) + 1
            if len(ext) == 1:
                only_one.append(r["name"])
        total = len(rows)
        seen_ext = total - by_count[0]
        return {
            "total": total,
            "per_source": per_source,
            "by_count": by_count,
            "disagreement_pct": (100.0 * by_count[1] / seen_ext) if seen_ext else 0.0,
            "journal_only": by_count[0],
            "only_one_examples": only_one[:5],
        }

    # ---------------------------------------------------------------- reports
    def lifetime(self) -> Dict[str, object]:
        """
        Totals across everything the plugin has ever recorded.

        Distance flown is summed over consecutive visited systems ordered by
        when they were first visited - an approximation, but it is the only
        figure available without keeping a separate flight log, and it is
        right to within the odd out-of-order jump.
        """
        q = lambda s, *a: self.cx.execute(s, a).fetchone()[0]
        rows = self.cx.execute(
            "SELECT x, y, z FROM systems WHERE visited=1 AND x IS NOT NULL "
            "ORDER BY visited_ts").fetchall()
        ly = 0.0
        for a, b in zip(rows, rows[1:]):
            d = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
            if d < 500.0:            # ignore carrier hops and session gaps
                ly += d
        first = self.cx.execute(
            "SELECT MIN(first_seen) FROM systems").fetchone()[0]
        return {
            "systems_visited": q("SELECT COUNT(*) FROM systems WHERE visited=1"),
            "systems_known": q("SELECT COUNT(*) FROM systems"),
            "jumps_ly": ly,
            "bodies": q("SELECT COUNT(*) FROM bodies"),
            "mapped": q("SELECT COUNT(*) FROM bodies WHERE mapped=1"),
            "first_discoveries": q(
                "SELECT COUNT(*) FROM bodies WHERE was_discovered=0"),
            "first_mapped": q("SELECT COUNT(*) FROM bodies WHERE was_mapped=0 "
                              "AND mapped=1"),
            "bio_sampled": q("SELECT COUNT(*) FROM bodies WHERE organics>0"),
            "boxels_closed": q("SELECT COUNT(*) FROM boxels WHERE complete=1"),
            "not_there": q("SELECT COUNT(*) FROM absent"),
            "spheres": q("SELECT COUNT(*) FROM spheres"),
            "since": first or "?",
        }

    def stats(self) -> Dict[str, int]:
        q = lambda s, *a: self.cx.execute(s, a).fetchone()[0]
        return {
            "systems": q("SELECT COUNT(*) FROM systems"),
            "visited": q("SELECT COUNT(*) FROM systems WHERE visited=1"),
            "exact_journal": q("SELECT COUNT(*) FROM systems WHERE quality>=?", Q_JOURNAL),
            "exact_external": q("SELECT COUNT(*) FROM systems WHERE quality=?", Q_EXTERNAL),
            "confirmed_only": q("SELECT COUNT(*) FROM systems WHERE quality<=?", Q_CONFIRMED),
            "bodies": q("SELECT COUNT(*) FROM bodies"),
            "mapped": q("SELECT COUNT(*) FROM bodies WHERE mapped=1"),
            "first_discoveries": q("SELECT COUNT(*) FROM bodies WHERE was_discovered=0"),
            "negative_cache": q("SELECT COUNT(*) FROM absent"),
            "boxels": q("SELECT COUNT(*) FROM boxels"),
            "boxels_closed": q("SELECT COUNT(*) FROM boxels WHERE complete=1"),
            "sectors": q("SELECT COUNT(*) FROM sectors"),
        }

    # -------------------------------------------------------------- migration
    def import_neareststars(self, path: str) -> Tuple[int, int]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("Nearest", []) if isinstance(data, dict) else []
        ok = skipped = 0
        for s in rows:
            try:
                nm = str(s["Name"]).strip()
                if not nm:
                    skipped += 1; continue
                self.upsert(nm, float(s["X"]), float(s["Y"]), float(s["Z"]),
                            id64=s.get("id64"), quality=Q_EXTERNAL,
                            source="neareststars.json", commit=False)
                ok += 1
            except (KeyError, TypeError, ValueError):
                skipped += 1
        self.cx.commit()
        return ok, skipped

    def import_survey_state(self, path: str) -> Tuple[int, int]:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
        ok = 0
        for s in st.get("pending_systems", []):
            self.upsert(s.get("name"), s.get("x"), s.get("y"), s.get("z"),
                        id64=s.get("id64"), quality=Q_EXTERNAL,
                        source="survey_state", commit=False)
            ok += 1
        for s in (st.get("all_systems") or {}).values():
            self.upsert(s.get("name"), s.get("x"), s.get("y"), s.get("z"),
                        id64=s.get("id64"), quality=Q_EXTERNAL,
                        source="survey_state", commit=False)
            ok += 1
        vis = 0
        for nm in st.get("visited_names", []):
            self.upsert(nm, quality=Q_UNKNOWN, source="survey_state",
                        visited=True, commit=False)
            vis += 1
        self.cx.commit()
        return ok, vis

    def import_journals(self, journal_dir: str, max_files: int = 0,
                        progress=None) -> Dict[str, int]:
        """
        Replay existing journal files. Purely additive; the files are never
        modified. progress(done, total, filename) is called once per file.
        """
        import glob
        files = sorted(set(glob.glob(os.path.join(journal_dir, "Journal.*.log"))
                           + glob.glob(os.path.join(journal_dir, "Journal_*.log"))))
        if max_files:
            files = files[-max_files:]
        res = {"files": len(files), "events": 0, "lines": 0, "errors": 0}
        for i, fn in enumerate(files, 1):
            if progress:
                try:
                    progress(i, len(files), os.path.basename(fn))
                except Exception:
                    pass
            try:
                with open(fn, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        res["lines"] += 1
                        try:
                            res["events"] += self.ingest_journal_event(json.loads(line))
                        except Exception:
                            res["errors"] += 1
            except OSError:
                res["errors"] += 1
            self.cx.commit()
        self.cx.commit()
        return res
