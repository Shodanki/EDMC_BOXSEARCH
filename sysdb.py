# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
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
import glob
import json
import logging
import math
import os
import shutil
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from procgen import (MASSCODES, SectorRegistry, boxel_index_of_coords,
                     boxel_labels, computed_sector_index, decode_id64,
                     id64_of_slot, id64_slot, make_name, parse_boxel_key,
                     parse_name, star_pos)
from shells import INHABITED, inhabited_event

logger = logging.getLogger(__name__)

Q_UNKNOWN = 0
Q_ESTIMATE = 10
Q_CONFIRMED = 20
Q_EXTERNAL = 30
Q_JOURNAL = 40

SCHEMA_VERSION = 5          # 4: external_calls, fetched_shells (4.6 local-first)
                            # 5: exploration per commander (4.8, C1)

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
    route_done INTEGER NOT NULL DEFAULT 0, route_done_ts TEXT,
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

CREATE TABLE IF NOT EXISTS hotspots (
    sys_id64  INTEGER NOT NULL,
    body_id   INTEGER NOT NULL,
    body_name TEXT,
    material  TEXT NOT NULL,     -- 'Platinum', 'LowTemperatureDiamond', ...
    label     TEXT,              -- localised name where the game gives one
    count     INTEGER NOT NULL,  -- number of hotspots in that ring
    ring_class TEXT,
    found     TEXT,
    PRIMARY KEY (sys_id64, body_id, material)
);
CREATE INDEX IF NOT EXISTS ix_hot_mat ON hotspots(material);

CREATE TABLE IF NOT EXISTS earnings (
    ts       TEXT,
    kind     TEXT,              -- 'exploration' or 'organic'
    base     INTEGER,
    bonus    INTEGER,
    total    INTEGER,
    systems  INTEGER,
    bodies   INTEGER,
    detail   TEXT,
    PRIMARY KEY (ts, kind)
);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);

-- 4.3: what a body offers besides rings - planetary mining locations,
-- geological / biological / thargoid / guardian / human signals, the genera
-- the DSS names (Brain Trees!), codex sites. body_id -1 = whole system.
CREATE TABLE IF NOT EXISTS signals (
    sys_id64  INTEGER NOT NULL,
    body_id   INTEGER NOT NULL,
    body_name TEXT,
    kind      TEXT NOT NULL,     -- 'mining_location', 'geological', 'genus:Brain Trees' ...
    label     TEXT,
    count     INTEGER NOT NULL DEFAULT 1,
    found     TEXT,
    PRIMARY KEY (sys_id64, body_id, kind)
);
CREATE INDEX IF NOT EXISTS signals_kind ON signals(kind);

-- 4.3: where engineering materials were actually picked up. One row per
-- MaterialCollected event (timestamp in the key), so replaying a journal
-- never counts the same pickup twice.
CREATE TABLE IF NOT EXISTS material_finds (
    ts        TEXT NOT NULL,
    sys_id64  INTEGER NOT NULL,
    body_name TEXT,              -- NULL = in space, not near a body
    material  TEXT NOT NULL,
    label     TEXT,
    category  TEXT,
    count     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (ts, sys_id64, material)
);
CREATE INDEX IF NOT EXISTS material_finds_mat ON material_finds(material);

-- 4.4: the way you moved on a body (from Status.json, live only - no journal
-- holds it) and the places where something happened there.
CREATE TABLE IF NOT EXISTS surface_track (
    sys_id64  INTEGER NOT NULL,
    body_name TEXT NOT NULL,
    ts        REAL NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL, alt REAL, heading REAL,
    mode      TEXT,              -- 'ship', 'srv', 'foot'
    PRIMARY KEY (sys_id64, body_name, ts)
);
CREATE TABLE IF NOT EXISTS surface_marks (
    ts        TEXT NOT NULL,
    sys_id64  INTEGER NOT NULL,
    body_name TEXT NOT NULL,
    kind      TEXT NOT NULL,     -- touchdown, liftoff, srv_out, srv_in, disembark,
                                 -- srv_parked, embark, bio_log, bio_sample, bio_analyse,
                                 -- material, codex, settlement, screenshot,
                                 -- refined (one tonne from a Rhino rig)
    label     TEXT,
    detail    TEXT,              -- genus for bio marks, category for materials
    lat REAL, lon REAL,          -- NULL when the position is unknown
    PRIMARY KEY (ts, kind, body_name, label)
);
CREATE INDEX IF NOT EXISTS surface_marks_body ON surface_marks(sys_id64, body_name);

-- 4.6 local-first: one row per request to an outside service (netgate),
-- kept CALL_LOG_DAYS days - shows how gently the plugin asks EDSM/Spansh.
CREATE TABLE IF NOT EXISTS external_calls (
    id       INTEGER PRIMARY KEY,
    ts       REAL NOT NULL,            -- epoch seconds
    service  TEXT NOT NULL,            -- edsm | spansh | github
    endpoint TEXT NOT NULL,
    status   INTEGER NOT NULL,         -- HTTP status, 0 = no answer
    ok       INTEGER NOT NULL,
    ms       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS external_calls_ts ON external_calls(ts);

-- 4.6 local-first: which shell (centre, r_min..r_max) each online service
-- delivered completely, and until when that counts (5-14 days, random).
-- The systems themselves are in `systems`; this only says "asked already".
CREATE TABLE IF NOT EXISTS fetched_shells (
    id         INTEGER PRIMARY KEY,
    service    TEXT NOT NULL,          -- edsm | spansh
    cx REAL NOT NULL, cy REAL NOT NULL, cz REAL NOT NULL,
    r_min      REAL NOT NULL,
    r_max      REAL NOT NULL,
    fetched_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    systems    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS fetched_shells_svc ON fetched_shells(service, expires_at);

-- 4.8 (C1): more than one commander on one PC. What is KNOWN about a system
-- or body (positions, bodies, signals, rings, hotspots, finds) stays shared in
-- the tables above; what each commander EXPLORED (visited, FSS, scanned,
-- mapped, first discoveries, species analysed) is kept here per FID. The
-- shared columns (systems.visited, bodies.scanned ...) still mean "any
-- commander", so older readers keep working.
CREATE TABLE IF NOT EXISTS commanders (
    fid        TEXT PRIMARY KEY,       -- Frontier ID, 'F1234567'
    name       TEXT,
    carrier    INTEGER NOT NULL DEFAULT 0,   -- owns a fleet carrier
    first_seen TEXT,
    last_seen  TEXT
);
CREATE TABLE IF NOT EXISTS cmdr_logins (
    fid TEXT NOT NULL,
    ts  TEXT NOT NULL,                 -- LoadGame timestamp: one per session
    PRIMARY KEY (fid, ts)
);
CREATE TABLE IF NOT EXISTS cmdr_systems (
    fid          TEXT NOT NULL,
    sys_id64     INTEGER NOT NULL,
    visited_ts   TEXT,                 -- first arrival (journal time)
    fss_complete INTEGER NOT NULL DEFAULT 0,
    arrival_ts   TEXT,                 -- R3: the last arrival decided below
    start_body   INTEGER,              -- R3: route starts at this body (carrier)
    start_name   TEXT,                 --     NULL = at the main star
    lost_ts      TEXT,                 -- data of this system lost with the ship
    PRIMARY KEY (fid, sys_id64)
);
CREATE INDEX IF NOT EXISTS ix_cmdr_sys ON cmdr_systems(sys_id64);
CREATE TABLE IF NOT EXISTS cmdr_bodies (
    fid            TEXT NOT NULL,
    sys_id64       INTEGER NOT NULL,
    body_id        INTEGER NOT NULL,
    scanned        INTEGER NOT NULL DEFAULT 0,
    mapped         INTEGER NOT NULL DEFAULT 0,
    was_discovered INTEGER,            -- as this commander's own scan saw it
    was_mapped     INTEGER,
    was_footfalled INTEGER,
    organics       INTEGER NOT NULL DEFAULT 0,   -- distinct species analysed
    bio_species    TEXT,               -- JSON list, this commander's analyses
    -- data carried, not sold yet - lost when the ship is destroyed (Died)
    scan_open      INTEGER NOT NULL DEFAULT 0,
    map_open       INTEGER NOT NULL DEFAULT 0,
    scan_sold      INTEGER NOT NULL DEFAULT 0,
    map_sold       INTEGER NOT NULL DEFAULT 0,
    bio_open       TEXT,               -- JSON list of species analysed, not sold
    lost_ts        TEXT,               -- when data of this body was lost
    lost_what      TEXT,               -- JSON: "scan", "map", "bio:<species>" still to redo
    PRIMARY KEY (fid, sys_id64, body_id)
);
CREATE INDEX IF NOT EXISTS ix_cmdr_bod ON cmdr_bodies(sys_id64);
"""

# C1: the full journal replay that fills the per-commander tables; until it
# has run, readers fall back to the shared columns (any commander).
CMDR_READY = "upgrade_48_cmdr"
# events that change what a commander carries unsold (and loses with the ship)
LOSS_EVENTS = frozenset(("Scan", "SAAScanComplete", "ScanOrganic", "SellExplorationData",
                         "MultiSellExplorationData", "SellOrganicData", "Died"))
LOSS_REPLAY = "upgrade_48_lost"     # one replay fills the carried / lost state
# the columns of a body that are exploration (per commander), not knowledge
EXPLORE_COLS = ("scanned", "mapped", "was_discovered", "was_mapped",
                "was_footfalled", "organics", "bio_species")
PLAN = "plan"            # system_progress(fid=PLAN): the main commander
CURRENT = "current"      # ... fid=CURRENT: the commander playing now

CALL_LOG_DAYS = 30


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


# One-time data repairs; each sets its meta key when done. A database that
# still misses one of them (or has another schema version) gets a backup
# before it is touched.
REPAIRS = ("fix_phantoms", "fix_marks45", "fix_n1zero", "fix_lost_ticks",
           "fix_boxel_end410")
BACKUP_KEEP = 3          # newest backups kept next to the database


def stored_state(path: str) -> Optional[Tuple[int, Set[str]]]:
    """(schema version, repairs done) of an existing database, read only.

    None for a missing or empty file - a new database needs no backup.
    A database without the meta table counts as schema 0.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    cx = sqlite3.connect(path, timeout=15.0)
    try:
        tables = {r[0] for r in cx.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables:
            return None
        if "meta" not in tables:
            return 0, set()
        meta = dict(cx.execute("SELECT k, v FROM meta").fetchall())
    finally:
        cx.close()
    try:
        version = int(meta.get("schema") or 0)
    except ValueError:
        version = 0
    return version, {k for k in REPAIRS if meta.get(k)}


def needs_migration(state: Optional[Tuple[int, Set[str]]]) -> bool:
    if state is None:
        return False
    version, done = state
    return version != SCHEMA_VERSION or not set(REPAIRS) <= done


def backup_database(path: str, tag: str, keep: int = BACKUP_KEEP) -> str:
    """Copy the database (WAL included, via SQLite's backup API) to
    <path>.<tag>-<UTC stamp>.bak and keep only the newest `keep` backups.
    Raises OSError when the disk lacks room for the copy."""
    size = os.path.getsize(path)
    if os.path.exists(path + "-wal"):
        size += os.path.getsize(path + "-wal")
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(path))).free
    if free < size * 1.2 + 10 * 1024 * 1024:
        raise OSError("not enough disk space for a backup (%d MB free)"
                      % (free // (1024 * 1024)))
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dst_path = "%s.%s-%s.bak" % (path, tag, stamp)
    n = 1
    while os.path.exists(dst_path):          # two migrations in one second
        n += 1
        dst_path = "%s.%s-%s-%d.bak" % (path, tag, stamp, n)
    src = sqlite3.connect(path, timeout=15.0)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(glob.glob(glob.escape(path) + ".*.bak"),
                 key=lambda f: (os.path.getmtime(f), f), reverse=True)
    for f in old[max(1, keep):]:
        try:
            os.remove(f)
        except OSError:
            logger.warning("could not remove old backup %s", f)
    return dst_path


class SystemDB:
    """All writes are idempotent and commit-safe."""

    def __init__(self, path: str):
        self.path = path
        self.backup_path: Optional[str] = None
        self._dock_market_id: Optional[int] = None
        try:
            state = stored_state(path)
        except sqlite3.Error:
            logger.exception("could not read the database version")
            state = (0, set())
        if needs_migration(state):
            # "your data": copy it before a schema change or repair touches it.
            # The changes themselves only add tables and columns, so a failed
            # backup is reported but does not stop the plugin.
            try:
                self.backup_path = backup_database(path, "schema%d" % state[0])
                logger.info("database backup before migration: %s",
                            os.path.basename(self.backup_path))
            except Exception:
                logger.exception("database backup before migration failed - "
                                 "migrating without a backup")
        self.cx = sqlite3.connect(path, check_same_thread=False, timeout=15.0)
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(SCHEMA)
        self._migrate()
        self.cx.execute("INSERT OR REPLACE INTO meta(k,v) VALUES ('schema',?)",
                        (str(SCHEMA_VERSION),))
        if state is None:
            # a new database has no history to sort per commander: whatever
            # it learns from now on (or from the first import) is per FID
            self.cx.execute("INSERT OR IGNORE INTO meta(k,v) VALUES (?,?)",
                            (CMDR_READY, _now()))
        self.cx.commit()
        # C1: the commander whose events arrive now (Commander / LoadGame or
        # EDMC's state) and the main commander the survey plans for
        self.fid: Optional[str] = None
        self.fid_name: Optional[str] = None
        self.plan_fid: Optional[str] = None
        self._cmdr_written: Optional[Tuple[str, Optional[str]]] = None
        self.prune_external_calls()
        self.prune_shells()
        self.sectors = SectorRegistry()
        self._load_sectors()
        # where the commander is, for MaterialCollected (which names no body)
        self._here_sys: Optional[int] = None
        self._here_body: Optional[str] = None
        # last Status.json position on a body (live only), for marks whose
        # journal event carries no position (ScanOrganic, MaterialCollected)
        self._pos: Optional[Dict[str, Any]] = None
        self._vehicle: Optional[str] = None     # SRV type of the last launch
        self._refine_ts: Optional[str] = None    # same-second MiningRefined
        self._refine_seq = 0
        self.marks_rev = 0                      # bumped on every new mark

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
                         ("star_type", "TEXT"), ("scan_ts", "REAL"),
                         ("route_done", "INTEGER"),
                         ("route_done_ts", "TEXT"),
                         # 4.1: physical data - bio prediction and body details
                         ("radius", "REAL"),          # metres
                         ("mass_em", "REAL"),         # planets, earth masses
                         ("gravity", "REAL"),         # m/s^2 (journal unit)
                         ("temp_k", "REAL"),          # surface temperature
                         ("pressure", "REAL"),        # Pa
                         ("atmosphere", "TEXT"),
                         ("atmo_type", "TEXT"),
                         ("atmo_comp", "TEXT"),       # JSON {name: percent}
                         ("volcanism", "TEXT"),
                         ("composition", "TEXT"),     # JSON {Ice, Rock, Metal}
                         ("materials", "TEXT"),       # JSON {name: percent}
                         ("tidal_lock", "INTEGER"),
                         ("axial_tilt", "REAL"),      # radians
                         ("rotation", "REAL"),        # seconds
                         ("was_footfalled", "INTEGER"),
                         ("rings_json", "TEXT"),      # JSON list incl. radii
                         ("reserve", "TEXT"),
                         ("stellar_mass", "REAL"),
                         ("abs_mag", "REAL"),
                         ("age_my", "REAL"),
                         ("luminosity", "TEXT"),
                         ("subclass", "INTEGER"),
                         ("bio_species", "TEXT")):    # JSON list, ScanOrganic
            if col not in bhave:
                self.cx.execute("ALTER TABLE bodies ADD COLUMN %s %s" % (col, typ))
        chave = {r[1] for r in self.cx.execute("PRAGMA table_info(cmdr_systems)")}
        for col, typ in (("arrival_ts", "TEXT"), ("start_body", "INTEGER"),
                         ("start_name", "TEXT"), ("lost_ts", "TEXT")):
            if col not in chave:
                self.cx.execute("ALTER TABLE cmdr_systems ADD COLUMN %s %s" % (col, typ))
        bchave = {r[1] for r in self.cx.execute("PRAGMA table_info(cmdr_bodies)")}
        for col, typ in (("scan_open", "INTEGER NOT NULL DEFAULT 0"),
                         ("map_open", "INTEGER NOT NULL DEFAULT 0"),
                         ("scan_sold", "INTEGER NOT NULL DEFAULT 0"),
                         ("map_sold", "INTEGER NOT NULL DEFAULT 0"),
                         ("bio_open", "TEXT"), ("lost_ts", "TEXT"), ("lost_what", "TEXT")):
            if col not in bchave:
                self.cx.execute("ALTER TABLE cmdr_bodies ADD COLUMN %s %s" % (col, typ))
        self.cx.commit()
        if not self.get_meta("fix_phantoms"):
            try:
                n = self.repair_phantoms()
                logger.info("database repair (destination phantoms): %d removed", n)
            except Exception:
                logger.exception("database repair (destination phantoms) failed")
        if not self.get_meta("fix_marks45"):
            try:
                res = self.repair_marks45()
                logger.info("database repair (SRV parked / vehicle landings): %s", res)
            except Exception:
                logger.exception("database repair (surface marks) failed")
        if not self.get_meta("fix_lost_ticks") and self.get_meta(LOSS_REPLAY):
            try:
                n = self.repair_lost_ticks()
                logger.info("database repair (route ticks of data lost in a crash): %d cleared", n)
            except Exception:
                logger.exception("database repair (lost route ticks) failed")
        elif not self.get_meta("fix_lost_ticks"):
            self.set_meta("fix_lost_ticks", _now())     # nothing lost recorded yet
        if not self.get_meta("fix_n1zero"):
            try:
                res = self.repair_n1zero()
                logger.info("database repair (n1=0 naming rule): %s", res)
            except Exception:
                logger.exception("database repair (n1=0 naming rule) failed")
        if not self.get_meta("fix_boxel_end410"):
            try:
                res = self.repair_boxel_ends()
                logger.info("database repair (boxel ends below a known system): %s", res)
            except Exception:
                logger.exception("database repair (boxel ends) failed")

    def repair_boxel_ends(self) -> Dict[str, int]:
        """
        One-time repair (4.10): a boxel must not end at or below a system
        that exists in it.

        Up to 4.10 "not there" closed the boxel at that number, also when a
        higher number was known - the slot below can be a catalogue star
        ("HIP 33254" is n2 = 0 of "Synuefe RH-U c19"), so its procedural name
        is missing from the galaxy map while the boxel runs on to 21. Such an
        end is dropped; the boxel is open again and the planner decides anew.
        The absent name itself stays recorded - that name really is not there.
        """
        rows = self.cx.execute(
            "SELECT key, n2_max, n2_end FROM boxels WHERE n2_end IS NOT NULL").fetchall()
        reopened = 0
        for r in rows:
            top = self.boxel_known_max(r["key"])
            if top is not None and top >= r["n2_end"]:
                self.cx.execute("UPDATE boxels SET n2_end=NULL, complete=0, n2_max=?, "
                                "updated=? WHERE key=?", (top, _now(), r["key"]))
                reopened += 1
        self.set_meta("fix_boxel_end410", _now())
        self.cx.commit()
        return {"boxels_with_end": len(rows), "reopened": reopened}

    def repair_n1zero(self) -> Dict[str, int]:
        """
        One-time repair for the pre-4.1 naming bug.

        Up to 4.0 "Synuefe XV-C d12" was read as "boxel XV-C d12 holds exactly
        one system" and that boxel was closed. In truth it is system n2=12 of
        boxel "XV-C d" (n1 = 0). Two kinds of rows are therefore wrong:

        * boxels with an n1 = 0 key ("... d"): every probe ever generated for
          them used a name of the form "XV-C d-3" that does not exist in the
          game, so any closure of such a boxel was based on a search that
          could never have found anything.
        * boxels whose key is the name of such a system ("... d12"): closed by
          the old shortcut, although the real boxel d12 (d12-0, d12-1 ...)
          was never looked at.

        Both are rebuilt from scratch from the systems we know and from the
        absent entries that are still valid. Nothing the commander flew for is
        touched.
        """
        sysnames = [r[0] for r in self.cx.execute("SELECT name FROM systems")]
        n1zero_names = set()
        for nm in sysnames:
            p = parse_name(nm)
            if p and p.n1 == 0:
                n1zero_names.add(nm)
        absent_by_key: Dict[str, List[Tuple[str, int]]] = {}
        bad_absent = []
        for nm, key in self.cx.execute("SELECT name, boxel FROM absent").fetchall():
            p = parse_name(nm)
            if p is None:
                bad_absent.append(nm)       # e.g. old "XV-C d-3" form
            else:
                absent_by_key.setdefault(p.boxel_key, []).append((nm, p.n2))

        reset: List[str] = []
        for r in self.cx.execute(
                "SELECT key, n2_max, n2_end FROM boxels").fetchall():
            key = r["key"]
            if key[-1:].isalpha():
                reset.append(key)
            elif key in n1zero_names and (r["n2_max"] is None or r["n2_max"] < 0) \
                    and r["n2_end"] == 0 and key not in absent_by_key:
                reset.append(key)
            elif key in n1zero_names and r["n2_end"] == 0 \
                    and not any(n2 == 0 for _, n2 in absent_by_key.get(key, [])):
                # overwritten later by a real system, but still carries the
                # bogus end=0 of the old shortcut
                reset.append(key)

        for nm in bad_absent:
            self.cx.execute("DELETE FROM absent WHERE name=?", (nm,))
        for key in reset:
            self.cx.execute("DELETE FROM boxels WHERE key=?", (key,))
        reset_set = set(reset)
        # rebuild what is known about the reset boxels and every n1 = 0 boxel
        touched = 0
        for nm in sysnames:
            p = parse_name(nm)
            if p and (p.n1 == 0 or p.boxel_key in reset_set):
                self._touch_boxel(nm)
                touched += 1
        for key in reset_set:
            for nm, n2 in absent_by_key.get(key, []):
                self._touch_boxel(nm, n2_end=n2)
        self.set_meta("fix_n1zero", _now())
        self.cx.commit()
        return {"boxels_reset": len(reset), "bad_absent_removed": len(bad_absent),
                "systems_retouched": touched, "n1zero_systems": len(n1zero_names)}

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

    # ------------------------------------------------------ external calls
    def log_external_calls(self, records: Iterable[Sequence[Any]]) -> int:
        """Store netgate records (ts, service, endpoint, status, ok, ms)."""
        rows = [(float(r[0]), str(r[1]), str(r[2]), int(r[3]), 1 if r[4] else 0,
                 int(r[5])) for r in records]
        if rows:
            self.cx.executemany(
                "INSERT INTO external_calls(ts, service, endpoint, status, ok, ms)"
                " VALUES (?,?,?,?,?,?)", rows)
            self.cx.commit()
        return len(rows)

    def external_calls_since(self, since: float,
                             service: Optional[str] = None) -> int:
        if service:
            r = self.cx.execute("SELECT COUNT(*) FROM external_calls "
                                "WHERE ts>=? AND service=?", (since, service))
        else:
            r = self.cx.execute("SELECT COUNT(*) FROM external_calls WHERE ts>=?",
                                (since,))
        return int(r.fetchone()[0])

    def prune_external_calls(self, days: int = CALL_LOG_DAYS) -> int:
        n = self.cx.execute("DELETE FROM external_calls WHERE ts<?",
                            (time.time() - days * 86400.0,)).rowcount
        self.cx.commit()
        return n

    # ------------------------------------------------------ fetched shells
    def record_shell(self, service: str, center: Sequence[float], r_min: float,
                     r_max: float, systems: int, ttl_s: float,
                     now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self.cx.execute(
            "INSERT INTO fetched_shells(service, cx, cy, cz, r_min, r_max,"
            " fetched_at, expires_at, systems) VALUES (?,?,?,?,?,?,?,?,?)",
            (service, float(center[0]), float(center[1]), float(center[2]),
             float(r_min), float(r_max), now, now + float(ttl_s), int(systems)))
        self.cx.commit()

    def valid_shells(self, service: str, now: Optional[float] = None
                     ) -> List[Tuple[float, float, float, float, float]]:
        """Regions (cx, cy, cz, r_min, r_max) the service delivered and that
        are still valid."""
        now = time.time() if now is None else now
        return [(r[0], r[1], r[2], r[3], r[4]) for r in self.cx.execute(
            "SELECT cx, cy, cz, r_min, r_max FROM fetched_shells"
            " WHERE service=? AND expires_at>?", (service, now))]

    def prune_shells(self, keep_days: int = 60) -> int:
        """Forget shells that expired more than keep_days ago."""
        n = self.cx.execute("DELETE FROM fetched_shells WHERE expires_at<?",
                            (time.time() - keep_days * 86400.0,)).rowcount
        self.cx.commit()
        return n

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
        """Rebuild the procgen name from an id64 alone - only when the boxel
        can carry one name. Inside a hand-authored sector the name is that
        sector's; where the sector's surface cuts the boxel the id64 cannot
        tell which name the star has, so None (4.10; before, the procedural
        name was invented there)."""
        try:
            d = decode_id64(id64)
            per = 128 >> d["mc"]
            g = tuple(s * per + b for s, b in zip(d["sector_idx"], d["boxel"]))
            labels = boxel_labels(g, d["mc"], self.sectors.resolve)
            if len(labels) != 1:
                return None
            sect, bx = labels[0]
            return make_name(sect, d["mc"], bx, d["n2"])
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

    def mark_inhabited(self, name: Optional[str], id64: Optional[int]) -> int:
        """I1: population, factions or a station seen in the journal - the
        system is known to every database without asking. Stored as the
        pseudo source 'inhabited' (no schema change). 1 when newly marked."""
        if not name and not id64:
            return 0
        if name:
            self.upsert(name, id64=id64, quality=Q_ESTIMATE, source="journal")
        row = (self.system_by_id64(id64) if id64 else None) or (
            self.system(name) if name else None)
        if row is None:
            return 0
        have = set((row["sources"] or "").split(",")) - {""}
        if INHABITED in have:
            return 0
        have.add(INHABITED)
        self.cx.execute("UPDATE systems SET sources=?, updated=? WHERE name=?",
                        (",".join(sorted(have)), _now(), row["name"]))
        self.cx.commit()
        return 1

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
        fid = self.view_fid(PLAN)
        if fid and out:
            # C1: the survey plans for the main commander - "visited" and
            # "FSS complete" are his, the systems themselves are shared
            mine = self.visited_by(fid)
            own = []
            for r in out:
                d = dict(r)
                m = mine.get(r["id64"]) if r["id64"] else None
                d["visited"] = 1 if m is not None and m["visited_ts"] else 0
                d["visited_ts"] = m["visited_ts"] if m is not None else None
                d["fss_complete"] = m["fss_complete"] if m is not None else 0
                own.append(d)
            out = own
        return out

    # ------------------------------------------------------------ negative cache
    def mark_absent(self, name: str) -> bool:
        """The galaxy map does not know this name. True when that closes
        the boxel there (n2 runs on from 0, so nothing above it exists).

        Below the highest system known in the boxel it closes nothing: that
        slot exists under another name (a catalogue star such as "HIP 33254"
        fills "Synuefe RH-U c19-0"), only this one name is ruled out."""
        name = name.strip()
        p = parse_name(name)
        self.cx.execute(
            "INSERT OR REPLACE INTO absent(name,boxel,n2,ts) VALUES (?,?,?,?)",
            (name, p.boxel_key if p else None, p.n2 if p else None, _now()))
        closes = False
        if p:
            top = self.boxel_known_max(p.boxel_key)
            closes = top is None or p.n2 > top
            if closes:
                self._touch_boxel(name, n2_end=p.n2)
        self.cx.commit()
        return closes

    def unmark_absent(self, name: str) -> None:
        self.cx.execute("DELETE FROM absent WHERE name=?", (name.strip(),))
        self.cx.commit()

    def absent_set(self) -> Set[str]:
        return {r[0] for r in self.cx.execute("SELECT name FROM absent")}

    # ------------------------------------------------------------------ boxel
    def _touch_boxel(self, name: str, n2_end: Optional[int] = None) -> None:
        p = parse_name(name)
        if p is None:
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

    def boxel_gidx(self, boxel_key: str) -> Optional[Tuple[int, Tuple[int, int, int]]]:
        """(mass code, global index) of the physical boxel behind a label -
        from a system of it with an id64 or a position, else computed for a
        procedural sector. None when nothing tells."""
        pk = parse_boxel_key(boxel_key)
        if pk is None:
            return None
        for r in self.cx.execute("SELECT name, id64, x, y, z FROM systems WHERE name LIKE ?",
                                 (boxel_key + "%",)):
            p = parse_name(r["name"])
            if p is None or p.boxel_key != boxel_key:
                continue
            if r["id64"]:
                mc, g, _n2 = id64_slot(int(r["id64"]))
                if mc == pk.mc:
                    return mc, g
            if r["x"] is not None:
                return pk.mc, boxel_index_of_coords(r["x"], r["y"], r["z"], pk.mc)
        si = computed_sector_index(pk.sector)
        if si is None:
            return None
        per = 128 >> pk.mc
        return pk.mc, tuple(s * per + b for s, b in zip(si, pk.boxel))  # type: ignore[return-value]

    def slot_n2(self, mc: int, gidx: Sequence[int]) -> Set[int]:
        """Every n2 some system with an id64 fills in one physical boxel -
        whatever its name (catalogue stars included)."""
        low = id64_of_slot(mc, gidx, 0)
        shift = 44 - 3 * mc
        mask = (1 << shift) - 1
        out: Set[int] = set()
        for (i,) in self.cx.execute(
                "SELECT id64 FROM systems WHERE id64 IS NOT NULL AND (id64 & ?) = ?",
                (mask, low)):
            out.add((int(i) >> shift) & ((1 << (11 + 3 * mc)) - 1))
        return out

    def slot_map(self) -> Dict[Tuple[int, Tuple[int, int, int]], Set[int]]:
        """(mass code, global boxel index) -> filled n2, from every id64.
        Called once per plan run."""
        out: Dict[Tuple[int, Tuple[int, int, int]], Set[int]] = {}
        for (i,) in self.cx.execute("SELECT id64 FROM systems WHERE id64 IS NOT NULL"):
            try:
                mc, g, n2 = id64_slot(int(i))
            except (TypeError, ValueError):
                continue
            out.setdefault((mc, g), set()).add(n2)
        return out

    def known_n2(self, boxel_key: str) -> Set[int]:
        """Every n2 known for one boxel: by name, and (4.10) every slot a
        system with an id64 fills there under any name."""
        out: Set[int] = set()
        # "XV-C d" (n1 = 0) holds "XV-C d0", "XV-C d1" ...; "VA-I b2" holds
        # "VA-I b2-0" ... - one LIKE covers both, the parse below filters.
        for (nm,) in self.cx.execute("SELECT name FROM systems WHERE name LIKE ?",
                                     (boxel_key + "%",)):
            p = parse_name(nm)
            if p and p.boxel_key == boxel_key:
                out.add(p.n2)
        where = self.boxel_gidx(boxel_key)
        if where is not None:
            out |= self.slot_n2(*where)
        return out

    def boxel_known_max(self, boxel_key: str) -> Optional[int]:
        """The highest n2 known to exist in a boxel, or None."""
        known = self.known_n2(boxel_key)
        return max(known) if known else None

    def close_boxel(self, boxel_key: str, last: Optional[int] = None) -> Optional[int]:
        """
        Declare a boxel finished after seeing its full list in the galaxy map.

        last is the highest number the galaxy map listed (4.10: "list ends
        at"). Every slot up to it exists - a number missing from the list is
        a catalogue star - so the end is last + 1 and the numbers up to it
        nobody knows yet become certain gaps. A last below a known system is
        refused (None): the list was cut off or it is the wrong boxel.
        Without last, the end is just above the highest known n2. Returns
        the end.
        """
        known = self.known_n2(boxel_key)
        top = max(known) if known else -1
        if last is not None:
            if last < top:
                return None
            top = last
        end = top + 1
        row = self.cx.execute("SELECT sector, mc FROM boxels WHERE key=?",
                              (boxel_key,)).fetchone()
        sector = row["sector"] if row else None
        mc = row["mc"] if row else None
        if sector is None:
            p = parse_boxel_key(boxel_key)
            if p:
                sector, mc = p.sector, p.mc
        self.cx.execute(
            "INSERT OR REPLACE INTO boxels(key,sector,mc,n2_max,n2_end,complete,"
            "updated) VALUES (?,?,?,?,?,1,?)",
            (boxel_key, sector, mc, top, end, _now()))
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

    def _link_parents(self, sys_id64: int, parents) -> None:
        """
        Give barycentres their parent, from a body's Parents chain.

        ScanBaryCentre carries orbital elements but no Parents, so a
        barycentre never learnt what it orbits and was placed around the
        system origin. Binary moons (two moons around a common barycentre
        that orbits a planet) then appeared thousands of LS away from their
        planet. The chain of any body below the barycentre names each link:
        [{"Null": 35}, {"Planet": 30}, {"Null": 29}, {"Star": 0}] means
        barycentre 35 orbits planet 30, barycentre 29 orbits star 0.
        """
        chain = [list(p.items())[0] for p in (parents or [])
                 if isinstance(p, dict) and p]
        for (kind, node), (_k, up) in zip(chain, chain[1:]):
            if kind != "Null":
                continue                # real bodies get theirs from their own Scan
            row = self.cx.execute("SELECT parent_id FROM bodies WHERE sys_id64=? "
                                  "AND body_id=?", (sys_id64, node)).fetchone()
            if row is None:
                # barycentre not scanned (yet): placeholder, orbit unknown -
                # it then sits on its parent, which is far better than the origin
                self.cx.execute("INSERT INTO bodies(sys_id64,body_id,kind,parent_id,"
                                "updated) VALUES (?,?,?,?,?)",
                                (sys_id64, node, "BaryCentre", up, _now()))
            elif row["parent_id"] is None:
                self.cx.execute("UPDATE bodies SET parent_id=? WHERE sys_id64=? AND "
                                "body_id=?", (up, sys_id64, node))

    def system_progress(self, id64: Optional[int], fid: Optional[str] = PLAN
                        ) -> Dict[str, object]:
        """What is still outstanding in this system - for the main commander
        (default), the current one (CURRENT), a given FID or anyone (None)."""
        empty = {"body_count": None, "scanned": 0, "mapped": 0, "fss_complete": False,
                 "dss_open": [], "bio_open": [], "bio_signals_open": 0,
                 "new_discoveries": 0, "valuable": []}
        if not id64:
            return empty
        fid = self.view_fid(fid)
        s = self.system_by_id64(id64)
        rows = self.bodies_for(id64, fid)
        if fid:
            own = self.cmdr_system(fid, id64)
            s = dict(s) if s is not None else None
            if s is not None:
                s["fss_complete"] = own["fss_complete"] if own else 0
        scanned = sum(1 for r in rows if r["scanned"])
        mapped = sum(1 for r in rows if r["mapped"])
        dss_open, bio_open, valuable = [], [], []
        bio_signals_open = 0
        for r in rows:
            worth = (r["sig_bio"] or 0) > 0 or (r["planet_class"] in VALUABLE_CLASSES) \
                or (r["terraform"] or "") == "Terraformable"
            if r["kind"] == "Planet" and worth and not r["mapped"]:
                dss_open.append(r["name"] or "Body %d" % r["body_id"])
            # M1: open = signals minus species analysed - a body with three
            # signals and one species done is still open (it used to count
            # as done as soon as one species was analysed)
            left = (r["sig_bio"] or 0) - (r["organics"] or 0)
            if left > 0:
                bio_open.append(r["name"] or "Body %d" % r["body_id"])
                bio_signals_open += left
            if r["planet_class"] in VALUABLE_CLASSES or (r["terraform"] or "") == "Terraformable":
                valuable.append((r["name"], r["planet_class"], r["terraform"]))
        return {
            "body_count": s["body_count"] if s else None,
            "scanned": scanned,
            "mapped": mapped,
            "fss_complete": bool(s["fss_complete"]) if s else False,
            "dss_open": dss_open,
            "bio_open": bio_open,
            "bio_signals_open": bio_signals_open,
            "new_discoveries": sum(1 for r in rows if r["was_discovered"] == 0),
            "valuable": valuable,
        }

    def unfinished_systems(self, center: Sequence[float], radius: float
                           ) -> List[Dict[str, object]]:
        """Visited systems inside the sphere that still have work outstanding
        (for the main commander, as the whole survey plan)."""
        out = []
        for r in self.sphere(center, radius):
            if not r["visited"] or not r["id64"]:
                continue
            p = self.system_progress(r["id64"], PLAN)
            need_fss = (p["body_count"] is not None
                        and p["scanned"] < p["body_count"] and not p["fss_complete"])
            if need_fss or p["dss_open"] or p["bio_open"]:
                dist = math.dist((r["x"], r["y"], r["z"]), tuple(center))
                out.append({"name": r["name"], "id64": r["id64"], "dist": dist,
                            "fss": (p["scanned"], p["body_count"]),
                            "dss": p["dss_open"], "bio": p["bio_open"]})
        out.sort(key=lambda d: d["dist"])
        return out

    # ------------------------------------------------- commanders (C1, 4.8)
    def cmdr_ready(self) -> bool:
        """Has the per-commander history been filled (one journal replay)?"""
        return bool(self.get_meta(CMDR_READY))

    def view_fid(self, fid: Optional[str]) -> Optional[str]:
        """Resolve PLAN / CURRENT to a FID; None = the shared view (anyone),
        also while the per-commander history is not filled yet."""
        if fid == PLAN:
            fid = self.plan_fid or self.fid
        elif fid == CURRENT:
            fid = self.fid
        if not fid or not self.cmdr_ready():
            return None
        return str(fid)

    def set_commander(self, fid: Optional[str], name: Optional[str] = None,
                      ts: Optional[str] = None) -> bool:
        """The commander whose events follow. True when it changed."""
        if not fid:
            return False
        fid = str(fid)
        changed = fid != self.fid
        self.fid = fid
        if name:
            self.fid_name = name
        elif changed:
            self.fid_name = None
        if self._cmdr_written != (fid, name) or ts:
            stamp = ts or _now()
            self.cx.execute(
                "INSERT INTO commanders(fid,name,first_seen,last_seen) VALUES (?,?,?,?) "
                "ON CONFLICT(fid) DO UPDATE SET name=COALESCE(excluded.name,name), "
                "first_seen=MIN(first_seen,excluded.first_seen), "
                "last_seen=MAX(last_seen,excluded.last_seen)",
                (fid, name, stamp, stamp))
            self.cx.commit()
            self._cmdr_written = (fid, name)
        return changed

    def _cmdr_event(self, ev: str, entry: dict) -> None:
        """Commander / LoadGame name the FID; carrier events mark an owner."""
        if ev in ("Commander", "LoadGame") and entry.get("FID"):
            self.set_commander(entry["FID"], entry.get("Name") or entry.get("Commander"),
                               entry.get("timestamp"))
            if ev == "LoadGame" and entry.get("timestamp"):
                self.cx.execute("INSERT OR IGNORE INTO cmdr_logins(fid,ts) VALUES (?,?)",
                                (self.fid, entry["timestamp"]))
        elif self.fid and (ev == "CarrierStats" or ev == "CarrierLocation") and \
                entry.get("CarrierType", "FleetCarrier") == "FleetCarrier":
            self.cx.execute("UPDATE commanders SET carrier=1 WHERE fid=? AND carrier=0",
                            (self.fid,))

    def _cmdr_system(self, a: Optional[int], ts: Optional[str] = None,
                     fss: bool = False) -> None:
        if not self.fid or not a:
            return
        self.cx.execute("INSERT OR IGNORE INTO cmdr_systems(fid,sys_id64) VALUES (?,?)",
                        (self.fid, a))
        if fss:
            self.cx.execute("UPDATE cmdr_systems SET fss_complete=1 WHERE fid=? AND sys_id64=?",
                            (self.fid, a))
        else:
            self.cx.execute("UPDATE cmdr_systems SET visited_ts=COALESCE(visited_ts,?) "
                            "WHERE fid=? AND sys_id64=?", (ts or _now(), self.fid, a))

    def _cmdr_body(self, a: Optional[int], bid: Optional[int], **cols) -> None:
        """This commander's exploration of a body. was_* keep the lowest value
        seen: once your scan saw 'undiscovered', it stays your discovery."""
        if not self.fid or a is None or bid is None:
            return
        self.cx.execute("INSERT OR IGNORE INTO cmdr_bodies(fid,sys_id64,body_id) "
                        "VALUES (?,?,?)", (self.fid, a, bid))
        sets, args = [], []
        for k, v in cols.items():
            if v is None:
                continue
            if k.startswith("was_"):
                sets.append("%s=MIN(COALESCE(%s,?),?)" % (k, k))
                args += [v, v]
            else:
                sets.append("%s=?" % k)
                args.append(v)
        if sets:
            self.cx.execute("UPDATE cmdr_bodies SET %s WHERE fid=? AND sys_id64=? AND body_id=?"
                            % ",".join(sets), args + [self.fid, a, bid])

    def _cmdr_species(self, a: int, bid: int, entry: dict, sp: Optional[str]) -> None:
        """Bio done per commander: the species this commander analysed."""
        if not self.fid or not sp:
            return
        cur = self.cx.execute("SELECT bio_species FROM cmdr_bodies WHERE fid=? AND "
                              "sys_id64=? AND body_id=?", (self.fid, a, bid)).fetchone()
        try:
            species = json.loads(cur["bio_species"]) if cur and cur["bio_species"] else []
        except ValueError:
            species = []
        if sp not in [s.get("species") for s in species]:
            species.append({"species": sp,
                            "genus": entry.get("Genus_Localised") or entry.get("Genus"),
                            "variant": entry.get("Variant_Localised") or entry.get("Variant"),
                            "ts": entry.get("timestamp")})
        self._cmdr_body(a, bid, organics=len(species), bio_species=json.dumps(species))
        self.cx.commit()

    # ------------------------------------------------- lost with the ship
    def _lost_list(self, raw: Optional[str]) -> List[str]:
        try:
            return list(json.loads(raw)) if raw else []
        except ValueError:
            return []

    def _done_again(self, a: int, bid: int, what: str) -> None:
        """A lost scan / map / species redone - its loss mark goes."""
        r = self.cx.execute("SELECT lost_what FROM cmdr_bodies WHERE fid=? AND sys_id64=? AND "
                            "body_id=?", (self.fid, a, bid)).fetchone()
        if r is None or not r["lost_what"]:
            return
        left = [w for w in self._lost_list(r["lost_what"]) if w != what]
        self.cx.execute("UPDATE cmdr_bodies SET lost_what=?, lost_ts=CASE WHEN ? THEN lost_ts END "
                        "WHERE fid=? AND sys_id64=? AND body_id=?",
                        (json.dumps(left) if left else None, 1 if left else 0, self.fid, a, bid))

    def _cmdr_carried(self, ev: str, entry: dict) -> None:
        """
        What this commander carries unsold - and what a destroyed ship takes
        with it. Scans, maps and analysed species are "open" until sold
        (Sell(Multi)ExplorationData by system, SellOrganicData by species).
        Died: every open scan / map / species is undone for this commander
        (the route plans the body again, bio counts as open again) and marked
        lost (lost_what, lost_ts) until it is redone. Knowledge about the
        body stays.
        """
        a, ts = entry.get("SystemAddress"), entry.get("timestamp")
        if ev == "Scan" and a and entry.get("BodyID") is not None \
                and entry.get("ScanType") != "NavBeaconDetail":
            bid = entry["BodyID"]
            self._cmdr_body(a, bid)
            self.cx.execute("UPDATE cmdr_bodies SET scan_open=1 WHERE fid=? AND sys_id64=? AND "
                            "body_id=? AND scan_sold=0", (self.fid, a, bid))
            self._done_again(a, bid, "scan")
        elif ev == "SAAScanComplete" and a and entry.get("BodyID") is not None:
            bid = entry["BodyID"]
            self._cmdr_body(a, bid)
            self.cx.execute("UPDATE cmdr_bodies SET map_open=1 WHERE fid=? AND sys_id64=? AND "
                            "body_id=? AND map_sold=0", (self.fid, a, bid))
            self._done_again(a, bid, "map")
        elif ev == "ScanOrganic" and entry.get("ScanType") == "Analyse" and a \
                and entry.get("Body") is not None:
            sp = entry.get("Species_Localised") or entry.get("Species")
            bid = entry["Body"]
            if not sp:
                return
            self._cmdr_body(a, bid)
            r = self.cx.execute("SELECT bio_open FROM cmdr_bodies WHERE fid=? AND sys_id64=? AND "
                                "body_id=?", (self.fid, a, bid)).fetchone()
            open_ = self._lost_list(r["bio_open"] if r else None)
            if sp not in open_:
                open_.append(sp)
            self.cx.execute("UPDATE cmdr_bodies SET bio_open=? WHERE fid=? AND sys_id64=? AND "
                            "body_id=?", (json.dumps(open_), self.fid, a, bid))
            self._done_again(a, bid, "bio:" + sp)
        elif ev in ("SellExplorationData", "MultiSellExplorationData"):
            names = [d.get("SystemName") for d in entry.get("Discovered") or []] \
                or list(entry.get("Systems") or [])
            for nm in names:
                row = self.system(nm) if nm else None
                if row is None or not row["id64"]:
                    continue
                self.cx.execute("UPDATE cmdr_bodies SET scan_sold=MAX(scan_sold,scan_open), "
                                "map_sold=MAX(map_sold,map_open), scan_open=0, map_open=0 "
                                "WHERE fid=? AND sys_id64=?", (self.fid, row["id64"]))
        elif ev == "SellOrganicData":
            for b in entry.get("BioData") or []:
                sp = b.get("Species_Localised") or b.get("Species")
                if not sp:
                    continue
                r = self.cx.execute("SELECT rowid, bio_open FROM cmdr_bodies WHERE fid=? AND "
                                    "bio_open LIKE ? ORDER BY rowid LIMIT 1",
                                    (self.fid, '%' + json.dumps(sp) + '%')).fetchone()
                if r is not None:
                    left = [x for x in self._lost_list(r["bio_open"]) if x != sp]
                    self.cx.execute("UPDATE cmdr_bodies SET bio_open=? WHERE rowid=?",
                                    (json.dumps(left) if left else None, r["rowid"]))
        elif ev == "Died":
            rows = self.cx.execute(
                "SELECT rowid, * FROM cmdr_bodies WHERE fid=? AND (scan_open=1 OR map_open=1 "
                "OR bio_open IS NOT NULL)", (self.fid,)).fetchall()
            systems = set()
            for r in rows:
                lost = self._lost_list(r["lost_what"])
                sets = {"scan_open": 0, "map_open": 0, "bio_open": None, "lost_ts": ts}
                if r["scan_open"]:
                    sets["scanned"] = 0
                    lost.append("scan")
                if r["map_open"]:
                    sets["mapped"] = 0
                    lost.append("map")
                gone = self._lost_list(r["bio_open"])
                if gone:
                    species = [x for x in self._lost_list(r["bio_species"])
                               if isinstance(x, dict) and x.get("species") not in gone]
                    sets["bio_species"] = json.dumps(species) if species else None
                    sets["organics"] = len(species)
                    lost += ["bio:" + g for g in gone]
                if not (r["scan_open"] or r["map_open"] or gone):
                    continue
                sets["lost_what"] = json.dumps(sorted(set(lost)))
                self.cx.execute("UPDATE cmdr_bodies SET %s WHERE rowid=?"
                                % ",".join("%s=?" % k for k in sets),
                                list(sets.values()) + [r["rowid"]])
                if r["scan_open"]:
                    systems.add(r["sys_id64"])
            for sa in systems:
                self.cx.execute("UPDATE cmdr_systems SET fss_complete=0, lost_ts=? WHERE fid=? "
                                "AND sys_id64=?", (ts, self.fid, sa))
            # the route ticks of that work went down with it
            self._clear_lost_ticks(ts, " AND c.fid=? AND c.lost_ts=?", (self.fid, ts))
            if rows:
                logger.info("ship lost: %d bodies with unsold data reset for %s", len(rows), self.fid)
        self.cx.commit()

    def _clear_lost_ticks(self, before: Optional[str], where: str = "", args: Sequence[Any] = ()) -> int:
        """Route ticks set before a crash belong to work that is gone - the
        stops have to be flown again. Ticks made after it stay."""
        cur = self.cx.execute(
            "UPDATE bodies SET route_done=0, route_done_ts=NULL WHERE route_done=1 "
            "AND (route_done_ts IS NULL OR ? IS NULL OR route_done_ts < ?) AND EXISTS ("
            "SELECT 1 FROM cmdr_bodies c WHERE c.sys_id64=bodies.sys_id64 "
            "AND c.body_id=bodies.body_id AND c.lost_what IS NOT NULL%s)" % where,
            (before, before) + tuple(args))
        return cur.rowcount or 0

    def repair_lost_ticks(self) -> int:
        """One-time: ticks older than the loss of their body (4.8 installs
        whose crash was marked before ticks were cleared with it)."""
        n = 0
        for r in self.cx.execute("SELECT DISTINCT fid, lost_ts FROM cmdr_bodies "
                                 "WHERE lost_what IS NOT NULL").fetchall():
            n += self._clear_lost_ticks(r["lost_ts"], " AND c.fid=? AND c.lost_ts=?",
                                        (r["fid"], r["lost_ts"]))
        self.set_meta("fix_lost_ticks", _now())
        self.cx.commit()
        return n

    def lost_of_body(self, fid: Optional[str], sys_id64: int, body_id: Optional[int]) -> List[str]:
        """What of one body this commander lost in a crash and has not redone
        ("scan", "map", "bio:<species>"); [] without a commander or loss."""
        if not fid or body_id is None:
            return []
        r = self.cx.execute("SELECT lost_what FROM cmdr_bodies WHERE fid=? AND sys_id64=? "
                            "AND body_id=?", (fid, sys_id64, body_id)).fetchone()
        return self._lost_list(r["lost_what"]) if r is not None else []

    def lost_summary(self, fid: Optional[str]) -> List[Dict[str, Any]]:
        """Systems with data lost in a crash and not redone yet, newest first."""
        if not fid:
            return []
        out: Dict[int, Dict[str, Any]] = {}
        for r in self.cx.execute("SELECT b.sys_id64, b.body_id, b.lost_ts, b.lost_what, s.name "
                                 "FROM cmdr_bodies b LEFT JOIN systems s ON s.id64=b.sys_id64 "
                                 "WHERE b.fid=? AND b.lost_what IS NOT NULL", (fid,)):
            d = out.setdefault(r["sys_id64"], {"id64": r["sys_id64"], "name": r["name"],
                                               "ts": r["lost_ts"], "scan": 0, "map": 0, "bio": []})
            for w in self._lost_list(r["lost_what"]):
                if w == "scan":
                    d["scan"] += 1
                elif w == "map":
                    d["map"] += 1
                elif w.startswith("bio:"):
                    d["bio"].append(w[4:])
        return sorted(out.values(), key=lambda d: d["ts"] or "", reverse=True)

    def is_visited(self, row: Any, fid: Optional[str] = PLAN) -> bool:
        """Has this commander (default: the main one) been in the system?"""
        if row is None:
            return False
        f = self.view_fid(fid)
        if not f or not row["id64"]:
            return bool(row["visited"])
        m = self.cmdr_system(f, row["id64"])
        return bool(m is not None and m["visited_ts"])

    def explored(self, fid: str, id64: int) -> bool:
        """Has this commander explored the system - FSS complete or any body
        scanned with his own scanner?"""
        r = self.cmdr_system(fid, id64)
        if r is not None and r["fss_complete"]:
            return True
        return self.cx.execute("SELECT 1 FROM cmdr_bodies WHERE fid=? AND sys_id64=? "
                               "AND scanned=1 LIMIT 1", (fid, id64)).fetchone() is not None

    def _cmdr_arrival(self, ev: str, entry: dict) -> None:
        """
        R3: riding along on a fleet carrier, you start at the carrier, not at
        the main star. Arriving by CarrierJump, or loading the game docked at
        a FleetCarrier, in a system THIS commander has not explored: the
        route of this visit starts at the carrier's body (Body / BodyID of the
        event). Any other arrival (FSDJump, a carrier jump into an explored
        system) starts at the main star again. Location away from a carrier
        changes nothing. Decided once, when the arrival happens - a replay of
        an older arrival keeps what was decided then.
        """
        a, ts = entry.get("SystemAddress"), entry.get("timestamp")
        if not self.fid or not a or not ts:
            return
        carrier = ev == "CarrierJump" or (
            ev == "Location" and entry.get("Docked")
            and entry.get("StationType") == "FleetCarrier")
        if ev == "Location" and not carrier:
            return
        cur = self.cmdr_system(self.fid, a)
        if cur is not None and cur["arrival_ts"] and ts <= cur["arrival_ts"]:
            return
        body, name = None, None
        if carrier and entry.get("BodyID") is not None and not self.explored(self.fid, a):
            body, name = entry["BodyID"], entry.get("Body")
        self.cx.execute("INSERT OR IGNORE INTO cmdr_systems(fid,sys_id64) VALUES (?,?)",
                        (self.fid, a))
        self.cx.execute("UPDATE cmdr_systems SET arrival_ts=?, start_body=?, start_name=? "
                        "WHERE fid=? AND sys_id64=?", (ts, body, name, self.fid, a))

    def route_start(self, fid: Optional[str], id64: Optional[int]
                    ) -> Optional[Tuple[int, Optional[str]]]:
        """R3: (body id, body name) the route of this visit starts at, or
        None for the main star."""
        if not fid or not id64:
            return None
        r = self.cmdr_system(fid, id64)
        if r is None or r["start_body"] is None:
            return None
        return int(r["start_body"]), r["start_name"]

    def cmdr_system(self, fid: str, id64: int) -> Optional[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM cmdr_systems WHERE fid=? AND sys_id64=?",
                               (fid, id64)).fetchone()

    def bodies_for(self, sys_id64: int, fid: Optional[str]) -> List[Any]:
        """The bodies of a system as one commander explored them: the shared
        knowledge (class, orbit, signals ...) with that commander's scanned /
        mapped / first discovery / species analysed. fid None = anyone."""
        rows = self.bodies_of(sys_id64)
        if not fid:
            return rows
        own = {r["body_id"]: r for r in self.cx.execute(
            "SELECT * FROM cmdr_bodies WHERE fid=? AND sys_id64=?", (fid, sys_id64))}
        out = []
        for r in rows:
            d = dict(r)
            o = own.get(r["body_id"])
            d["scanned"] = o["scanned"] if o else 0
            d["mapped"] = o["mapped"] if o else 0
            d["organics"] = o["organics"] if o else 0
            d["bio_species"] = o["bio_species"] if o else None
            for k in ("was_discovered", "was_mapped", "was_footfalled"):
                if o is not None and o[k] is not None:
                    d[k] = o[k]
            d["lost_what"] = o["lost_what"] if o is not None else None
            out.append(d)
        return out

    def visited_by(self, fid: str) -> Dict[int, sqlite3.Row]:
        """id64 -> (visited_ts, fss_complete) of one commander."""
        return {r["sys_id64"]: r for r in self.cx.execute(
            "SELECT sys_id64, visited_ts, fss_complete FROM cmdr_systems WHERE fid=?",
            (fid,))}

    def commanders(self) -> List[Dict[str, Any]]:
        """Every commander seen, with what the main-commander suggestion uses."""
        rows = self.cx.execute(
            "SELECT c.fid, c.name, c.carrier, c.last_seen, "
            "(SELECT COUNT(*) FROM cmdr_logins l WHERE l.fid=c.fid) logins, "
            "(SELECT COUNT(*) FROM cmdr_systems s WHERE s.fid=c.fid "
            " AND s.visited_ts IS NOT NULL) systems "
            "FROM commanders c").fetchall()
        return [dict(r) for r in rows]

    def suggest_main(self) -> Optional[str]:
        """C1: the commander with an own carrier, else the one with the most
        sessions (journals), else the most systems."""
        best = sorted(self.commanders(),
                      key=lambda c: (c["carrier"], c["logins"], c["systems"],
                                     c["last_seen"] or ""), reverse=True)
        return best[0]["fid"] if best else None

    def set_main_commander(self, fid: Optional[str]) -> Optional[str]:
        """Use this FID ('' / None = the suggestion) for the survey plan and
        statistics; stored in meta for the FIS. Returns the FID in use."""
        use = str(fid) if fid else self.suggest_main()
        self.plan_fid = use
        if (self.get_meta("main_fid") or None) != use:
            self.set_meta("main_fid", use or "")
        return use

    def commander_name(self, fid: Optional[str]) -> Optional[str]:
        if not fid:
            return None
        r = self.cx.execute("SELECT name FROM commanders WHERE fid=?", (fid,)).fetchone()
        return r["name"] if r is not None else None

    def explorers(self, id64: Optional[int], but: Optional[str] = None) -> List[str]:
        """Names of the commanders who have been in this system (C1 'also
        explored by'), leaving out `but`."""
        if not id64:
            return []
        rows = self.cx.execute(
            "SELECT s.fid, c.name FROM cmdr_systems s LEFT JOIN commanders c ON c.fid=s.fid "
            "WHERE s.sys_id64=? AND s.visited_ts IS NOT NULL ORDER BY s.visited_ts",
            (id64,)).fetchall()
        return [r["name"] or r["fid"] for r in rows if r["fid"] != but]

    # -------------------------------------------------------------- ingestion
    def _track_location(self, ev: str, entry: dict) -> None:
        """Keep track of the body we are at, for MaterialCollected."""
        if ev in ("FSDJump", "CarrierJump", "Location", "StartUp"):
            self._here_sys = entry.get("SystemAddress") or self._here_sys
            self._here_body = entry.get("Body") if entry.get("BodyType") in (
                "Planet", "Star") else None
        elif ev in ("Touchdown", "ApproachBody", "SupercruiseExit", "Disembark",
                    "ApproachSettlement", "Liftoff"):
            body = entry.get("Body") or entry.get("BodyName")
            if body:
                self._here_sys = entry.get("SystemAddress") or self._here_sys
                self._here_body = body
        elif ev in ("LeaveBody", "SupercruiseEntry"):
            self._here_body = None

    # ------------------------------------------------------- surface (4.4)
    POS_MAX_AGE = 120.0      # s: a Status.json fix older than this is stale

    def note_status(self, st: dict, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Remember the latest position on a body from Status.json. Returns the
        fix (with mode) or None when not on/near a body.
        """
        lat, lon, body = st.get("Latitude"), st.get("Longitude"), st.get("BodyName")
        if lat is None or lon is None or not body:
            self._pos = None
            return None
        flags = int(st.get("Flags") or 0)
        flags2 = int(st.get("Flags2") or 0)
        mode = "foot" if flags2 & 1 else ("srv" if flags & (1 << 26) else "ship")
        self._pos = {"body": body, "lat": float(lat), "lon": float(lon),
                     "alt": st.get("Altitude"), "heading": st.get("Heading"),
                     "radius": st.get("PlanetRadius"), "mode": mode,
                     "landed": bool(flags & 2), "t": now if now is not None else time.time(),
                     "gt": _epoch(st.get("timestamp"))}     # game time of the fix
        return self._pos

    def _fresh_pos(self, body: Optional[str], at: Optional[float] = None
                   ) -> Optional[Dict[str, Any]]:
        """
        The last Status.json fix, if it belongs to this body and to the time
        of the event. `at` is the event's game time: replaying an old journal
        while standing on the same body must not stamp today's position on
        a sample taken months ago.
        """
        p = self._pos
        if not p or (body and p["body"] != body):
            return None
        if at is not None:
            return p if p.get("gt") is not None and abs(at - p["gt"]) <= self.POS_MAX_AGE else None
        if time.time() - p["t"] > self.POS_MAX_AGE:
            return None
        return p

    def add_track_point(self, sys_id64: int, pos: Dict[str, Any], ts: float) -> None:
        self.cx.execute(
            "INSERT OR IGNORE INTO surface_track(sys_id64,body_name,ts,lat,lon,alt,"
            "heading,mode) VALUES (?,?,?,?,?,?,?,?)",
            (sys_id64, pos["body"], ts, pos["lat"], pos["lon"], pos.get("alt"),
             pos.get("heading"), pos.get("mode")))
        self.cx.commit()

    def _mark(self, entry: dict, kind: str, body: Optional[str], label: str = "",
              detail: Optional[str] = None, lat=None, lon=None) -> bool:
        a = entry.get("SystemAddress") or self._here_sys
        body = body or self._here_body or (self._pos or {}).get("body")
        if not a or not body:
            return False
        if lat is None or lon is None:
            p = self._fresh_pos(body, _epoch(entry.get("timestamp")))
            if p:
                lat, lon = p["lat"], p["lon"]
        self.cx.execute(
            "INSERT OR IGNORE INTO surface_marks(ts,sys_id64,body_name,kind,label,"
            "detail,lat,lon) VALUES (?,?,?,?,?,?,?,?)",
            (entry.get("timestamp") or _now(), a, body, kind, label or "", detail,
             lat, lon))
        self.cx.commit()
        self.marks_rev += 1
        return True

    def _body_name_of(self, sys_id64: Optional[int], body_id: Optional[int]) -> Optional[str]:
        if sys_id64 is None or body_id is None:
            return None
        r = self.cx.execute("SELECT name FROM bodies WHERE sys_id64=? AND body_id=?",
                            (sys_id64, body_id)).fetchone()
        return r[0] if r else None

    def _surface_event(self, ev: str, e: dict) -> None:
        """Turn surface journal events into marks."""
        if ev in ("Touchdown", "Liftoff"):
            # who landed: the flying Nomad writes Touchdown/Liftoff too, and a
            # ship sent away or called back does it without the player
            if e.get("PlayerControlled") is False:
                who = "auto"
            else:
                p = self._fresh_pos(e.get("Body"), _epoch(e.get("timestamp")))
                who = ("srv" if p["mode"] == "srv" else "ship") if p else None
            self._mark(e, ev.lower(), e.get("Body"), e.get("Body") or "", detail=who,
                       lat=e.get("Latitude"), lon=e.get("Longitude"))
        elif ev in ("LaunchSRV", "LaunchVessel"):
            # LaunchVessel: the Nomad (flying SRV), dropped from a ship in flight
            self._vehicle = (e.get("SRVType_Localised") or e.get("VesselType_Localised")
                             or "SRV")
            self._mark(e, "srv_out", None, self._vehicle)
        elif ev in ("DockSRV", "DockVessel"):
            self._mark(e, "srv_in", None, e.get("SRVType_Localised") or
                       e.get("VesselType_Localised") or "SRV")
        elif ev == "Disembark" and e.get("OnPlanet"):
            if e.get("SRV"):
                # the vehicle stays here - the point to walk back to
                self._mark(e, "srv_parked", e.get("Body"), "SRV",
                           detail=self._vehicle or "SRV")
            else:
                self._mark(e, "disembark", e.get("Body"), "on foot")
        elif ev == "Embark" and e.get("OnPlanet"):
            self._mark(e, "embark", e.get("Body"), "SRV" if e.get("SRV") else "ship")
        elif ev == "ScanOrganic":
            kind = {"Log": "bio_log", "Sample": "bio_sample",
                    "Analyse": "bio_analyse"}.get(e.get("ScanType") or "")
            if kind:
                body = self._body_name_of(e.get("SystemAddress"), e.get("Body"))
                self._mark(e, kind, body,
                           e.get("Species_Localised") or e.get("Species") or "",
                           detail=e.get("Genus_Localised") or e.get("Genus"))
        elif ev == "MaterialCollected":
            if self._here_body and self._fresh_pos(self._here_body,
                                                   _epoch(e.get("timestamp"))):
                self._mark(e, "material", self._here_body,
                           e.get("Name_Localised") or (e.get("Name") or "").capitalize(),
                           detail=e.get("Category"))
        elif ev == "MiningRefined":
            self._rig_refined(e)
        elif ev == "CodexEntry" and e.get("Latitude") is not None:
            body = (e.get("BodyName") or
                    self._body_name_of(e.get("SystemAddress"), e.get("BodyID")))
            self._mark(e, "codex", body, e.get("Name_Localised") or "",
                       detail=e.get("SubCategory_Localised"),
                       lat=e.get("Latitude"), lon=e.get("Longitude"))
        elif ev == "ApproachSettlement" and e.get("Latitude") is not None:
            self._mark(e, "settlement", e.get("BodyName"), e.get("Name_Localised") or
                       e.get("Name") or "", lat=e.get("Latitude"), lon=e.get("Longitude"))
        elif ev == "Screenshot" and e.get("Latitude") is not None:
            self._mark(e, "screenshot", e.get("Body"), e.get("Filename") or "",
                       lat=e.get("Latitude"), lon=e.get("Longitude"))

    def _rig_refined(self, e: dict) -> None:
        """
        Surface mining: the Rhino collects a finished rig by driving over it,
        and every tonne refined writes one MiningRefined - so where they are
        written is where the rig stood. Placing a rig writes nothing at all.
        Only in the SRV (the ship's refinery writes the same event when
        mining asteroids). The position is the live Status.json fix or, when
        replaying a journal, the stored surface track within 15 s.
        """
        stamp = e.get("timestamp")
        t = _epoch(stamp)
        p = self._fresh_pos(self._here_body, t) if self._here_body else None
        if p and p.get("mode") == "srv":
            sys_id, body, lat, lon = self._here_sys, p["body"], p["lat"], p["lon"]
        elif t is not None:
            r = self.cx.execute(
                "SELECT sys_id64, body_name, lat, lon FROM surface_track WHERE mode='srv'"
                " AND ts BETWEEN ? AND ? ORDER BY ABS(ts - ?) LIMIT 1",
                (t - 15, t + 15, t)).fetchone()
            if not r:
                return
            sys_id, body, lat, lon = r
        else:
            return
        name = (e.get("Type_Localised") or
                (e.get("Type") or "").strip("$;").replace("_name", "").capitalize() or "?")
        # one tonne per event, sometimes two in the same second: the key
        # holds the timestamp, so number the second one on
        self._refine_seq = self._refine_seq + 1 if stamp == self._refine_ts else 0
        self._refine_ts = stamp
        label = name if not self._refine_seq else "%s#%d" % (name, self._refine_seq)
        self._mark({"timestamp": stamp, "SystemAddress": sys_id}, "refined", body, label,
                   detail="rig", lat=lat, lon=lon)

    def surface_bodies(self) -> List[sqlite3.Row]:
        """Bodies with marks or a track, most recent first."""
        return self.cx.execute(
            "SELECT sys_id64, body_name, MAX(ts) last, COUNT(*) n FROM ("
            " SELECT sys_id64, body_name, ts FROM surface_marks"
            " UNION ALL SELECT sys_id64, body_name, datetime(ts,'unixepoch') FROM surface_track)"
            " GROUP BY sys_id64, body_name ORDER BY last DESC").fetchall()

    def marks_of(self, sys_id64: int, body_name: str) -> List[sqlite3.Row]:
        return self.cx.execute(
            "SELECT * FROM surface_marks WHERE sys_id64=? AND body_name=? ORDER BY ts",
            (sys_id64, body_name)).fetchall()

    def track_of(self, sys_id64: int, body_name: str) -> List[sqlite3.Row]:
        return self.cx.execute(
            "SELECT * FROM surface_track WHERE sys_id64=? AND body_name=? ORDER BY ts",
            (sys_id64, body_name)).fetchall()

    def ingest_journal_event(self, entry: dict) -> int:
        """Process one journal event. Returns the number of records touched."""
        ev = entry.get("event")
        n = 0
        self._track_location(ev, entry)
        self._note_dock(ev, entry)
        try:
            self._cmdr_event(ev, entry)
        except Exception:
            logger.debug("commander event failed for %s", ev, exc_info=True)
        try:
            self._surface_event(ev, entry)
        except Exception:
            logger.debug("surface mark failed for %s", ev, exc_info=True)
        try:
            if inhabited_event(entry):
                n += self.mark_inhabited(entry.get("StarSystem"), entry.get("SystemAddress"))
            if ev in ("FSDJump", "Location", "CarrierJump"):
                pos = star_pos(entry.get("StarPos"))
                if entry.get("StarSystem") and pos:
                    self.upsert(entry["StarSystem"], pos[0], pos[1], pos[2],
                                id64=entry.get("SystemAddress"), quality=Q_JOURNAL,
                                source="journal", visited=True)
                    self._cmdr_arrival(ev, entry)
                    self._cmdr_system(entry.get("SystemAddress"), entry.get("timestamp"))
                    n += 1
                # CarrierJump is caught here, so the carrier branch below only
                # ever saw CarrierLocation: riding along on the own carrier
                # left it in the old system until the next login.
                if ev == "CarrierJump" and self._own_carrier_event(ev, entry):
                    self.set_carrier(entry.get("StarSystem"), entry.get("SystemAddress"),
                                     tuple(pos[:3]) if pos and len(pos) >= 3 else None)

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
                    pos = star_pos(hop.get("StarPos"))
                    if hop.get("StarSystem") and pos:
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
                self._cmdr_system(a, fss=True)
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

                    def _js(v):
                        return json.dumps(v, separators=(",", ":")) if v else None

                    def _pct(lst, key="Name"):
                        if not lst:
                            return None
                        if isinstance(lst, dict):
                            return lst
                        return {d.get(key): d.get("Percent") for d in lst
                                if isinstance(d, dict) and d.get(key)}

                    ring_list = [{"name": r.get("Name"),
                                  "cls": (r.get("RingClass") or "").replace("eRingClass_", ""),
                                  "mass": r.get("MassMT"),
                                  "inner": r.get("InnerRad"), "outer": r.get("OuterRad")}
                                 for r in rings]
                    phys = dict(
                        radius=entry.get("Radius"),
                        mass_em=entry.get("MassEM"),
                        gravity=entry.get("SurfaceGravity"),
                        temp_k=entry.get("SurfaceTemperature"),
                        pressure=entry.get("SurfacePressure"),
                        atmosphere=entry.get("Atmosphere") or None,
                        atmo_type=entry.get("AtmosphereType") or None,
                        atmo_comp=_js(_pct(entry.get("AtmosphereComposition"))),
                        volcanism=entry.get("Volcanism") or None,
                        composition=_js(entry.get("Composition")),
                        materials=_js(_pct(entry.get("Materials"))),
                        tidal_lock=(1 if entry.get("TidalLock") else 0)
                        if "TidalLock" in entry else None,
                        axial_tilt=entry.get("AxialTilt"),
                        rotation=entry.get("RotationPeriod"),
                        was_footfalled=(1 if entry.get("WasFootfalled") else 0)
                        if "WasFootfalled" in entry else None,
                        rings_json=_js(ring_list),
                        reserve=entry.get("ReserveLevel"),
                        stellar_mass=entry.get("StellarMass"),
                        abs_mag=entry.get("AbsoluteMagnitude"),
                        age_my=entry.get("Age_MY"),
                        luminosity=entry.get("Luminosity"),
                        subclass=entry.get("Subclass"),
                    )
                    self._body_upsert(
                        a, entry.get("BodyID"), **phys)
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
                        # a nav beacon hands over every body's data: the data
                        # counts, but it is not your scan (no discovery, no
                        # exploration data) - an own scan stays an own scan
                        scanned=None if entry.get("ScanType") == "NavBeaconDetail" else 1)
                    self._link_parents(a, entry.get("Parents"))
                    if entry.get("ScanType") != "NavBeaconDetail" and ev == "Scan":
                        self._cmdr_body(
                            a, entry.get("BodyID"), scanned=1,
                            was_discovered=(1 if entry.get("WasDiscovered") else 0)
                            if "WasDiscovered" in entry else None,
                            was_mapped=(1 if entry.get("WasMapped") else 0)
                            if "WasMapped" in entry else None,
                            was_footfalled=(1 if entry.get("WasFootfalled") else 0)
                            if "WasFootfalled" in entry else None)
                        self.cx.commit()
                    n += 1

            elif ev == "SAAScanComplete":
                a = entry.get("SystemAddress")
                if a:
                    self._body_upsert(a, entry.get("BodyID"),
                                      name=entry.get("BodyName"), mapped=1)
                    self._cmdr_body(a, entry.get("BodyID"), mapped=1)
                    self.cx.commit()
                    n += 1

            elif ev in ("SAASignalsFound", "FSSBodySignals"):
                a = entry.get("SystemAddress")
                if a:
                    self._store_hotspots(a, entry)
                    self._store_signals(a, entry)
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
                        "SELECT organics, bio_species FROM bodies "
                        "WHERE sys_id64=? AND body_id=?", (a, bid)).fetchone()
                    species = []
                    try:
                        species = json.loads(cur["bio_species"]) if cur and \
                            cur["bio_species"] else []
                    except ValueError:
                        species = []
                    sp = (entry.get("Species_Localised") or entry.get("Species"))
                    if sp:
                        if sp not in [s.get("species") for s in species]:
                            species.append({
                                "species": sp,
                                "genus": entry.get("Genus_Localised") or entry.get("Genus"),
                                "variant": entry.get("Variant_Localised")
                                or entry.get("Variant"),
                                "ts": entry.get("timestamp")})
                        # one per distinct species - replaying the same journal
                        # (first import, route bootstrap) must not count twice
                        organics = len(species)
                    else:
                        organics = (cur["organics"] if cur else 0) + 1
                    self._body_upsert(a, bid, organics=organics,
                                      bio_species=json.dumps(species) if species
                                      else None)
                    self._cmdr_species(a, bid, entry, sp)
                    n += 1

            elif ev == "CarrierLocation" and self._own_carrier_event(ev, entry):
                nm = entry.get("StarSystem")
                pos = star_pos(entry.get("StarPos"))
                a = entry.get("SystemAddress")
                if nm:
                    if pos:
                        self.upsert(nm, pos[0], pos[1], pos[2], id64=a,
                                    quality=Q_JOURNAL, source="carrier",
                                    visited=(ev == "CarrierJump"))
                    else:
                        self.upsert(nm, id64=a, quality=Q_CONFIRMED, source="carrier")
                    self.set_carrier(nm, a, pos)
                    n += 1

            elif ev == "CarrierStats" and entry.get("CarrierType", "FleetCarrier") == "FleetCarrier":
                if entry.get("CarrierID"):
                    self.set_meta("carrier_market_id", entry["CarrierID"])
                self.set_meta("carrier_callsign", entry.get("Callsign") or "")
                self.set_meta("carrier_name", entry.get("Name") or "")

            elif (ev == "Docked" and entry.get("StationType") == "FleetCarrier"
                  and self._own_carrier_event(ev, entry)):
                nm = entry.get("StarSystem")
                if nm:
                    self.set_carrier(nm, entry.get("SystemAddress"),
                                     callsign=entry.get("StationName"))
                    n += 1

            elif ev in ("SellExplorationData", "MultiSellExplorationData"):
                disc = entry.get("Discovered") or []
                base = int(entry.get("BaseValue") or 0)
                bonus = int(entry.get("Bonus") or 0)
                total = int(entry.get("TotalEarnings") or (base + bonus))
                bodies = sum(int(d.get("NumBodies") or 0) for d in disc)
                self.cx.execute(
                    "INSERT OR REPLACE INTO earnings(ts,kind,base,bonus,total,"
                    "systems,bodies,detail) VALUES (?,?,?,?,?,?,?,?)",
                    (entry.get("timestamp"), "exploration", base, bonus, total,
                     len(disc) or len(entry.get("Systems") or []), bodies, None))
                self.cx.commit()
                n += 1

            elif ev == "SellOrganicData":
                bio = entry.get("BioData") or []
                base = sum(int(b.get("Value") or 0) for b in bio)
                bonus = sum(int(b.get("Bonus") or 0) for b in bio)
                top = max(bio, key=lambda b: int(b.get("Value") or 0)) if bio else {}
                self.cx.execute(
                    "INSERT OR REPLACE INTO earnings(ts,kind,base,bonus,total,"
                    "systems,bodies,detail) VALUES (?,?,?,?,?,?,?,?)",
                    (entry.get("timestamp"), "organic", base, bonus, base + bonus,
                     0, len(bio),
                     top.get("Species_Localised") or top.get("Species")))
                self.cx.commit()
                n += 1

            elif ev == "CodexEntry":
                self.upsert(entry.get("System"), id64=entry.get("SystemAddress"),
                            quality=Q_CONFIRMED, source="codex")
                self._store_codex(entry)
                n += 1

            elif ev == "FSSSignalDiscovered":
                if self._store_fss_signal(entry):
                    n += 1

            elif ev == "MaterialCollected":
                if self._store_material(entry):
                    n += 1
            if self.fid and ev in LOSS_EVENTS:
                self._cmdr_carried(ev, entry)
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
        # Already known under its real name: nothing new. Catalogue systems
        # (HIP, HD ...) sit in a boxel slot too, so rebuilding a procgen
        # name from their id64 invented a second, unfindable "system" - up
        # to 4.2 that phantom then showed up as a flight target.
        if self.system_by_id64(a) is not None:
            return None
        nm = None
        given = dest.get("Name") or ""
        if not dest.get("Body") and given and not given.startswith("$"):
            nm = given                       # the game's own name for it
        if not nm:
            nm = self.name_from_id64(a)
        if not nm:
            return None
        existed = self.system(nm) is not None
        self.upsert(nm, id64=a, quality=Q_CONFIRMED, source="destination")
        return None if existed else nm

    def repair_marks45(self) -> Dict[str, int]:
        """
        4.5 one-time fix of recorded surface marks:
          * leaving the SRV was stored as a plain 'disembark' - the next
            'embark' says whether it was the SRV; those become 'srv_parked'
            (the vehicle you have to walk back to)
          * Touchdown/Liftoff carry no vehicle; the Nomad lands and lifts off
            on its own. The track's mode at that moment tells ship from SRV.
        """
        parked = vehicle = 0
        rows = self.cx.execute(
            "SELECT rowid, ts, sys_id64, body_name, kind, label FROM surface_marks "
            "WHERE kind IN ('disembark','embark','srv_out') ORDER BY body_name, ts").fetchall()
        last_srv: Dict[str, str] = {}
        for i, r in enumerate(rows):
            if r["kind"] == "srv_out":
                last_srv[r["body_name"]] = r["label"] or "SRV"
                continue
            if r["kind"] != "disembark":
                continue
            nxt = next((n for n in rows[i + 1:] if n["body_name"] == r["body_name"]
                        and n["kind"] in ("embark", "disembark")), None)
            if nxt is not None and nxt["kind"] == "embark" and nxt["label"] == "SRV":
                self.cx.execute("UPDATE OR IGNORE surface_marks SET kind='srv_parked', "
                                "label='SRV', detail=? WHERE rowid=?",
                                (last_srv.get(r["body_name"], "SRV"), r["rowid"]))
                parked += 1
        for r in self.cx.execute(
                "SELECT rowid, ts, sys_id64, body_name FROM surface_marks "
                "WHERE kind IN ('touchdown','liftoff') AND detail IS NULL").fetchall():
            t = _epoch(r["ts"])
            if t is None:
                continue
            tr = self.cx.execute(
                "SELECT mode FROM surface_track WHERE sys_id64=? AND body_name=? "
                "AND ts BETWEEN ? AND ? ORDER BY abs(ts-?) LIMIT 1",
                (r["sys_id64"], r["body_name"], t - 30, t + 30, t)).fetchone()
            if tr is not None and tr["mode"]:
                self.cx.execute("UPDATE surface_marks SET detail=? WHERE rowid=?",
                                ("srv" if tr["mode"] == "srv" else "ship", r["rowid"]))
                vehicle += 1
        self.set_meta("fix_marks45", _now())
        self.cx.commit()
        return {"srv_parked": parked, "vehicle_set": vehicle}

    def repair_phantoms(self) -> int:
        """
        Drop systems that were only ever seen as a rebuilt destination name
        while the same id64 is known under a better name (4.3 one-time fix).
        The boxel knowledge stays: the slot really is occupied.
        """
        rows = self.cx.execute(
            "SELECT p.name FROM systems p JOIN systems r ON r.id64 = p.id64 "
            "AND r.name <> p.name AND r.quality > p.quality "
            "WHERE p.sources = 'destination'").fetchall()
        for (nm,) in rows:
            self.cx.execute("DELETE FROM systems WHERE name=?", (nm,))
        self.set_meta("fix_phantoms", _now())
        self.cx.commit()
        return len(rows)

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
    def _own_carrier_event(self, ev: str, entry: dict) -> bool:
        """
        Is this carrier event about the commander's OWN fleet carrier?

        Up to 4.7 every Docked at a fleet carrier and every CarrierJump moved
        "my carrier": docking at someone else's carrier (or riding along on
        it) overwrote the own carrier's position and callsign - and a
        commander without a carrier got a stranger's carrier as his own.
        The own carrier is known by its CarrierID (= MarketID) from
        CarrierLocation / CarrierStats, which the game writes for owners at
        every login. Without that ID nothing but CarrierLocation counts.
        """
        if ev == "CarrierLocation":
            if entry.get("CarrierType", "FleetCarrier") != "FleetCarrier":
                return False             # squadron carrier, not the own one
            if entry.get("CarrierID"):
                self.set_meta("carrier_market_id", entry["CarrierID"])
            return True
        own = self.get_meta("carrier_market_id")
        mid = entry.get("MarketID")
        if ev == "CarrierJump" and not mid:
            mid = self._dock_market_id     # on foot aboard: no MarketID
        if own and mid:
            return str(mid) == str(own)
        if not own and ev == "Docked":
            cs = self.get_meta("carrier_callsign")
            return bool(cs) and entry.get("StationName") == cs
        return False

    def _note_dock(self, ev: str, entry: dict) -> None:
        """Remember where the commander is docked (for CarrierJump on foot)."""
        if ev == "Docked" or (ev == "Location" and entry.get("Docked")):
            self._dock_market_id = entry.get("MarketID")
        elif ev in ("Undocked", "FSDJump", "Died", "LoadGame", "Shutdown"):
            self._dock_market_id = None

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

    # ------------------------------------------------------------ route ticks
    def set_route_done(self, sys_id64: int, body_id: int, done: bool) -> None:
        """
        Remember that a body has been worked, so ticks survive a restart.

        Kept per body rather than as a session list: you often leave a system
        half finished, fly elsewhere and come back days later, and the ticks
        have to still be there when you do.
        """
        self.cx.execute(
            "UPDATE bodies SET route_done=?, route_done_ts=? "
            "WHERE sys_id64=? AND body_id=?",
            (1 if done else 0, _now() if done else None, sys_id64, body_id))
        self.cx.commit()

    def route_done_of(self, sys_id64: int) -> Set[int]:
        return {r[0] for r in self.cx.execute(
            "SELECT body_id FROM bodies WHERE sys_id64=? AND route_done=1",
            (sys_id64,))}

    def clear_route_done(self, sys_id64: int) -> int:
        cur = self.cx.execute(
            "UPDATE bodies SET route_done=0, route_done_ts=NULL "
            "WHERE sys_id64=? AND route_done=1", (sys_id64,))
        self.cx.commit()
        return cur.rowcount or 0

    def systems_part_done(self) -> List[sqlite3.Row]:
        """Systems left part-worked - useful when deciding where to go back to."""
        return self.cx.execute(
            "SELECT s.name, s.id64, COUNT(*) done FROM bodies b "
            "JOIN systems s ON s.id64 = b.sys_id64 "
            "WHERE b.route_done=1 GROUP BY b.sys_id64 ORDER BY done DESC"
        ).fetchall()

    # --------------------------------------------------------------- mining
    # Signal types that are neither biological nor geological are mining
    # materials: a ring scan reports "Platinum x3", "Low Temp. Diamonds x5"
    # and so on. Worth keeping - finding a good ring again months later is
    # otherwise a matter of remembering where you were.
    def _store_hotspots(self, sys_id64: int, entry: dict) -> None:
        body_id = entry.get("BodyID")
        name = entry.get("BodyName") or ""
        if body_id is None or "Ring" not in name:
            return
        ring_class = None
        row = self.cx.execute(
            "SELECT ring_classes FROM bodies WHERE sys_id64=? AND body_id=?",
            (sys_id64, body_id)).fetchone()
        if row:
            ring_class = row["ring_classes"]
        for sig in entry.get("Signals") or []:
            t = sig.get("Type") or ""
            if not t or "Biological" in t or "Geological" in t:
                continue
            self.cx.execute(
                "INSERT OR REPLACE INTO hotspots(sys_id64,body_id,body_name,"
                "material,label,count,ring_class,found) VALUES (?,?,?,?,?,?,?,?)",
                (sys_id64, body_id, name, t, sig.get("Type_Localised") or t,
                 int(sig.get("Count") or 0), ring_class, _now()))
        self.cx.commit()

    # ------------------------------------------------------------ signal atlas
    @staticmethod
    def signal_kind(sig_type: str) -> Tuple[str, str]:
        """Journal signal type -> (kind, readable label)."""
        t = sig_type or ""
        if "PlanetaryMiningLocation" in t:
            return "mining_location", "Planetary mining location"
        if t.startswith("$SAA_SignalType_"):
            k = t[len("$SAA_SignalType_"):].rstrip(";")
            return k.lower(), k
        return t.strip("$;").lower(), t.strip("$;")

    def _sig_put(self, sys_id64: int, body_id: int, body_name: Optional[str],
                 kind: str, label: str, count: int) -> None:
        self.cx.execute(
            "INSERT OR REPLACE INTO signals(sys_id64,body_id,body_name,kind,label,"
            "count,found) VALUES (?,?,?,?,?,?,?)",
            (sys_id64, body_id, body_name, kind, label, max(1, int(count or 1)),
             _now()))

    def _store_signals(self, sys_id64: int, entry: dict) -> None:
        """Body signals and DSS genera - everything except ring hotspots."""
        body_id = entry.get("BodyID")
        name = entry.get("BodyName") or ""
        if body_id is None or "Ring" in name:
            return
        for sig in entry.get("Signals") or []:
            t = sig.get("Type") or ""
            if not t:
                continue
            kind, label = self.signal_kind(t)
            self._sig_put(sys_id64, body_id, name, kind,
                          sig.get("Type_Localised") or label, sig.get("Count") or 1)
        for g in entry.get("Genuses") or []:
            genus = g.get("Genus_Localised") or g.get("Genus") or ""
            if genus:
                self._sig_put(sys_id64, body_id, name, "genus:" + genus, genus, 1)
        self.cx.commit()

    def _store_codex(self, entry: dict) -> None:
        """Geology/anomaly sites and Brain Trees from the codex."""
        a = entry.get("SystemAddress")
        label = entry.get("Name_Localised") or ""
        sub = entry.get("SubCategory_Localised") or ""
        if not a or not label:
            return
        if "Organic" in sub and "Brain Tree" not in label:
            return              # ordinary species are covered by ScanOrganic
        cat = entry.get("Category_Localised") or ""
        if ("Astronomical" in cat or "Stellar" in cat) and not any(
                w in label for w in ("Cloud", "Nebula", "Lagrange", "Anomal")):
            return              # planet and star classes, not sites
        body_id = entry.get("BodyID")
        self._sig_put(a, body_id if body_id is not None else -1,
                      entry.get("BodyName"), "codex:" + label, label, 1)
        self.cx.commit()

    def _store_fss_signal(self, entry: dict) -> bool:
        """Non-human signal sources and other rare system signals."""
        a = entry.get("SystemAddress")
        uss = entry.get("USSType") or ""
        st = entry.get("SignalType") or ""
        name = entry.get("SignalName_Localised") or entry.get("SignalName") or ""
        if not a:
            return False
        if "NonHuman" in uss:
            label = entry.get("USSType_Localised") or "Non-Human signal source"
            self._sig_put(a, -1, None, "uss:nonhuman", label, 1)
        elif st in ("Titan", "Codex"):
            # not by name: fleet carriers are called "Guardian of ..." too;
            # Guardian and Thargoid sites report as body signals instead
            self._sig_put(a, -1, None, "site:" + (name or st), name or st, 1)
        else:
            return False
        self.cx.commit()
        return True

    # Surface sites the journal never reports: they are found with the SRV
    # wave scanner and leave no event. The pickup is the only trace, so the
    # body is marked from what was collected there. Internal names: Thargoid
    # material is "unknown..." / "tg_..." (Sensor Fragment = unknownenergysource),
    # Guardian material "guardian_..." / "ancient...".
    @staticmethod
    def site_from_material(mat: str) -> Optional[Tuple[str, str]]:
        m = (mat or "").lower()
        if m.startswith(("unknown", "tg_")):
            return "site:nonhuman", "Non-human site (from pickup)"
        if m.startswith(("guardian_", "ancient")):
            return "site:guardian", "Guardian site (from pickup)"
        return None

    def _store_material(self, entry: dict) -> bool:
        a = self._here_sys or entry.get("SystemAddress")
        mat = entry.get("Name")
        if not a or not mat:
            return False
        site = self.site_from_material(mat)
        if site and self._here_body:
            r = self.cx.execute("SELECT body_id FROM bodies WHERE sys_id64=? AND "
                                "name=?", (a, self._here_body)).fetchone()
            self._sig_put(a, r[0] if r else -1, self._here_body, site[0], site[1], 1)
        self.cx.execute(
            "INSERT OR IGNORE INTO material_finds(ts,sys_id64,body_name,material,"
            "label,category,count) VALUES (?,?,?,?,?,?,?)",
            (entry.get("timestamp") or _now(), a, self._here_body, mat,
             entry.get("Name_Localised") or mat.capitalize(),
             entry.get("Category"), int(entry.get("Count") or 1)))
        self.cx.commit()
        return True

    def signal_kinds(self) -> List[Dict[str, object]]:
        """Every signal kind seen, with how many bodies carry it."""
        out = []
        for r in self.cx.execute(
                "SELECT kind, MAX(label) label, COUNT(*) bodies, SUM(count) total "
                "FROM signals GROUP BY kind ORDER BY total DESC"):
            out.append({"kind": r["kind"], "label": r["label"],
                        "bodies": r["bodies"], "total": r["total"]})
        return out

    def material_kinds(self) -> List[Dict[str, object]]:
        out = []
        for r in self.cx.execute(
                "SELECT material, MAX(label) label, MAX(category) category, "
                "COUNT(DISTINCT sys_id64 || '/' || IFNULL(body_name,'')) places, "
                "SUM(count) total FROM material_finds GROUP BY material "
                "ORDER BY category, label"):
            out.append({"material": r["material"], "label": r["label"],
                        "category": r["category"], "places": r["places"],
                        "total": r["total"]})
        return out

    def _with_dist(self, rows, near) -> List[Dict[str, object]]:
        out = []
        for r in rows:
            d = None
            if near is not None and r["x"] is not None:
                d = math.dist((r["x"], r["y"], r["z"]), tuple(near))
            out.append(dict(r, dist=d))
        out.sort(key=lambda h: (h["dist"] if h["dist"] is not None else 1e9,
                                -(h.get("count") or 0)))
        return out

    def find_signals(self, kind: Optional[str] = None,
                     near: Optional[Sequence[float]] = None,
                     limit: int = 40) -> List[Dict[str, object]]:
        """Bodies (or systems) carrying a signal kind, nearest first."""
        sql = ("SELECT g.kind, g.label, g.count, g.body_name, g.body_id, "
               "s.name sys_name, g.sys_id64, s.x, s.y, s.z FROM signals g "
               "LEFT JOIN (SELECT id64, name, x, y, z, MAX(quality) q FROM systems GROUP BY id64) s ON s.id64 = g.sys_id64")
        args: List[object] = []
        if kind:
            sql += " WHERE g.kind = ?"
            args.append(kind)
        rows = self._with_dist(self.cx.execute(sql, args).fetchall(), near)
        for r in rows:
            r["system"] = r["sys_name"] or str(r["sys_id64"])
        return rows[:limit]

    def find_materials(self, material: Optional[str] = None,
                       near: Optional[Sequence[float]] = None,
                       limit: int = 40) -> List[Dict[str, object]]:
        """Places where a material was picked up, nearest first."""
        sql = ("SELECT m.material, MAX(m.label) label, MAX(m.category) category, "
               "m.body_name, m.sys_id64, s.name sys_name, s.x, s.y, s.z, "
               "SUM(m.count) count, MAX(m.ts) last FROM material_finds m "
               "LEFT JOIN (SELECT id64, name, x, y, z, MAX(quality) q FROM systems GROUP BY id64) s ON s.id64 = m.sys_id64")
        args: List[object] = []
        if material:
            sql += " WHERE m.material = ?"
            args.append(material)
        sql += " GROUP BY m.material, m.sys_id64, m.body_name"
        rows = self._with_dist(self.cx.execute(sql, args).fetchall(), near)
        for r in rows:
            r["system"] = r["sys_name"] or str(r["sys_id64"])
        return rows[:limit]

    # finds on the ground worth coming back to (surface marks with a position)
    FIND_KINDS = (("codex", "codex finds"), ("bio_analyse", "biology analysed"),
                  ("settlement", "settlements"), ("screenshot", "screenshots / waypoints"))

    def find_kinds(self) -> List[Dict[str, object]]:
        """How many places of each kind of ground find are recorded."""
        have = {r[0]: r[1] for r in self.cx.execute(
            "SELECT kind, COUNT(DISTINCT sys_id64 || '/' || body_name || '/' || label) "
            "FROM surface_marks WHERE kind IN (%s) GROUP BY kind"
            % ",".join("?" * len(self.FIND_KINDS)), [k for k, _l in self.FIND_KINDS])}
        return [{"kind": k, "label": l, "places": have.get(k, 0)}
                for k, l in self.FIND_KINDS if have.get(k)]

    def find_marks(self, kind: Optional[str] = None,
                   near: Optional[Sequence[float]] = None,
                   limit: int = 40, text: Optional[str] = None) -> List[Dict[str, object]]:
        """
        Ground finds, one row per thing per body (the latest position), nearest
        system first. Codex entries of the same thing on the same body - the
        game logs one per sighting - count as one place with a count.
        """
        kinds = [kind] if kind else [k for k, _l in self.FIND_KINDS]
        sql = ("SELECT m.kind, m.label, MAX(m.detail) detail, m.body_name, m.sys_id64, "
               "s.name sys_name, s.x, s.y, s.z, COUNT(*) count, MAX(m.ts) last, "
               "m.lat, m.lon FROM surface_marks m "
               "LEFT JOIN (SELECT id64, name, x, y, z, MAX(quality) q FROM systems "
               "GROUP BY id64) s ON s.id64 = m.sys_id64 WHERE m.kind IN (%s)"
               % ",".join("?" * len(kinds)))
        args: List[object] = list(kinds)
        if text:
            sql += " AND (m.label LIKE ? OR m.body_name LIKE ? OR m.detail LIKE ?)"
            args += ["%" + text + "%"] * 3
        sql += " GROUP BY m.kind, m.sys_id64, m.body_name, m.label"
        rows = self._with_dist(self.cx.execute(sql, args).fetchall(), near)
        for r in rows:
            r["system"] = r["sys_name"] or str(r["sys_id64"])
        return rows[:limit]

    def hotspot_materials(self) -> List[sqlite3.Row]:
        """Every material seen, with how many rings carry it."""
        return self.cx.execute(
            "SELECT material, label, COUNT(*) rings, SUM(count) spots "
            "FROM hotspots GROUP BY material ORDER BY spots DESC").fetchall()

    def find_hotspots(self, material: Optional[str] = None,
                      near: Optional[Sequence[float]] = None,
                      limit: int = 40) -> List[Dict[str, object]]:
        """
        Rings carrying a material, nearest first.

        Distance is from the given point when the system's coordinates are
        known; rings in systems we have no position for still come back, just
        without one, rather than being dropped.
        """
        sql = ("SELECT h.*, s.name sys_name, s.x, s.y, s.z FROM hotspots h "
               "LEFT JOIN (SELECT id64, name, x, y, z, MAX(quality) q FROM systems "
               "GROUP BY id64) s ON s.id64 = h.sys_id64")
        args: List[object] = []
        if material:
            sql += " WHERE h.material = ?"
            args.append(material)
        out: List[Dict[str, object]] = []
        for r in self.cx.execute(sql, args):
            d = None
            if near is not None and r["x"] is not None:
                d = math.dist((r["x"], r["y"], r["z"]), tuple(near))
            out.append({
                "system": r["sys_name"] or str(r["sys_id64"]),
                "body": r["body_name"],
                "material": r["label"] or r["material"],
                "count": r["count"],
                "ring_class": (r["ring_class"] or "").replace("eRingClass_", ""),
                "dist": d,
            })
        out.sort(key=lambda h: (h["dist"] if h["dist"] is not None else 1e9,
                                -h["count"]))
        return out[:limit]

    def bodies_of(self, sys_id64: int) -> List[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM bodies WHERE sys_id64=?",
                               (sys_id64,)).fetchall()

    def bio_training_rows(self) -> List[sqlite3.Row]:
        """Every body with analysed species - what biopredict learns from."""
        return self.cx.execute(
            "SELECT * FROM bodies WHERE bio_species IS NOT NULL").fetchall()

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
    def earnings(self) -> Dict[str, object]:
        """
        What the survey has actually paid, split by what earned it.

        Worth knowing because the two are nowhere near equal: on the test
        data 142 bodies of exploration data sold for 4.5 M, while 14
        biological samples from the same trip made 114 M. Per unit of effort
        bio is an order of magnitude ahead, which is a strong argument for
        keeping the "has bio or geo signals" filter on.
        """
        rows = self.cx.execute(
            "SELECT kind, SUM(base) b, SUM(bonus) o, SUM(total) t, "
            "SUM(bodies) n, COUNT(*) c FROM earnings GROUP BY kind").fetchall()
        out: Dict[str, object] = {"exploration": None, "organic": None,
                                  "total": 0, "sales": 0}
        for r in rows:
            out[r["kind"]] = {"base": r["b"] or 0, "bonus": r["o"] or 0,
                              "total": r["t"] or 0, "units": r["n"] or 0,
                              "sales": r["c"]}
            out["total"] += r["t"] or 0
            out["sales"] += r["c"]
        return out

    def lifetime(self) -> Dict[str, object]:
        """
        Totals across everything the plugin has ever recorded.

        Distance flown is summed over consecutive visited systems ordered by
        when they were first visited - an approximation, but it is the only
        figure available without keeping a separate flight log, and it is
        right to within the odd out-of-order jump.
        """
        q = lambda s, *a: self.cx.execute(s, a).fetchone()[0]
        fid = self.view_fid(PLAN)
        if fid:
            return self._lifetime_of(fid)
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

    def _lifetime_of(self, fid: str) -> Dict[str, object]:
        """lifetime() for one commander (C1): his visits, scans and finds;
        boxels, absent names and spheres stay shared survey knowledge."""
        q = lambda s, *a: self.cx.execute(s, a).fetchone()[0]   # noqa: E731
        rows = self.cx.execute(
            "SELECT s.x, s.y, s.z FROM cmdr_systems c JOIN systems s ON s.id64=c.sys_id64 "
            "WHERE c.fid=? AND c.visited_ts IS NOT NULL AND s.x IS NOT NULL "
            "ORDER BY c.visited_ts", (fid,)).fetchall()
        ly = 0.0
        for a, b in zip(rows, rows[1:]):
            d = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
            if d < 500.0:
                ly += d
        others = [c for c in self.commanders() if c["fid"] != fid and c["systems"]]
        return {
            "commander": self.commander_name(fid) or fid,
            "also": [(c["name"] or c["fid"], c["systems"]) for c in others],
            "systems_visited": q("SELECT COUNT(*) FROM cmdr_systems WHERE fid=? "
                                 "AND visited_ts IS NOT NULL", fid),
            "systems_known": q("SELECT COUNT(*) FROM systems"),
            "jumps_ly": ly,
            "bodies": q("SELECT COUNT(*) FROM cmdr_bodies WHERE fid=? AND scanned=1", fid),
            "mapped": q("SELECT COUNT(*) FROM cmdr_bodies WHERE fid=? AND mapped=1", fid),
            "first_discoveries": q("SELECT COUNT(*) FROM cmdr_bodies WHERE fid=? "
                                   "AND was_discovered=0", fid),
            "first_mapped": q("SELECT COUNT(*) FROM cmdr_bodies WHERE fid=? "
                              "AND was_mapped=0 AND mapped=1", fid),
            "bio_sampled": q("SELECT COUNT(*) FROM cmdr_bodies WHERE fid=? AND organics>0", fid),
            "boxels_closed": q("SELECT COUNT(*) FROM boxels WHERE complete=1"),
            "not_there": q("SELECT COUNT(*) FROM absent"),
            "spheres": q("SELECT COUNT(*) FROM spheres"),
            "since": q("SELECT MIN(visited_ts) FROM cmdr_systems WHERE fid=?", fid) or "?",
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

    # Lines processed per lock acquisition during a replay. Small enough that
    # anything else waiting for the database (EDMC's main thread delivering a
    # live journal event, the UI refresh) gets in within a few milliseconds.
    REPLAY_CHUNK = 200
    REPLAY_SLICE = 0.04     # seconds of work per lock hold
    REPLAY_PAUSE = 0.003    # seconds the lock is left free in between

    def import_journals(self, journal_dir: str, max_files: int = 0,
                        progress=None, lock=None) -> Dict[str, int]:
        """
        Replay existing journal files. Purely additive; the files are never
        modified. progress(done, total, filename) is called once per file.

        lock: the lock that guards this connection. When given, it is taken
        per chunk of REPLAY_CHUNK lines and released in between - never for
        the whole replay. A full replay takes about a minute, and in 4.1.0
        holding the lock that long froze EDMC's start-up for the same time.
        """
        import contextlib
        import glob
        guard = lock if lock is not None else contextlib.nullcontext()
        files = sorted(set(glob.glob(os.path.join(journal_dir, "Journal.*.log"))
                           + glob.glob(os.path.join(journal_dir, "Journal_*.log"))))
        if max_files:
            files = files[-max_files:]
        res = {"files": len(files), "events": 0, "lines": 0, "errors": 0}
        ctx: Tuple[Optional[str], Optional[str]] = (None, None)   # replay's commander
        for i, fn in enumerate(files, 1):
            if progress:
                try:
                    progress(i, len(files), os.path.basename(fn))
                except Exception:
                    pass
            try:
                # file I/O outside the lock
                with open(fn, "r", encoding="utf-8", errors="replace") as f:
                    lines = [ln.strip() for ln in f]
            except OSError:
                res["errors"] += 1
                continue
            lines = [ln for ln in lines if ln]
            pos = 0
            while pos < len(lines):
                with guard:
                    # C1: the replay follows the commanders in the files; the
                    # live commander (EDMC) is put back after every chunk, so
                    # an event arriving in between is never filed under the
                    # commander of an old journal - nor the other way round
                    live = (self.fid, self.fid_name)
                    self.fid, self.fid_name = ctx
                    # at most REPLAY_CHUNK lines and at most REPLAY_SLICE seconds
                    t_end = time.perf_counter() + self.REPLAY_SLICE
                    stop = min(pos + self.REPLAY_CHUNK, len(lines))
                    while pos < stop:
                        res["lines"] += 1
                        try:
                            res["events"] += self.ingest_journal_event(
                                json.loads(lines[pos]))
                        except Exception:
                            res["errors"] += 1
                        pos += 1
                        if time.perf_counter() > t_end:
                            break
                    ctx = (self.fid, self.fid_name)
                    self.fid, self.fid_name = live
                    self.cx.commit()
                if lock is not None:
                    # Python locks are not fair: without a real pause this
                    # thread takes the lock straight back and a waiting
                    # thread can starve for seconds.
                    time.sleep(self.REPLAY_PAUSE)
        return res


def _selftest() -> int:
    """Backup before migration: new file no backup, current file no backup,
    old schema or missing repair -> one backup, only the newest kept."""
    import tempfile
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "shboxsearch.sqlite")
        baks = lambda: glob.glob(glob.escape(path) + ".*.bak")   # noqa: E731
        db = SystemDB(path)
        check(db.backup_path is None, "new database: no backup")
        db.close()
        db = SystemDB(path)
        check(db.backup_path is None and not baks(), "current database: no backup")
        db.cx.execute("UPDATE meta SET v='2' WHERE k='schema'")
        db.cx.commit()
        db.close()
        db = SystemDB(path)
        check(db.backup_path is not None and len(baks()) == 1,
              "older schema: one backup")
        old = sqlite3.connect(db.backup_path)
        check(old.execute("SELECT v FROM meta WHERE k='schema'").fetchone()[0] == "2",
              "backup holds the state before the migration")
        old.close()
        check(stored_state(path) == (SCHEMA_VERSION, set(REPAIRS)),
              "migrated database is current")
        db.cx.execute("DELETE FROM meta WHERE k='fix_n1zero'")
        db.cx.commit()
        db.close()
        db = SystemDB(path)
        check(db.backup_path is not None and "fix_n1zero" in stored_state(path)[1],
              "pending repair: backup, then repair runs")
        db.close()
        for _ in range(4):
            backup_database(path, "test")
        check(len(baks()) == BACKUP_KEEP, "only the newest %d backups kept" % BACKUP_KEEP)
        db = SystemDB(path)
        now = time.time()
        db.log_external_calls([(now - 40 * 86400, "edsm", "sphere", 200, True, 50),
                               (now, "edsm", "sphere", 429, False, 30),
                               (now, "spansh", "search", 200, True, 900)])
        check(db.external_calls_since(now - 60) == 2
              and db.external_calls_since(now - 60, "edsm") == 1,
              "call log counts per service")
        check(db.prune_external_calls() == 1 and db.external_calls_since(0) == 2,
              "call log keeps %d days" % CALL_LOG_DAYS)
        db.record_shell("edsm", (1, 2, 3), 0, 25, 40, 5 * 86400, now=now)
        db.record_shell("edsm", (1, 2, 3), 25, 50, 90, 10, now=now - 86400)
        db.record_shell("spansh", (1, 2, 3), 0, 25, 41, 9 * 86400, now=now)
        check(db.valid_shells("edsm", now) == [(1.0, 2.0, 3.0, 0.0, 25.0)]
              and len(db.valid_shells("spansh", now)) == 1,
              "fetched shells: valid ones per service, expired ones not")
        db.close()
        legacy = os.path.join(d, "legacy.sqlite")
        cx = sqlite3.connect(legacy)
        cx.execute("CREATE TABLE systems (name TEXT)")
        cx.commit()
        cx.close()
        check(stored_state(legacy) == (0, set()), "database without meta = schema 0")
        db = SystemDB(os.path.join(d, "carrier.sqlite"))
        db.ingest_journal_event({"event": "Docked", "StationType": "FleetCarrier",
                                 "StationName": "ZZZ-001", "MarketID": 1001,
                                 "StarSystem": "Test Alpha", "SystemAddress": 11})
        check(db.get_carrier() is None, "docking at a stranger's carrier: no own carrier")
        db.ingest_journal_event({"event": "CarrierLocation", "CarrierType": "FleetCarrier",
                                 "CarrierID": 2002, "StarSystem": "Test Home",
                                 "SystemAddress": 22})
        db.ingest_journal_event({"event": "CarrierStats", "CarrierID": 2002,
                                 "Callsign": "OWN-002", "Name": "TEST OWN"})
        db.ingest_journal_event({"event": "Docked", "StationType": "FleetCarrier",
                                 "StationName": "ZZZ-001", "MarketID": 1001,
                                 "StarSystem": "Test Alpha", "SystemAddress": 11})
        db.ingest_journal_event({"event": "Disembark", "OnStation": True})
        db.ingest_journal_event({"event": "CarrierJump", "OnFoot": True, "Docked": False,
                                 "StarSystem": "Test Beta", "SystemAddress": 33,
                                 "StarPos": [1.0, 2.0, 3.0]})
        c = db.get_carrier()
        check(c and c["system"] == "Test Home" and c["callsign"] == "OWN-002",
              "stranger's carrier (docked, jump on foot) leaves the own carrier alone")
        db.ingest_journal_event({"event": "Undocked"})
        db.ingest_journal_event({"event": "Docked", "StationType": "FleetCarrier",
                                 "StationName": "OWN-002", "MarketID": 2002,
                                 "StarSystem": "Test Home", "SystemAddress": 22})
        db.ingest_journal_event({"event": "CarrierJump", "OnFoot": True, "Docked": False,
                                 "StarSystem": "Test Gamma", "SystemAddress": 44,
                                 "StarPos": [4.0, 5.0, 6.0]})
        check(db.get_carrier()["system"] == "Test Gamma", "own carrier jump while aboard counts")
        db.ingest_journal_event({"event": "FSDJump", "StarSystem": "Test Town",
                                 "SystemAddress": 55, "StarPos": [7.0, 8.0, 9.0],
                                 "Population": 4200, "Factions": [{"Name": "F"}]})
        db.ingest_journal_event({"event": "FSDJump", "StarSystem": "Test Void",
                                 "SystemAddress": 66, "StarPos": [9.0, 8.0, 7.0],
                                 "Population": 0})
        db.ingest_journal_event({"event": "Docked", "StationType": "Coriolis",
                                 "StationName": "Port", "MarketID": 77,
                                 "StarSystem": "Test Port", "SystemAddress": 77})
        src = lambda nm: set(((db.system(nm) or {"sources": ""})["sources"] or "").split(","))  # noqa: E731
        check(INHABITED in src("Test Town") and INHABITED not in src("Test Void")
              and INHABITED in src("Test Port") and INHABITED not in src("Test Alpha"),
              "I1: population/factions/station marks 'inhabited', empty system and carrier not")
        check(db.system("Test Town")["quality"] == Q_JOURNAL and db.system("Test Town")["x"] == 7.0,
              "I1: marking keeps the journal position")
        nb = {"event": "Scan", "ScanType": "NavBeaconDetail", "StarSystem": "Test Town",
              "SystemAddress": 55, "BodyName": "Test Town 1", "BodyID": 1,
              "PlanetClass": "Rocky body", "DistanceFromArrivalLS": 10.0,
              "WasDiscovered": True, "WasMapped": False}
        db.ingest_journal_event(nb)
        own = dict(nb, ScanType="Detailed", BodyName="Test Town 2", BodyID=2)
        db.ingest_journal_event(own)
        db.ingest_journal_event(dict(own, ScanType="NavBeaconDetail"))
        b = {r["body_id"]: r for r in db.bodies_of(55)}
        check(b[1]["planet_class"] == "Rocky body" and b[1]["was_discovered"] == 1
              and not b[1]["scanned"] and b[2]["scanned"] == 1,
              "NavBeaconDetail: body data stored, not counted as your scan (an own scan stays)")
        db.close()
        n_cmdr = _selftest_cmdr(d, check)
        fails += n_cmdr
    print("failures: %d" % fails)
    return fails


def _selftest_cmdr(d: str, check) -> int:
    """C1: exploration per commander, knowledge shared, main commander,
    and an upgraded database falls back to the shared view until replayed."""
    db = SystemDB(os.path.join(d, "cmdr.sqlite"))
    check(db.cmdr_ready(), "C1: a new database is per-commander from the start")
    ev = db.ingest_journal_event
    ev({"event": "Commander", "FID": "F1", "Name": "Main", "timestamp": "2026-01-01T10:00:00Z"})
    ev({"event": "LoadGame", "FID": "F1", "Commander": "Main", "timestamp": "2026-01-01T10:00:01Z"})
    ev({"event": "CarrierStats", "CarrierID": 9, "Callsign": "OWN-009", "Name": "C"})
    ev({"event": "FSDJump", "StarSystem": "Cm Alpha", "SystemAddress": 501,
        "StarPos": [1.0, 0.0, 0.0], "timestamp": "2026-01-01T10:01:00Z"})
    scan = {"event": "Scan", "ScanType": "Detailed", "StarSystem": "Cm Alpha",
            "SystemAddress": 501, "BodyName": "Cm Alpha 1", "BodyID": 1,
            "PlanetClass": "Water world", "DistanceFromArrivalLS": 10.0,
            "WasDiscovered": False, "WasMapped": False}
    ev(scan)
    ev({"event": "SAAScanComplete", "SystemAddress": 501, "BodyID": 1, "BodyName": "Cm Alpha 1"})
    ev({"event": "FSSBodySignals", "SystemAddress": 501, "BodyID": 1, "BodyName": "Cm Alpha 1",
        "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 2}]})
    ev({"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 501, "Body": 1,
        "Species_Localised": "Bacterium Aurasus", "Genus_Localised": "Bacterium",
        "timestamp": "2026-01-01T10:20:00Z"})
    ev({"event": "FSSAllBodiesFound", "SystemName": "Cm Alpha", "SystemAddress": 501, "Count": 1})
    for i in range(3):
        ev({"event": "LoadGame", "FID": "F2", "Commander": "Second",
            "timestamp": "2026-01-0%dT10:00:00Z" % (i + 2)})
    ev({"event": "Location", "StarSystem": "Cm Alpha", "SystemAddress": 501,
        "StarPos": [1.0, 0.0, 0.0], "timestamp": "2026-01-05T10:00:00Z"})
    check(db.fid == "F2" and db.commander_name("F1") == "Main", "C1: FID follows LoadGame")
    p2 = db.system_progress(501, CURRENT)
    p1 = db.system_progress(501, "F1")
    check(p1["mapped"] == 1 and p1["fss_complete"] and p1["bio_signals_open"] == 1
          and p1["new_discoveries"] == 1, "C1: the first commander's own state")
    check(p2["scanned"] == 0 and p2["mapped"] == 0 and not p2["fss_complete"]
          and p2["dss_open"] == ["Cm Alpha 1"] and p2["bio_open"] == ["Cm Alpha 1"]
          and p2["bio_signals_open"] == 2,
          "C1: the second commander still has the work (FSS, DSS, both bio signals)")
    rows = {r["body_id"]: r for r in db.bodies_for(501, "F2")}
    check(rows[1]["planet_class"] == "Water world" and rows[1]["sig_bio"] == 2,
          "C1: knowledge (class, signals) is shared")
    check(len(db.bio_training_rows()) == 1, "C1: the bio model learns from every commander")
    check(db.suggest_main() == "F1", "C1: suggestion = the commander with a carrier (not most logins)")
    db.cx.execute("UPDATE commanders SET carrier=0")
    check(db.suggest_main() == "F2", "C1: without a carrier the one with most sessions")
    check(db.set_main_commander("F1") == "F1" and db.get_meta("main_fid") == "F1",
          "C1: the main commander is stored for the FIS")
    sp = db.sphere((0.0, 0.0, 0.0), 5.0)
    check(len(sp) == 1 and sp[0]["visited"] == 1 and sp[0]["fss_complete"] == 1,
          "C1: the survey sphere plans for the main commander")
    lt = db.lifetime()
    check(lt["commander"] == "Main" and lt["first_discoveries"] == 1 and lt["bio_sampled"] == 1
          and lt["also"] == [("Second", 1)], "C1: statistics of the main commander, 'also by'")
    check(db.explorers(501, but="F1") == ["Second"], "C1: also explored by")
    jd = os.path.join(d, "journals")
    os.makedirs(jd)
    for i, (fid, nm, sa) in enumerate((("F7", "Seven", 701), ("F8", "Eight", 702))):
        with open(os.path.join(jd, "Journal.2026-01-0%dT100000.01.log" % (i + 1)), "w",
                  encoding="utf-8") as fh:
            for e in ({"event": "Fileheader"},
                      {"event": "Commander", "FID": fid, "Name": nm,
                       "timestamp": "2026-01-0%dT10:00:00Z" % (i + 1)},
                      {"event": "FSDJump", "StarSystem": "Cm R%d" % i, "SystemAddress": sa,
                       "StarPos": [5.0, 5.0, float(i)], "timestamp": "2026-01-0%dT10:05:00Z" % (i + 1)}):
                fh.write(json.dumps(e) + "\n")
    db.set_commander("F9", "Live")
    db.import_journals(jd)
    check(db.fid == "F9" and db.explorers(701) == ["Seven"] and db.explorers(702) == ["Eight"],
          "C1: a replay files each journal under its own commander, the live one stays")
    # R3: Second rides along on a carrier into Cm Beta (never explored)
    db.set_commander("F2", "Second")
    ev({"event": "CarrierJump", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Beta", "SystemAddress": 502, "StarPos": [2.0, 0.0, 0.0],
        "Body": "Cm Beta 3", "BodyID": 7, "BodyType": "Planet",
        "timestamp": "2026-01-06T10:00:00Z"})
    check(db.route_start("F2", 502) == (7, "Cm Beta 3"), "R3: carrier jump into an unexplored system")
    ev(dict(scan, StarSystem="Cm Beta", SystemAddress=502, BodyName="Cm Beta 3", BodyID=7,
            timestamp="2026-01-06T10:05:00Z"))
    ev({"event": "CarrierJump", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Beta", "SystemAddress": 502, "StarPos": [2.0, 0.0, 0.0],
        "Body": "Cm Beta 3", "BodyID": 7, "BodyType": "Planet",
        "timestamp": "2026-01-06T10:00:00Z"})
    check(db.route_start("F2", 502) == (7, "Cm Beta 3"), "R3: a replay keeps the decision")
    ev({"event": "Location", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Beta", "SystemAddress": 502, "StarPos": [2.0, 0.0, 0.0],
        "Body": "Cm Beta 3", "BodyID": 7, "timestamp": "2026-01-07T10:00:00Z"})
    check(db.route_start("F2", 502) is None, "R3: explored meanwhile -> later routes at the main star")
    ev({"event": "Location", "Docked": True, "StationType": "FleetCarrier",
        "StarSystem": "Cm Gamma", "SystemAddress": 503, "StarPos": [3.0, 0.0, 0.0],
        "Body": "Cm Gamma 1", "BodyID": 4, "timestamp": "2026-01-08T10:00:00Z"})
    check(db.route_start("F2", 503) == (4, "Cm Gamma 1"), "R3: loading docked at a carrier, unexplored")
    ev({"event": "FSDJump", "StarSystem": "Cm Gamma", "SystemAddress": 503,
        "StarPos": [3.0, 0.0, 0.0], "timestamp": "2026-01-09T10:00:00Z"})
    check(db.route_start("F2", 503) is None, "R3: arriving by FSD -> main star")
    check(db.route_start("F1", 502) is None, "R3: per commander")
    db.cx.execute("DELETE FROM meta WHERE k=?", (CMDR_READY,))
    check(db.system_progress(501, CURRENT)["mapped"] == 1,
          "C1: not replayed yet -> shared view (anyone)")
    # crash: F1 scans Cm Delta 1 (sold), Cm Delta 2 and a species (not sold) - then dies
    db.set_commander("F1", "Main")
    ev({"event": "FSDJump", "StarSystem": "Cm Delta", "SystemAddress": 504,
        "StarPos": [4.0, 0.0, 0.0], "timestamp": "2026-02-01T10:00:00Z"})
    for bid in (1, 2):
        ev(dict(scan, StarSystem="Cm Delta", SystemAddress=504, BodyName="Cm Delta %d" % bid,
                BodyID=bid, timestamp="2026-02-01T10:0%d:00Z" % bid))
    ev({"event": "MultiSellExplorationData", "Discovered": [{"SystemName": "Cm Delta"}],
        "timestamp": "2026-02-01T10:05:00Z"})
    ev({"event": "SAAScanComplete", "SystemAddress": 504, "BodyID": 2, "BodyName": "Cm Delta 2"})
    ev({"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 504, "Body": 2,
        "Species_Localised": "Stratum Tectonicas", "timestamp": "2026-02-01T10:20:00Z"})
    ev({"event": "Scan", "ScanType": "Detailed", "StarSystem": "Cm Delta", "SystemAddress": 504,
        "BodyName": "Cm Delta 3", "BodyID": 3, "PlanetClass": "Icy body",
        "timestamp": "2026-02-01T10:21:00Z"})
    db.set_route_done(504, 2, True)
    db.cx.execute("UPDATE bodies SET route_done_ts='2026-02-01T10:25:00Z' WHERE sys_id64=504")
    ev({"event": "Died", "timestamp": "2026-02-01T10:30:00Z"})
    check(db.route_done_of(504) == set(), "crash: route ticks of the lost work are cleared")
    b = {r["body_id"]: r for r in db.bodies_for(504, "F1")}
    check(b[1]["scanned"] == 1 and not b[1]["lost_what"], "crash: sold data stays")
    check(b[2]["scanned"] == 1 and b[2]["mapped"] == 0 and b[2]["organics"] == 0
          and json.loads(b[2]["lost_what"]) == ["bio:Stratum Tectonicas", "map"],
          "crash: unsold map and species undone and marked lost (sold scan stays)")
    check(b[3]["scanned"] == 0 and json.loads(b[3]["lost_what"]) == ["scan"],
          "crash: unsold scan undone and marked lost")
    lost = {d["name"]: d for d in db.lost_summary("F1")}
    check(lost["Cm Delta"]["bio"] == ["Stratum Tectonicas"] and lost["Cm Delta"]["scan"] == 1
          and "Cm Alpha" in lost,              # scanned there earlier, never sold
          "crash: lost summary per system")
    check(db.lost_of_body("F1", 504, 2) == ["bio:Stratum Tectonicas", "map"]
          and db.lost_of_body("F1", 504, 1) == [] and db.lost_of_body(None, 504, 2) == []
          and db.lost_of_body("F2", 504, 2) == [],
          "crash: lost marks of one body, for that commander only")
    check(db.bio_training_rows() and any("Tectonicas" in (r["bio_species"] or "")
                                         for r in db.bio_training_rows()),
          "crash: the shared knowledge (bio model) keeps what was found")
    ev({"event": "SAAScanComplete", "SystemAddress": 504, "BodyID": 2, "BodyName": "Cm Delta 2"})
    ev({"event": "ScanOrganic", "ScanType": "Analyse", "SystemAddress": 504, "Body": 2,
        "Species_Localised": "Stratum Tectonicas", "timestamp": "2026-02-02T10:20:00Z"})
    b = {r["body_id"]: r for r in db.bodies_for(504, "F1")}
    check(not b[2]["lost_what"] and b[2]["mapped"] == 1, "crash: redone -> no longer marked")
    db.cx.execute("UPDATE meta SET v='4' WHERE k='schema'")
    db.cx.commit()
    db.close()
    db = SystemDB(os.path.join(d, "cmdr.sqlite"))
    check(db.backup_path is not None and not db.cmdr_ready()
          and db.cx.execute("SELECT COUNT(*) FROM cmdr_bodies").fetchone()[0] >= 1,
          "C1: schema 4 -> 5 makes a backup, keeps the data, waits for the replay")
    db.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(1 if _selftest() else 0)
