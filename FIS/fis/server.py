# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""HTTP server: static web files, JSON API and Server-Sent Events.

Standard library only (ThreadingHTTPServer). Default bind 127.0.0.1; with
--lan it binds 0.0.0.0 and every request from another device needs the token
from fis.ini, as `?token=...` or header `X-FIS-Token`; this PC itself (loopback
with a local Host) passes without it (5.0.1).
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import config as config_mod
from . import __version__, setup
from . import qr as qr_mod
from .config import WEB_DIR, Config
from .data import Database
from .live import Hub, LiveTracker

_RE_SYS = re.compile(r"^/api/system/(\d+)$")
_RE_BODY = re.compile(r"^/api/body/(\d+)/(\d+)$")


class App:
    """Everything a request handler needs, shared across threads."""

    def __init__(self, cfg: Config, live: Optional[LiveTracker] = None,
                 db: Optional[Database] = None, web_dir: str = WEB_DIR) -> None:
        cfg.use_plugin_path()
        from . import model  # after sys.path is set
        self.model = model
        self.cfg = cfg
        self.lan_at_start = cfg.lan          # LAN on/off needs a restart
        self.watch_restarts = 0
        self._watch_stop = threading.Event()
        self.db = db or Database(cfg.db_path)
        self.db.main_setting = getattr(cfg, "main_cmdr", "") or ""
        self.hub = live.hub if live else Hub()
        self.live = live or LiveTracker(cfg.journal_dir, self.hub, cfg.poll_s)
        self.web_dir = web_dir
        self.started = time.time()
        self._cache: Dict[str, Tuple[Any, Any]] = {}
        self._cache_lock = threading.Lock()
        self._kepler_busy = False
        self._kepler_last: Optional[Dict[str, Any]] = None
        self._stop = threading.Event()
        from .fleet import Archive
        self.archive = Archive(cfg.journal_dir)
        self.archive.use_edd(cfg.edd_user_db())     # 5.0: EDDiscovery's archive, when on
        from .favourites import FavouriteStore
        # personal (K2): next to fis.ini, never in the repository
        self.favourites = FavouriteStore(os.path.join(os.path.dirname(cfg.ini_path), "favourites.json"))
        from .losthidden import LostHiddenStore
        # SHIP -> LOST DATA: crash losses hidden from the list (FIS-owned file)
        self.lost_hidden = LostHiddenStore(os.path.join(os.path.dirname(cfg.ini_path), "lost_hidden.json"))
        from .vehicletanks import VehicleTankStore
        # V1b: tank size per vehicle type, learnt after a refuel synthesis (FIS-owned file)
        self.vehicle_tanks = VehicleTankStore(os.path.join(os.path.dirname(cfg.ini_path), "vehicle_tanks.json"))
        # 5.0 JUMP PLAN: the carrier's plan and "target full" reports (FIS-owned file)
        from .jumpplan import PlanStore
        self.jumpplans = PlanStore(os.path.join(os.path.dirname(cfg.ini_path), "jump_plan.json"))
        self._edd_stars: Any = None
        # K5: the one online lookup of the FIS (on a click, through the plugin's gateway)
        from .online import CarrierLookup
        self.lookup = CarrierLookup(__version__, calls_today=self._calls_today,
                                    offline=self._plugin_offline)
        # SK3: when a learnt model was reset (FIS-owned file next to fis.ini,
        # read by the plugin at start-up too)
        self.learn_reset_path = os.path.join(os.path.dirname(cfg.ini_path), "learn_reset.json")
        lr = model.plugin().learnreset
        if lr is not None:
            self.live.fuel_since = lr.fuel_since(lr.load(self.learn_reset_path))
        from .calib import Calibrator
        self.calib = Calibrator(cfg.journal_dir, model.plugin().sysroute, self._leg_ls,
                                marks=self._learn_marks)

    def _learn_marks(self) -> Dict[str, Any]:
        """The model resets (plugin learnreset), empty with an older plugin."""
        lr = self.model.plugin().learnreset
        return lr.load(self.learn_reset_path) if lr is not None else {}

    def _sold_marks(self) -> Dict[str, float]:
        """SM1: the logged-in commander's sold marks ({"explo": ts, "bio": ts})."""
        lr = self.model.plugin().learnreset
        if lr is None or not hasattr(lr, "sold_since"):
            return {}
        return lr.sold_since(self._learn_marks(), self.archive.commander()[0])

    def _unsold_now(self) -> Optional[Dict[str, Any]]:
        """M4 unsold data with the commander's limits, value reset and sold marks."""
        from . import shipview
        return shipview._unsold(self.archive, self.cfg.unsold, self._learn_marks().get("value"),
                                self._sold_marks())

    def _leg_ls(self, id64: int, a: str, b: str, at: float) -> Optional[float]:
        """Distance body a -> body b at time `at`, from the plugin's orbits."""
        try:
            sysroute = self.model.plugin().sysroute
            return sysroute.leg_distance_ls(self.db.bodies_of(int(id64)), a, b, at=at)
        except Exception:
            return None

    def _arrival_ls(self, id64: int, body_id: Optional[int], name: Optional[str]) -> Optional[float]:
        try:
            if body_id is not None:
                r = self.db.body(int(id64), int(body_id))
                if r is not None:
                    return r["arrival_ls"]
            if name:
                for r in self.db.bodies_of(int(id64)):
                    if r["name"] == name:
                        return r["arrival_ls"]
        except Exception:
            return None
        return None

    def watch_db(self, interval: float = 1.0) -> threading.Thread:
        """Push a `scan` event when the plugin has written to the database,
        so the views refresh after the plugin (not only the journal) moved."""
        def run() -> None:
            last = self.db.mtime()
            while not self._stop.wait(interval):
                mt = self.db.mtime()
                if mt != last:
                    last = mt
                    self.hub.publish("scan", {"source": "db", "ts": time.time()})
        th = threading.Thread(target=run, name="fis-db", daemon=True)
        th.start()
        return th

    def stop(self) -> None:
        """Ask the background watchers to stop."""
        self._stop.set()

    def live_state(self) -> Dict[str, Any]:
        """A copy of the live state."""
        return self.live.snapshot()

    def forecast_inputs(self) -> Dict[str, Any]:
        """B-24: your minutes per worked system (own-4) and value per hour of
        your sessions of at least 30 min (RT1/FX0), cached while the
        journals and the database stand still."""
        evs = self.archive.events()
        sig = (len(evs), evs[-1].get("timestamp") if evs else None, self.db.mtime())

        def build() -> Dict[str, Any]:
            from . import stats, systime
            from .shipview import _bodyvalue
            st = systime.build(evs, self.db, self.archive.commander()[0], keep=1 << 30)
            ses = stats.play_sessions(evs, _bodyvalue(), self.archive.organic_values(), keep=1 << 30)
            long_ = [r for r in ses["sessions"] if r["minutes"] * 60 >= stats.SESSION_MIN_S]
            return {"minutes": {r["id64"]: r["minutes"] for r in st["systems"]},
                    "value_h": [r["value_h"] for r in long_ if r["value_h"] is not None]}
        return self.cached("forecast_inputs", sig, build)

    def sphere_forecast(self, survey: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """B-24: hours, value and finds still ahead in the active sphere -
        minutes from the sphere's own worked systems once there are three,
        else from all of yours."""
        if not survey or not survey.get("center") or not survey.get("systems"):
            return None
        from . import forecast, learn
        inp = self.forecast_inputs()
        c = survey["center"]
        ids = {int(r["id64"]) for r in self.db.systems_in_sphere(c[0], c[1], c[2], survey.get("radius") or 0.0)
               if r["visited"] and r["id64"] is not None}
        own = [v for k, v in inp["minutes"].items() if k in ids]
        mins = own if len(own) >= forecast.MIN_N else list(inp["minutes"].values())
        out = forecast.sphere(survey["systems"], mins, inp["value_h"], learn.find_odds(self.db))
        if out:
            out["minutes_from"] = "sphere" if mins is own else "all"
        return out

    def forecasts(self) -> Dict[str, Any]:
        """B-24 for STATISTICS > LEARNING STATUS: the sphere's rest and the
        tank in jumps."""
        out: Dict[str, Any] = {"sphere": None, "jumps": None}
        try:
            out["sphere"] = self.sphere_forecast(self.model.build_survey(self.db))
        except Exception:
            out["sphere"] = None
        try:
            from . import forecast
            out["jumps"] = forecast.jumps(self.model._fuel_state(self.live_state()))
        except Exception:
            out["jumps"] = None
        return out

    def kepler_check(self, wait: bool = False) -> Optional[Dict[str, Any]]:
        """V0: the Kepler watch over every system with two scanned bodies or
        more - a few seconds (12 s on a full database), so kept until 25 more
        bodies are scanned. R1: without `wait` it never computes in the
        request - it hands back the last result (or {"pending": True}) and
        computes in the background, then tells the browsers."""
        n = (self.db.one("SELECT COUNT(*) AS n FROM bodies WHERE scanned = 1") or {"n": 0})["n"]
        sig = int(n) // 25
        with self._cache_lock:
            hit = self._cache.get("kepler_check")
        if hit and hit[0] == sig:
            return hit[1]
        if wait:
            return self._kepler_compute(sig)
        with self._cache_lock:
            busy, self._kepler_busy = self._kepler_busy, True
        if not busy:
            def run() -> None:
                try:
                    self._kepler_compute(sig)
                    self.hub.publish("scan", {"source": "kepler", "ts": time.time()})
                except Exception:
                    with self._cache_lock:          # no retry loop until 25 more scans
                        self._cache["kepler_check"] = (sig, None)
                    self._kepler_last = None
                finally:
                    with self._cache_lock:
                        self._kepler_busy = False
            threading.Thread(target=run, name="fis-kepler", daemon=True).start()
        return self._kepler_last if self._kepler_last is not None else {"pending": True}

    def _kepler_compute(self, sig: int) -> Optional[Dict[str, Any]]:
        from . import realitycheck

        def build() -> Optional[Dict[str, Any]]:
            m = self.model
            p = m.plugin()
            sr = p.sysroute
            ids = [r["sys_id64"] for r in self.db.query(
                "SELECT sys_id64 FROM bodies WHERE scanned = 1 GROUP BY sys_id64 HAVING COUNT(*) >= 2")]
            now = time.time()

            def summary(id64: int) -> Optional[Dict[str, int]]:
                rows = self.db.bodies_for(id64, None)
                srow = self.db.system_by_id64(id64)
                bodies, _by = m._system_bodies(p, self.db, rows, (srow["name"] if srow else "") or "", now)
                if not any(b.pos for b in bodies.values()):
                    sr.resolve_positions(bodies)
                out = sr.check_summary(bodies)
                bar, ls_m = getattr(sr, "CHECK_BAR", 0.01), getattr(sr, "LS_PER_METRE", 1.0 / 299792458.0)
                out.update(realitycheck.double_moons(bodies, bar, ls_m))
                return out
            return realitycheck.kepler(ids, summary)
        val = self.cached("kepler_check", sig, build)
        self._kepler_last = val
        return val

    def reality(self, stats_out: Dict[str, Any]) -> List[Dict[str, Any]]:
        """V0: one error value per learning model, from what the statistics
        payload already holds plus the fuel and Kepler checks."""
        from . import realitycheck
        L = stats_out.get("learning") or {}
        models = L.get("models") or {}
        parts: Dict[str, Any] = {"route": stats_out.get("systime"), "work": models.get("work"),
                                 "value": models.get("value"),
                                 "finds": realitycheck.finds(L.get("finds")),
                                 "bio": (stats_out.get("bio_rates") or {}).get("v0")}
        try:
            live = self.live_state()
            base = self.model._fuel_state(live)

            def make(js: List[Any]) -> Any:
                fs = self.model._fuel_state(dict(live, jumps=js))
                fs.unladen, fs.cargo, fs.fsd = getattr(base, "unladen", 0.0), getattr(base, "cargo", 0.0), base.fsd
                return fs
            parts["fuel"] = realitycheck.fuel(live.get("jumps") or [], make)
        except Exception:
            parts["fuel"] = None
        try:
            parts["kepler"] = self.kepler_check()
        except Exception:
            parts["kepler"] = None
        parts.update(self.mining_reality())
        try:
            parts["scoop"] = self.scoop()["reality"]
        except Exception:
            parts["scoop"] = None
        return realitycheck.build(parts)

    def scoop(self) -> Dict[str, Any]:
        """B-15: fuel scoop rate per star class from your journals, and its
        reality check - cached while the journals stand still."""
        evs = self.archive.events()
        sig = (len(evs), evs[-1].get("timestamp") if evs else None)

        def build() -> Dict[str, Any]:
            from . import scooprate
            smp = scooprate.samples(evs)
            return {"rates": scooprate.rates(smp), "reality": scooprate.reality(smp), "min_n": scooprate.MIN_N}
        return self.cached("scoop", sig, build)

    def mining_reality(self) -> Dict[str, Any]:
        """R3: tonnes per rock (MP1, the plugin's RockYield) and collector
        lifetime (ML1) against what came after - cached while the journals
        stand still."""
        evs = self.archive.events()
        sig = (len(evs), evs[-1].get("timestamp") if evs else None)

        def build() -> Dict[str, Any]:
            from . import mining, realitycheck
            from .model import _optional
            ms = _optional("miningstat")
            out: Dict[str, Any] = {"rocks": None, "collectors": None}
            try:
                if ms is not None and hasattr(ms, "RockYield"):
                    out["rocks"] = realitycheck.rock_yield(evs, ms.RockYield)
            except Exception:
                out["rocks"] = None
            try:
                out["collectors"] = realitycheck.collectors(mining.collector_waves(evs))
            except Exception:
                out["collectors"] = None
            return out
        return self.cached("mining_reality", sig, build)

    def cached(self, key: str, sig: Any, build) -> Any:
        """Rebuild only when the database or the relevant live data moved."""
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and hit[0] == sig:
                return hit[1]
        val = build()
        with self._cache_lock:
            self._cache[key] = (sig, val)
            if len(self._cache) > 64:
                self._cache.pop(next(iter(self._cache)))
        return val

    def _calls_today(self) -> Dict[str, int]:
        """Today's requests from the plugin's call log (read only) - one cap for both."""
        try:
            day0 = int(time.time() // 86400) * 86400
            rows = self.db.query("SELECT service, COUNT(*) n FROM external_calls WHERE ts >= ? "
                                 "GROUP BY service", (day0,))
            return {r["service"]: int(r["n"]) for r in rows}
        except Exception:
            return {}

    def _plugin_offline(self) -> bool:
        """The plugin's "offline" switch (EDMC config.toml) holds for the FIS too."""
        try:
            data = self.cfg._plugin_settings() or {}
        except Exception:
            data = {}
        return str(data.get("shboxsearch_offline", "")).lower() in ("true", "1")

    # ------------------------------------------------------------ routes
    def fid(self) -> Optional[str]:
        """C1: the commander playing (journal archive), for their own exploration."""
        try:
            return self.archive.commander()[0]
        except Exception:
            return None

    def system(self, id64: int) -> Dict[str, Any]:
        """The SYSTEM record of a system: bodies with positions, signals,
        carriers and places; cached for 30 s while the database does not
        change."""
        live = self.live_state()
        fx = live.get("last_fix") or {}
        cur = live.get("system") or {}
        # positions move along their orbits; a 30 s bucket is plenty
        sig = (self.db.mtime(), int(time.time() // 30), cur.get("id64"),
               fx.get("body_id"), fx.get("body"),
               int((fx.get("ts") or 0) // 60), id(self.calib.model),
               tuple(self.cfg.filters), self.cfg.skip_arrival, self.archive.rev,
               self.fid())
        self.calib.maybe_refresh()
        cm, om = self.calib.model, self.calib.order_model
        out = self.cached("sys:%d" % id64, sig, lambda: self.model.build_system(
            self.db, id64, live, self.cfg.filters, cost_model=cm, order_model=om,
            skip_arrival=self.cfg.skip_arrival, archive=self.archive, fid=self.fid()))
        out = self._with_places(self._with_favourites(self._with_carrier(out, id64)), id64)
        try:
            out = dict(out, time_here=self._time_here(id64))
        except Exception:
            pass
        return out

    def _time_here(self, id64: int) -> Optional[Dict[str, Any]]:
        """own-4: the time spent in this system so far and the route's kept
        estimate (systime)."""
        from . import systime
        evs = self.archive.events()
        v = self.cached("systime:visits", (len(evs), evs[-1].get("timestamp") if evs else None),
                        lambda: systime.visits(evs))
        return systime.here(v.get(id64), systime.estimates(self.db, self.fid()).get(id64))

    def archive_planets(self) -> List[Dict[str, Any]]:
        """EA2: landable planets the archive knows and the plugin database
        does not (learn.archive_planets) - with the EDDiscovery archive on."""
        from . import fleet, learn
        known = {(r["sys_id64"], r["body_id"]) for r in self.db.query("SELECT sys_id64, body_id FROM bodies")}
        return learn.archive_planets(self.archive.events(fleet.ALL_COMMANDERS), known)

    def _with_places(self, out: Dict[str, Any], id64: int) -> Dict[str, Any]:
        """S2b: what the SYSTEM map draws - your favourite carriers as long as
        their newest known position is here, other carriers while fresh, never
        your own a second time (carriers.map_places)."""
        try:
            from . import carriers
            favs = carriers.build_known(self.archive, self.favourites, None, sighted=0)["favourites"]
            here = [f for f in carriers.carriers_here(id64, out.get("name"), None, favs)
                    if f.get("kind") == "favourite"]
            own = (out.get("carrier") or {}).get("callsign")
            poi, extra = carriers.map_places(out.get("poi") or [], own, here)
        except Exception:
            return out
        return dict(out, poi=poi, fav_here=extra)

    def _with_favourites(self, out: Dict[str, Any]) -> Dict[str, Any]:
        """K4: a star at your favourite carriers among the points of interest;
        A1: their docking access where known, carriers refusing us left out."""
        if not out.get("poi"):
            return out
        try:
            from .carriers import docking_access, mark_docking_pois, mark_favourite_pois
            saved = self.favourites.get(self.archive.commander()[0])
        except Exception:
            return out
        favs = saved.get("favourites") or {}
        poi = out["poi"]
        hidden = 0
        try:
            acc = docking_access(self.archive.events(), saved.get("markets"), favs)
            poi, hidden = mark_docking_pois(poi, acc)
        except Exception:
            pass
        if favs:
            poi = mark_favourite_pois(poi, favs)
        if poi is out["poi"] and not hidden:
            return out
        return dict(out, poi=poi, poi_hidden=hidden)

    def favourite_carriers_at(self) -> List[Dict[str, Any]]:
        """K4 GALAXY: your favourite carriers at their last known position."""
        try:
            from . import carriers
            favs = carriers.build_known(self.archive, self.favourites, None, sighted=0)["favourites"]
        except Exception:
            return []
        out = []
        for c in favs:
            p = c.get("pos")
            if p and len(p) >= 3:
                out.append({"callsign": c["callsign"], "name": c.get("name"), "system": c.get("system"),
                            "id": c.get("id64"), "ts": c.get("ts"), "how": c.get("how"),
                            "x": round(float(p[0]), 2), "y": round(float(p[1]), 2), "z": round(float(p[2]), 2)})
        return out

    def carriers_here(self, live: Dict[str, Any]) -> List[Dict[str, Any]]:
        """B1 BRIEFING: your own and your favourite carriers known in the
        jump target's system - or, without a target, in the current one -
        from the journal and the stored Spansh lookup, no request. Cached per
        journal change, favourites file and minute."""
        tgt = self.model.current_target(live or {})
        cur = ({"id64": tgt.get("id64"), "name": tgt.get("name")} if tgt
               else (live or {}).get("system") or {})
        if not (cur.get("id64") or cur.get("name")):
            return []
        try:
            fmt = os.path.getmtime(self.favourites.path)
        except OSError:
            fmt = None
        sig = (self.archive.rev, fmt, cur.get("id64"), cur.get("name"), int(time.time() // 60))

        def build() -> List[Dict[str, Any]]:
            from . import carriers, galaxy
            try:
                own = galaxy.carrier_now(self.archive, self.db)
            except Exception:
                own = None
            try:
                favs = carriers.build_known(self.archive, self.favourites, None, sighted=0)["favourites"]
            except Exception:
                favs = []
            return carriers.carriers_here(cur.get("id64"), cur.get("name"), own, favs)
        try:
            return self.cached("carriers_here", sig, build)
        except Exception:
            return []

    def _with_carrier(self, out: Dict[str, Any], id64: int) -> Dict[str, Any]:
        """Your carrier, when it is in this system or jumping here."""
        from . import galaxy
        try:
            cn = galaxy.carrier_now(self.archive, self.db)
        except Exception:
            cn = None
        if not cn:
            return out
        out = dict(out)
        if cn.get("id") == id64:
            out["carrier"] = {k: cn.get(k) for k in ("name", "callsign", "body_id", "body", "since", "expected")}
        j = cn.get("jump") or {}
        if j.get("id") == id64:
            out["carrier_incoming"] = {"name": cn.get("name"), "callsign": cn.get("callsign"),
                                       "departure": j.get("departure"), "body": j.get("body"),
                                       "body_id": j.get("body_id"), "from": cn.get("system")}
        return out

    def edd_stars(self) -> Any:
        """JUMP PLAN: EDDiscovery's star database through the plugin's reader
        (read only), once calibrated; False when there is none."""
        if self._edd_stars is None:
            from . import jumpplan
            from .config import PLUGIN_PREFIX
            path = (self.cfg._plugin_settings() or {}).get(PLUGIN_PREFIX + "edd_path") or None
            self._edd_stars = jumpplan.edd_stars(path) or False
        return self._edd_stars or None

    def carrier_now(self) -> Optional[Dict[str, Any]]:
        """JUMP PLAN: the own carrier's system, position, tank and load."""
        c = self.archive.carrier()
        if not c:
            return None
        from . import galaxy
        name = (c.get("location") or {}).get("StarSystem")
        su = (c.get("stats") or {}).get("SpaceUsage") or {}
        used = None
        if su.get("TotalCapacity") and su.get("FreeSpace") is not None:
            used = su["TotalCapacity"] - su["FreeSpace"]      # what Spansh calls "used capacity"
        return {"system": name, "pos": galaxy._positions(self.archive, self.db)(name) if name else None,
                "fuel": c.get("fuel"), "load": c.get("load"), "used": used,
                "model": (c.get("tritium_model") or {}).get("model")}

    def current_id64(self) -> Optional[int]:
        """The current system: from the journal, else the last one visited."""
        cur = self.live_state().get("system") or {}
        if cur.get("id64"):
            return int(cur["id64"])
        row = self.db.last_visited()
        return int(row["id64"]) if row is not None and row["id64"] else None

    # ---------------------------------------------------------- watchdog
    WATCH_S = 5.0
    STALL_S = 20.0

    def watchdog_state(self) -> Dict[str, Any]:
        """State of the live reader for /api/health: thread alive, age of the
        last poll, journal rewrites, restarts."""
        lp = getattr(self.live, "last_poll", 0.0) or 0.0
        return {"live_thread": self.live.alive() if hasattr(self.live, "alive") else None,
                "poll_age_s": round(time.time() - lp, 1) if lp else None,
                "journal_rewrites": getattr(self.live, "rewrites", 0),
                "restarts": self.watch_restarts}

    _market_sig: Any = None

    def snapshot_market(self, live: Optional[Dict[str, Any]] = None) -> bool:
        """
        K3: docked at someone else's carrier with its market open - keep what
        it buys and sells (Market.json is overwritten at the next market).
        Same rules as the CARRIER hint (shipview.visiting_carrier): docked,
        the last docking was this market, the market younger than it.
        Checked when Market.json or the journal archive changed.
        """
        jd = self.cfg.journal_dir
        if not jd:
            return False
        try:
            mt = os.path.getmtime(os.path.join(jd, "Market.json"))
        except OSError:
            return False
        self.archive.refresh()
        sig = (mt, self.archive.rev)
        if sig == self._market_sig:
            return False
        from . import carriers, shipview
        evs = self.archive.events()
        own = carriers.own_carrier_ids(evs)["market_id"]
        vis = shipview.visiting_carrier(self.archive, live if live is not None else self.live_state(), jd, own)
        if not vis:
            return False                  # not (yet) docked there: try again on the next change
        self._market_sig = sig
        return self.favourites.note_market(self.archive.commander()[0], vis)

    def watch(self) -> None:
        """Keeps the live link alive: a dead polling thread is started again;
        the state goes to /api/health and every SSE ping."""
        def run() -> None:
            while not self._watch_stop.wait(self.WATCH_S):
                try:
                    if hasattr(self.live, "alive") and not self.live.alive():
                        self.watch_restarts += 1
                        print("FIS watchdog: the journal reader had stopped - restarted (%d)"
                              % self.watch_restarts, flush=True)
                        self.live.restart()
                except Exception:
                    pass
                try:
                    self.snapshot_market()
                except Exception:
                    pass
        threading.Thread(target=run, name="fis-watchdog", daemon=True).start()

    def health(self) -> Dict[str, Any]:
        """The FIS's state for /api/health: version, uptime, database, journal,
        live reader."""
        live = self.live_state()
        return {
            "ok": True, "version": __version__, "uptime_s": round(time.time() - self.started, 1),
            "db": self.db.health(),
            "journal": {"dir": self.cfg.journal_dir, "exists": os.path.isdir(self.cfg.journal_dir),
                        "file": live.get("journal"), "last_event": live.get("last_event"),
                        "errors": self.live.errors},
            "watchdog": self.watchdog_state(),
            "sse_clients": self.hub.clients, "lan": self.cfg.lan,
            "cost_model": self.calib.info,
            "ai_at_runtime": False,
        }


class Handler(BaseHTTPRequestHandler):
    """The FIS's HTTP handler: static files and the JSON API, local only unless
    the home network is switched on (token)."""
    server_version = "SHBOX-FIS/" + __version__
    app: App  # set on the class by make_server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet console
        """Quiet: requests are written only with FIS_DEBUG set."""
        if os.environ.get("FIS_DEBUG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------- E14: home-network brake
    # Devices in the home network (never the game PC itself) get at most
    # RATE_MAX requests per RATE_WINDOW_S - a page load with all its modules
    # stays far below - and after FAIL_MAX wrong tokens within FAIL_WINDOW_S
    # nothing at all for BLOCK_S (guessing the token is pointless anyway,
    # this keeps a stuck or hostile device from hammering the FIS).
    RATE_WINDOW_S, RATE_MAX = 10.0, 120
    FAIL_WINDOW_S, FAIL_MAX, BLOCK_S = 600.0, 20, 600.0
    _brake_lock = threading.Lock()
    _hits: Dict[str, Any] = {}
    _fails: Dict[str, Any] = {}
    _blocked: Dict[str, float] = {}

    def _braked(self) -> Optional[float]:
        """None = go on; else seconds to wait (answer 429)."""
        if self._local():
            return None
        ip = self.client_address[0] if self.client_address else "?"
        now = time.monotonic()
        cls = Handler
        with cls._brake_lock:
            until = cls._blocked.get(ip)
            if until is not None:
                if now < until:
                    return until - now
                cls._blocked.pop(ip, None)
            q = cls._hits.setdefault(ip, [])
            while q and now - q[0] > cls.RATE_WINDOW_S:
                q.pop(0)
            if len(q) >= cls.RATE_MAX:
                return cls.RATE_WINDOW_S - (now - q[0])
            q.append(now)
        return None

    def _note_fail(self) -> None:
        if self._local():
            return
        ip = self.client_address[0] if self.client_address else "?"
        now = time.monotonic()
        cls = Handler
        with cls._brake_lock:
            q = cls._fails.setdefault(ip, [])
            while q and now - q[0] > cls.FAIL_WINDOW_S:
                q.pop(0)
            q.append(now)
            if len(q) >= cls.FAIL_MAX:
                cls._blocked[ip] = now + cls.BLOCK_S
                q.clear()

    def _too_many(self, wait: float) -> None:
        self.close_connection = True
        self._send(429, b'{"error":"too many requests"}', "application/json; charset=utf-8",
                   {"Retry-After": str(max(1, int(wait + 0.999)))})

    # ---------------------------------------------------------- helpers
    def _authorised(self, qs: Dict[str, Any]) -> bool:
        cfg = self.app.cfg
        if not cfg.lan:
            return True
        tok = (qs.get("token") or [""])[0] or self.headers.get("X-FIS-Token", "")
        if not tok and self._local_client():
            # 5.0.1: the token guards the home network; the game PC itself
            # opens the FIS as it does without LAN (the app's start page has
            # no token, a browser restart dropped the page's cookie, an old
            # cookie after a new token). A wrong token given is still wrong.
            return True
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"fis_token=([A-Za-z0-9_\-]+)", cookie)
        if not tok and m:
            tok = m.group(1)
        # A1 (5.0.1): compared as bytes - compare_digest raises TypeError on a
        # str with non-ASCII characters (?token=%C3%BC), which tore the
        # connection down without an answer and without counting the try
        return bool(cfg.token) and hmac.compare_digest(tok.encode("utf-8", "replace"),
                                                       cfg.token.encode("utf-8", "replace"))

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None,
              cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # settings: only from the game PC itself, only from the FIS page
    LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _local(self) -> bool:
        return (self.client_address[0] if self.client_address else "") in self.LOCAL

    def _same_origin(self) -> bool:
        """A page of another site cannot send the custom header without a
        preflight (which we never answer), and its Origin would differ."""
        if self.headers.get("X-FIS-Settings") != "1":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.app.cfg.port
        return origin in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port, "http://[::1]:%d" % port)

    def _settings(self) -> Dict[str, Any]:
        cfg = self.app.cfg
        fw = None
        if cfg.lan:
            try:
                fw = setup.firewall_rule_ok(cfg.port)
            except Exception:
                fw = None
        db = self.app.db
        try:
            cmdrs = [{"fid": c["fid"], "name": c["name"], "carrier": bool(c["carrier"]),
                      "logins": c["logins"], "systems": c["systems"]} for c in db.commanders()]
            auto = db.commander_name(db.suggest_main()) if cmdrs else None
            prev, db.main_setting = db.main_setting, ""
            auto_fid = db.main_fid()
            db.main_setting = prev
        except Exception:
            cmdrs, auto, auto_fid = [], None, None
        return {"language": cfg.language, "open_browser": cfg.open_browser, "lan": cfg.lan,
                "port": cfg.port, "ini": cfg.ini_path, "running_lan": self.app.lan_at_start,
                # on the game PC only: the address for the tablet, with the token
                "lan_urls": setup.lan_urls(cfg.port, cfg.token) if cfg.lan and cfg.token else [],
                "firewall": fw,
                # C1: main commander ("" = automatic: the plugin's choice / suggestion)
                "main_cmdr": cfg.main_cmdr, "commanders": cmdrs,
                "main_auto": db.commander_name(auto_fid) or auto,
                # 4.11: the commander's own limits for UNSOLD DATA (M Cr / systems)
                "unsold": dict(cfg.unsold),
                "unsold_defaults": {k: v[0] for k, v in config_mod.UNSOLD_LIMITS.items()},
                # FG1: the key bindings in SHIP (reads the game's Bindings folder)
                "show_controls": cfg.show_controls,
                # 5.0: the EDDiscovery archive - switch, file, what it added
                "edd_archive": cfg.edd_archive, "edd": self.app.archive.edd_state}

    def do_POST(self) -> None:
        """The few writing calls (carrier favourites and lookups, lost and
        hidden ships, settings, the jump plan): a body of at most 4 KiB (a
        Spansh route to import: 256 KiB), under the request brake; each call
        checks who may write."""
        wait = self._braked()
        if wait is not None:
            self.close_connection = True
            return self._too_many(wait)
        url = urlparse(self.path)
        limit = _POST_LIMITS.get(url.path, 4096)
        # read the (small) body first: answering before it was read makes
        # Windows reset the connection instead of delivering the answer
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        raw = self.rfile.read(n) if 0 < n <= limit else b""
        if n > limit or n < 0:
            self.close_connection = True
            if limit < n <= 65536:
                # a too large body is still read (and dropped) up to 64 KiB, or
                # Windows resets the connection before the 400 arrives
                # (test_losthidden.test_locks failed about once in three runs)
                try:
                    self.rfile.read(n)
                except OSError:
                    pass
            return self._error(400, "bad request")
        fn = _POST_ROUTES.get(url.path)
        if fn is None:
            return self._error(404, "not found")
        try:
            return fn(self, raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return None
        except Exception:
            # A2 (5.0.1): like do_GET - a writing call that fails answers 500
            # instead of dropping the connection; the details stay in the console
            traceback.print_exc()
            try:
                return self._error(500, "internal error - see the FIS console")
            except OSError:
                return None

    def _post_settings(self, raw: bytes) -> None:
        """POST /api/settings: only from the game PC, only from the FIS page.
        Fields that are missing keep their value; nothing is changed when the
        request is refused."""
        if not self._local():
            return self._error(403, "settings only on the game PC")
        if not self._same_origin():
            return self._error(403, "settings only from the FIS page")
        try:
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._error(400, "bad request")
        cfg = self.app.cfg
        if "unsold" in body:
            # 4.11: the commander's own limits for UNSOLD DATA - checked first
            before = dict(cfg.unsold)
            if not isinstance(body["unsold"], dict) or not cfg.set_unsold_limits(body["unsold"]):
                cfg.unsold = before
                return self._error(400, "limits must be whole numbers")
        lang = str(body.get("language", cfg.language)).lower()
        cfg.language = lang if lang in config_mod.LANGUAGES else cfg.language
        cfg.open_browser = bool(body.get("open_browser", cfg.open_browser))
        cfg.show_controls = bool(body.get("show_controls", cfg.show_controls))
        cfg.edd_archive = bool(body.get("edd_archive", cfg.edd_archive))
        self.app.archive.use_edd(cfg.edd_user_db())
        cfg.lan = bool(body.get("lan", cfg.lan))
        if "main_cmdr" in body:
            mc = str(body.get("main_cmdr") or "")
            known = {c["fid"] for c in self.app.db.commanders()}
            if mc == "" or mc in known:
                cfg.main_cmdr = mc
                self.app.db.main_setting = mc
        if cfg.lan:
            cfg.ensure_token(save=False)
        changed = False
        if body.get("new_token") is True and cfg.lan:
            cfg.new_token()
            changed = True
        cfg.setup_done = True
        cfg.save()
        out = self._settings()
        out["saved"] = True
        out["token_changed"] = changed
        out["restart"] = cfg.lan != self.app.lan_at_start
        return self._json(out)

    LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")

    def _page_write_ok(self) -> bool:
        """
        K2: may this request change a favourite? Unlike the settings (which
        can switch the LAN and the token, so game PC only) a star and a note
        are harmless and the tablet beside the screen is where you look at
        CARRIER - so the tablet may, under the same locks as every read plus
        the ones a write needs:
          * the custom header X-FIS-Settings (another site's page cannot send
            it without a preflight, which is never answered),
          * Origin, when sent, equal to this very address,
          * without LAN only a localhost Host (no DNS-rebinding detour),
          * with LAN the token (header or the page's cookie),
          * the E14 brake (do_POST) and small bodies (4 KiB).
        """
        if self.headers.get("X-FIS-Settings") != "1":
            return False
        host = self.headers.get("Host") or ""
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            return False
        if not self.app.cfg.lan:
            return self._local_host()
        return self._authorised({})

    def _local_client(self) -> bool:
        """A request of this PC to this PC: from the loopback address AND
        with a local Host header - a tablet, or this PC asking by its LAN
        address, still needs the token."""
        return self._local() and bool((self.headers.get("Host") or "").strip()) and self._local_host()

    def _local_host(self) -> bool:
        """The Host header names this PC (127.0.0.1, localhost, [::1]). A page
        of another site that re-points its own name at 127.0.0.1 (DNS
        rebinding) still sends its own name and is refused. No Host at all
        (HTTP/1.0 tools) cannot come from a browser and is let through."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return True
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return name in self.LOCAL_HOSTS

    def _post_favourite(self, raw: bytes) -> None:
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "favourites only from the FIS page")
        try:
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._error(400, "bad request")
        from . import carriers
        cs = str(body.get("callsign") or "")
        if not carriers.is_callsign(cs):
            return self._error(400, "bad callsign")
        app = self.app
        fid = app.archive.commander()[0]
        info = carriers.known_carriers(app.archive.events()).get(cs)
        note = body.get("note")
        try:
            fav = app.favourites.set_favourite(fid, cs, bool(body.get("on", True)),
                                               note=None if note is None else str(note), info=info)
        except ValueError as exc:
            return self._error(400, str(exc))
        seen = app.lookup.from_nearby(cs) if fav is not None and not fav.get("online") else None
        if seen:
            app.favourites.set_online(fid, cs, seen)     # H2: starred from the nearby list
        return self._json({"callsign": cs, "favourite": fav is not None, "note": (fav or {}).get("note", "")})

    def _post_learning_reset(self, raw: bytes) -> None:
        """
        SK3, POST /api/learning/reset {"part": "route" | "work" | "fuel" | "value"}:
        forget what a model learnt - measurements before now are left out
        from then on, here and in the plugin at its next start. Same locks
        as a favourite (the FIS page only; with LAN the token).
        """
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "resets only from the FIS page")
        try:
            body = json.loads(raw.decode("utf-8"))
            part = str(body.get("part") or "") if isinstance(body, dict) else ""
        except (ValueError, UnicodeDecodeError):
            part = ""
        app = self.app
        lr = app.model.plugin().learnreset
        if lr is None or part not in lr.PARTS:
            return self._error(400, "bad request")
        now = time.time()
        ship = app.live.reset_fuel(now) if part == "fuel" else None
        if part == "fuel" and ship is None:
            return self._error(409, "no ship known yet")
        try:
            lr.mark(app.learn_reset_path, part, now, ship=ship)
        except (OSError, ValueError):
            return self._error(500, "could not write the reset")
        if part != "fuel":
            threading.Thread(target=app.calib.run_once, name="fis-calib", daemon=True).start()
        return self._json({"part": part, "since": now})

    def _post_unsold_sold(self, raw: bytes) -> None:
        """
        SM1, POST /api/unsold/sold {"parts": ["explo", "bio"], "ts": null}:
        the game logged no sale, so the commander marks their data as sold -
        what was scanned before ts (default now; never in the future) counts
        as sold, here and in the plugin. Only the FIS's learn_reset.json
        changes. Same locks as a favourite (the FIS page only; with LAN the
        token).
        """
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "only from the FIS page")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = None
        app = self.app
        lr = app.model.plugin().learnreset
        now = time.time()
        parts = body.get("parts", ["explo", "bio"]) if isinstance(body, dict) else None
        ts = body.get("ts") if isinstance(body, dict) else None
        if (lr is None or not isinstance(parts, list) or not parts
                or any(p not in lr.SOLD_PARTS for p in parts)
                or (ts is not None and (not isinstance(ts, (int, float)) or isinstance(ts, bool)
                                        or not 0 < ts <= now))):
            return self._error(400, "bad request")
        fid = app.archive.commander()[0]
        if not fid:
            return self._error(409, "no commander known yet")
        ts = now if ts is None else float(ts)
        try:
            lr.mark_sold(app.learn_reset_path, fid, ts, tuple(parts))
        except (OSError, ValueError):
            return self._error(500, "could not write the mark")
        return self._json({"parts": parts, "ts": ts})

    def _post_lost_hidden(self, raw: bytes) -> None:
        """SHIP -> LOST DATA: hide crash losses from the list, or show them
        all again. Only the FIS's own lost_hidden.json changes - the plugin
        database stays read-only, the tasks stay planned.
          {"hide": [{"id64": n, "what": null | "scan" | "map" | "bio:<species>"}]}
          {"cap": 100 | 250 | 500 | 1000}   every listed system farther away
          {"reset": true}"""
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "only from the FIS page")
        try:
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._error(400, "bad request")
        app = self.app
        fid = app.archive.commander()[0]
        store = app.lost_hidden
        if body.get("reset") is True:
            return self._json({"shown": store.reset(fid)})
        try:
            lost = app.db.lost_summary(fid)
        except Exception:
            lost = []
        if "cap" in body:
            items = self._lost_beyond(body, lost, store.get(fid))
        else:
            items = self._lost_listed(body)
        if items is None:
            return None                       # the error is sent
        try:
            n = store.hide(fid, items, lost)
        except ValueError as exc:
            return self._error(400, str(exc))
        return self._json({"hidden": n})

    def _lost_beyond(self, body: Dict[str, Any], lost: Any, hidden: Any
                     ) -> Optional[List[Tuple[int, Optional[str]]]]:
        """{"cap": ly}: every listed system farther away; None after an error."""
        from . import losthidden
        if body["cap"] not in losthidden.CAPS_LY or isinstance(body["cap"], bool):
            self._error(400, "bad cap")
            return None
        pos = (self.app.live_state().get("system") or {}).get("pos")
        if not pos:
            self._error(409, "position unknown")
            return None
        vis, _ = losthidden.apply(lost, hidden, pos)
        return [(s["id64"], None) for s in losthidden.beyond(vis, body["cap"])]

    def _lost_listed(self, body: Dict[str, Any]) -> Optional[List[Tuple[int, Optional[str]]]]:
        """{"hide": [...]}: at most 50 entries, each checked; None after an error."""
        from . import losthidden
        items: List[Tuple[int, Optional[str]]] = []
        hide = body.get("hide")
        if not isinstance(hide, list) or not hide or len(hide) > 50:
            self._error(400, "bad request")
            return None
        for h in hide:
            if not isinstance(h, dict) or not isinstance(h.get("id64"), int) \
                    or isinstance(h.get("id64"), bool) or not losthidden.valid_what(h.get("what")):
                self._error(400, "bad entry")
                return None
            items.append((h["id64"], h.get("what")))
        return items

    def _post_lookup(self, raw: bytes) -> None:
        """K5: one favourite's position at Spansh - on a click, cached 6 h."""
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "lookups only from the FIS page")
        try:
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._error(400, "bad request")
        from . import carriers
        cs = str(body.get("callsign") or "")
        if not carriers.is_callsign(cs):
            return self._error(400, "bad callsign")
        app = self.app
        fid = app.archive.commander()[0]
        fav = app.favourites.get(fid)["favourites"].get(cs)
        if not fav:
            return self._error(400, "only favourites are looked up")
        hit = app.lookup.cached(fav)
        if hit:
            return self._json(dict(hit, callsign=cs, cached=True))
        res = app.lookup.lookup(cs)
        if res.get("error"):
            return self._json(dict(res, callsign=cs), 503 if res["error"] != "offline" else 409)
        app.favourites.set_online(fid, cs, res)
        return self._json(dict(res, callsign=cs, cached=False))

    def _body(self, raw: bytes) -> Optional[Dict[str, Any]]:
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return body if isinstance(body, dict) else None

    def _post_jumpplan(self, raw: bytes) -> None:
        """JUMP PLAN: plan the carrier's jumps to a target (name or id64,
        optionally a body) - from your own data, checked and extended with
        EDDiscovery's star database. Nothing goes online."""
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "plans only from the FIS page")
        body = self._body(raw)
        if body is None:
            return self._error(400, "bad request")
        from . import jumpplan
        app = self.app
        car = app.carrier_now()
        if not car or not car.get("pos"):
            return self._error(409, "carrier position unknown")
        edd = app.edd_stars()
        own = jumpplan.own_stars(app.db, app.archive.events())
        permits = edd.permits() if edd else set()
        own.drop(permits)                    # a carrier cannot go to a permit-locked system
        try:
            id64 = int(body["id64"]) if body.get("id64") else None
        except (TypeError, ValueError):
            return self._error(400, "bad id64")
        target = jumpplan.resolve(own, edd, name=str(body.get("name") or "")[:80] or None, id64=id64)
        if target is None:
            return self._json({"error": "target unknown", "spansh": True}, 404)
        if target["name"].lower() == (car["system"] or "").lower():
            return self._json({"ok": False, "here": True, "spansh": False})
        bid = body.get("body_id")
        plan = jumpplan.make_plan({"name": car["system"], "pos": car["pos"]}, target, own, edd, time.time(),
                                  body=str(body.get("body") or "")[:80] or None,
                                  body_id=bid if isinstance(bid, int) else None)
        plan["target"]["permit"] = bool(target.get("id64") and int(target["id64"]) in permits)
        if plan["hops"]:
            app.jumpplans.set_plan(app.archive.commander()[0], plan)
        return self._json({"ok": bool(plan["hops"]), "plan": plan, "spansh": not plan["hops"]})

    def _post_jumpplan_import(self, raw: bytes) -> None:
        """JUMP PLAN: a route the commander computed at Spansh (its JSON or
        CSV export, chosen or pasted in the page) becomes the plan. The FIS
        reads no file itself and asks nothing online."""
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "plans only from the FIS page")
        body = self._body(raw)
        from . import jumpplan
        jumps = jumpplan.parse_spansh(str((body or {}).get("text") or ""))
        if not jumps:
            return self._error(400, "not a Spansh fleet carrier route (JSON or CSV)")
        app = self.app
        own = jumpplan.own_stars(app.db, app.archive.events())
        plan = jumpplan.spansh_plan(jumps, own, app.edd_stars(), time.time())
        if plan is None:
            return self._error(400, "the route has no jump")
        app.jumpplans.set_plan(app.archive.commander()[0], plan)
        car = app.carrier_now() or {}
        return self._json({"ok": True, "plan": plan,
                           "other_start": (car.get("system") or "").lower() != plan["start"]["name"].lower()})

    def _post_jumpplan_full(self, raw: bytes) -> None:
        """JUMP PLAN: the target is full - with "report" the commander's
        report is kept for learning (a system fills and empties within
        minutes: a hint, never a rule); always the alternatives: other bodies
        of the system, then systems near it within a laden jump of a
        transporter on board, reachable from the jump before the target."""
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "plans only from the FIS page")
        body = self._body(raw) or {}
        from . import jumpplan
        app = self.app
        fid = app.archive.commander()[0]
        saved = app.jumpplans.get(fid)
        plan = saved["plan"]
        if not plan or not plan.get("hops") or not plan["target"].get("pos"):
            return self._error(409, "no plan with a target position")
        tgt, now, evs = plan["target"], time.time(), app.archive.events()
        sight = jumpplan.sightings(evs)
        if body.get("report"):
            app.jumpplans.report_full(fid, {"system": tgt["name"], "id64": tgt.get("id64"), "body": tgt.get("body"),
                                            "ts": now, "seen": jumpplan.seen_at(sight, tgt.get("id64"), now)})
        ships = jumpplan.transporters(app.archive.fleet()["ships"], jumpplan.laden_seen(evs))
        pick = next((x for x in ships if x["id"] == body.get("ship")), ships[0] if ships else None)
        laden = pick["laden"] if pick else jumpplan.DEFAULT_LADEN
        hops = plan["hops"]
        before = hops[-2]["pos"] if len(hops) > 1 and hops[-2].get("pos") else plan["start"]["pos"]
        own = jumpplan.own_stars(app.db, evs)
        if app.edd_stars():
            own.drop(app.edd_stars().permits())
        finders = [own] + ([app.edd_stars()] if app.edd_stars() else [])
        avoid = [r["system"] for r in app.jumpplans.get(fid)["full"] if now - (r.get("ts") or 0) <= jumpplan.FULL_FRESH]
        alts = jumpplan.alternatives(tgt, before, finders, laden, bool(body.get("fewest", True)), avoid, sight, now)
        bodies = []
        if tgt.get("id64") and app.db.exists:
            bodies = [b["name"] for b in app.db.bodies_of(int(tgt["id64"])) if b["name"] != tgt.get("body")][:8]
        return self._json({"alternatives": alts, "bodies": bodies, "ship": pick, "laden": laden,
                           "fewest": bool(body.get("fewest", True)), "reported": bool(body.get("report"))})

    def _post_jumpplan_online(self, raw: bytes = b"") -> None:
        """JUMP PLAN: the carriers Spansh knows in the target - only in the
        bubble, only on a click, through the same gateway, cache and daily
        cap as "carriers near me" (online.CarrierLookup.nearby)."""
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "lookups only from the FIS page")
        from . import jumpplan
        plan = self.app.jumpplans.get(self.app.archive.commander()[0])["plan"]
        tgt = (plan or {}).get("target") or {}
        if not tgt.get("pos") or not jumpplan.in_bubble(tgt["pos"]):
            return self._error(409, "only for targets in the bubble")
        res = self.app.lookup.nearby(tgt["pos"])
        if res.get("error"):
            return self._json(res, 503 if res["error"] != "offline" else 409)
        return self._json(jumpplan.carriers_in(res, tgt))

    def _post_jumpplan_clear(self, raw: bytes = b"") -> None:
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "plans only from the FIS page")
        self.app.jumpplans.set_plan(self.app.archive.commander()[0], None)
        return self._json({"ok": True})

    def _post_nearby(self, raw: bytes = b"") -> None:
        """H2: carriers near the commander at Spansh - on a click only, one
        request per region and day (online.CarrierLookup.nearby)."""
        if not self._page_write_ok():
            self._note_fail()
            return self._error(403, "lookups only from the FIS page")
        from .live import star_pos
        pos = star_pos(((self.app.live_state() or {}).get("system") or {}).get("pos"))
        if pos is None:
            return self._error(409, "position unknown - jump once or open the galaxy map")
        # one request up to 5000 ly everywhere: within 100 ly as ever, and the
        # rescue list when nothing is that close (a border "1000 ly from Sol"
        # took empty space 670 ly out for the bubble - user 19.11.)
        res = self.app.lookup.nearby(pos, deep=True)
        if res.get("error"):
            return self._json(res, 503 if res["error"] != "offline" else 409)
        try:            # what was shown joins KNOWN CARRIERS (user 19.11.)
            self.app.favourites.note_online(self.app.archive.commander()[0],
                                            (res.get("carriers") or []) + (res.get("rescue") or []))
        except OSError:
            pass
        return self._json(res)

    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                          default=str).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    # ------------------------------------------------------------- verbs
    def do_HEAD(self) -> None:
        """As GET (the body is sent the same way)."""
        self.do_GET()

    def do_GET(self) -> None:
        """Static files, the JSON API and the live event stream, under the
        request brake."""
        wait = self._braked()
        if wait is not None:
            return self._too_many(wait)
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if not self.app.cfg.lan and not self._local_host():
            # DNS rebinding: refused, but not counted for the brake - every
            # such request comes from 127.0.0.1, and the brake would then
            # lock out the commander's own browser too
            return self._error(403, "this PC only - open http://127.0.0.1:%d/" % self.app.cfg.port)
        if not self._authorised(qs):
            self._note_fail()
            return self._error(401, "token required")
        path = url.path
        try:
            if path.startswith("/api/"):
                return self._api(path, qs)
            return self._static(path, qs)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return None
        except Exception:
            # N10: the details (paths, names, values) stay in the FIS console;
            # the browser - possibly a tablet in the home network - learns
            # only that something went wrong
            traceback.print_exc()
            try:
                return self._error(500, "internal error - see the FIS console")
            except OSError:
                return None

    def _settings_qr(self, qs: Dict[str, Any]) -> None:
        """The tablet address WITH token as QR code - same rule as the
        settings: only the game PC itself ever sees it."""
        if not self._local():
            return self._error(403, "settings only on the game PC")
        urls = self._settings()["lan_urls"]
        if not urls:
            return self._error(404, "home network is off")
        try:
            i = int((qs.get("i") or ["0"])[0])
        except ValueError:
            i = 0
        text = urls[i] if 0 <= i < len(urls) else urls[0]
        return self._send(200, qr_mod.svg(text).encode("utf-8"), "image/svg+xml; charset=utf-8")

    def _controls(self) -> Dict[str, Any]:
        """FG1: the key bindings - read only while switched on in the settings."""
        if not self.app.cfg.show_controls:
            return {"enabled": False}
        from . import bindings
        st = (self.app.live_state() or {}).get("status") or {}
        return dict(bindings.read(), enabled=True, fire_group=st.get("fire_group"))

    def _api(self, path: str, qs: Dict[str, Any]) -> None:
        """One GET of the JSON API: a fixed path from _GET_ROUTES, a system or a body."""
        route = _GET_ROUTES.get(path)
        if route is not None:
            return route(self, qs)
        app = self.app
        m = app.model
        mm = _RE_SYS.match(path)
        if mm:
            return self._json(app.system(int(mm.group(1))))
        mm = _RE_BODY.match(path)
        if mm:
            out = m.build_body(app.db, int(mm.group(1)), int(mm.group(2)), app.archive, fid=app.fid())
            if out is None:
                return self._error(404, "body not found")
            return self._json(out)
        return self._error(404, "unknown endpoint")

    def _get_health(self, qs: Dict[str, Any]) -> None:
        """The FIS's state: version, uptime, database, journal, live reader."""
        app = self.app
        return self._json(app.health())

    def _get_settings(self, qs: Dict[str, Any]) -> None:
        """The settings page's values - only on the game PC."""
        if not self._local():
            return self._error(403, "settings only on the game PC")
        return self._json(self._settings())

    def _get_settings_qr(self, qs: Dict[str, Any]) -> None:
        """The QR code for a device in the home network."""
        return self._settings_qr(qs)

    def _get_controls(self, qs: Dict[str, Any]) -> None:
        """The key bindings for SHIP, when switched on."""
        return self._json(self._controls())

    def _get_config(self, qs: Dict[str, Any]) -> None:
        """Language and the addresses for other devices, never the token."""
        app = self.app
        # addresses for other devices, never the token (that stays on this PC)
        from . import files
        return self._json({"language": app.cfg.language, "lan": app.cfg.lan,
                           "port": app.cfg.port,
                           "lan_urls": setup.lan_urls(app.cfg.port, "") if app.cfg.lan else [],
                           # 4.12: missing or damaged files (relative names only)
                           "files": files.for_browser()})

    def _get_events(self, qs: Dict[str, Any]) -> None:
        """The live event stream (server-sent events)."""
        return self._sse()

    def _get_live(self, qs: Dict[str, Any]) -> None:
        """The live state."""
        app = self.app
        return self._json(app.live_state())

    def _get_system_current(self, qs: Dict[str, Any]) -> None:
        """The SYSTEM record of the current system."""
        app = self.app
        id64 = app.current_id64()
        if not id64:
            return self._error(404, "no current system yet")
        return self._json(app.system(id64))

    def _get_briefing(self, qs: Dict[str, Any]) -> None:
        """The BRIEFING of the jump target, with the carriers there."""
        app = self.app
        m = app.model
        live = app.live_state()
        out = m.build_briefing(app.db, live, fid=app.fid())
        out["carriers_here"] = app.carriers_here(live)
        # at the jump target when there is one (11.11.: a carrier left
        # behind in the current system says nothing about the next one)
        out["carriers_where"] = "target" if out.get("target") else "here"
        return self._json(out)

    def _get_ship(self, qs: Dict[str, Any]) -> None:
        """The ship's state for the cockpit view."""
        app = self.app
        m = app.model
        return self._json(m.build_ship(app.live_state()))

    def _get_vehicle(self, qs: Dict[str, Any]) -> None:
        """VEHICLE: the SRV's state, tank sizes learnt, synthesis recipes."""
        app = self.app
        m = app.model
        live = app.live_state()
        v = live.get("srv") or {}
        full = v.get("tank_full")
        if full and v.get("type"):              # V1b: a full tank after a refuel synthesis
            app.vehicle_tanks.learn(v["type"], full.get("t"), v.get("name"),
                                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(full.get("ts") or 0)))
        out = m.build_vehicle(live, tanks=app.vehicle_tanks.all())
        try:                                  # V1c: recipes from your own Synthesis events
            from . import synthesis
            out["synthesis"] = synthesis.build_synthesis(app.archive)
        except Exception:
            out["synthesis"] = None
        return self._json(out)

    def _get_surface(self, qs: Dict[str, Any]) -> None:
        """SURFACE of a body (or the current one); on foot with the backpack."""
        app = self.app
        m = app.model
        sid = (qs.get("sys") or [None])[0]
        body = (qs.get("body") or [None])[0]
        out = m.build_surface(app.db, app.live_state(),
                              int(sid) if sid and sid.isdigit() else None, body or None,
                              archive=app.archive)
        if out.get("life"):
            out["backpack"] = m.backpack(app.cfg.journal_dir)     # on foot (M5)
        return self._json(out)

    def _get_atlas_kinds(self, qs: Dict[str, Any]) -> None:
        """The kinds the ATLAS can list for a view."""
        app = self.app
        m = app.model
        return self._json({"view": (qs.get("view") or ["signals"])[0],
                           "kinds": m.build_atlas_kinds(app.db, (qs.get("view") or ["signals"])[0])})

    def _get_atlas(self, qs: Dict[str, Any]) -> None:
        """ATLAS: signals, materials, rings ... nearest first, filtered."""
        app = self.app
        m = app.model
        view = (qs.get("view") or ["signals"])[0]
        kind = (qs.get("kind") or [None])[0] or None
        q = (qs.get("q") or [None])[0] or None
        try:
            limit = max(1, min(300, int((qs.get("limit") or ["60"])[0])))
        except ValueError:
            limit = 60
        try:
            max_ly = float((qs.get("max") or ["0"])[0]) or None
        except ValueError:
            max_ly = None
        near = (app.live_state().get("system") or {}).get("pos")
        return self._json(m.build_atlas(app.db, view, kind, near, limit, q, max_ly))

    def _get_shipstatus(self, qs: Dict[str, Any]) -> None:
        """SHIP: status, modules, fuel, data at risk, ships lost or hidden."""
        app = self.app
        m = app.model
        from . import shipview
        live = app.live_state()
        try:
            live = dict(live, fuel_warning=m._fuel_state(live).warning() if live.get("ship") else None)
        except Exception:
            pass
        out = shipview.build_shipstatus(live, app.archive, app.cfg.journal_dir, app.db,
                                        lost_hidden=app.lost_hidden,
                                        unsold_limits=app.cfg.unsold,
                                        value_since=app._learn_marks().get("value"),
                                        sold_marks=app._sold_marks())
        try:
            from . import synthesis
            out["synthesis"] = synthesis.build_synthesis(app.archive, ship=True)      # V2
        except Exception:
            out["synthesis"] = None
        return self._json(out)

    def _get_nexthop(self, qs: Dict[str, Any]) -> None:
        """NH1: the systems within one jump, best chance of a find first."""
        from . import nexthop
        return self._json(nexthop.build_nexthop(self.app.db, self.app.live_state()))

    def _get_carrier(self, qs: Dict[str, Any]) -> None:
        """CARRIER: the own carrier, its jumps and hold."""
        app = self.app
        from . import shipview
        from . import capi
        return self._json(shipview.build_carrier(app.archive, app.live_state(),
                                                 journal_dir=app.cfg.journal_dir,
                                                 capi_path=capi.path_for(app.cfg.plugin_dir)))

    def _get_jumpplan(self, qs: Dict[str, Any]) -> None:
        """CARRIER > JUMP PLAN: the plan with tritium, time and what is done."""
        app = self.app
        from . import jumpplan, shipview, capi
        car = app.carrier_now()
        hold = shipview.hold_tritium(capi.path_for(app.cfg.plugin_dir), time.time())
        saved = app.jumpplans.get(app.archive.commander()[0])
        out = jumpplan.build(saved["plan"], car, app.archive.own_carrier_events(),
                             int((hold or {}).get("t") or 0), time.time())
        out.update(carrier=car, hold_info=hold, edd=app.edd_stars() is not None,
                   spansh=jumpplan.spansh_help(car, saved["plan"], int((hold or {}).get("t") or 0)))
        plan = saved["plan"]
        if plan and plan.get("hops") and not out.get("arrived"):
            evs = app.archive.events()
            out["full"] = jumpplan.full_estimate(plan["target"], saved["full"],
                                                 jumpplan.arrivals(app.archive.own_carrier_events()),
                                                 jumpplan.sightings(evs), time.time())
            out["transporters"] = jumpplan.transporters(app.archive.fleet()["ships"], jumpplan.laden_seen(evs))
            out["bubble"] = bool(plan["target"].get("pos")) and jumpplan.in_bubble(plan["target"]["pos"])
        return self._json(out)

    def _get_carriers_known(self, qs: Dict[str, Any]) -> None:
        """KNOWN CARRIERS: favourites and carriers seen."""
        app = self.app
        from . import carriers
        return self._json(carriers.build_known(app.archive, app.favourites, app.live_state(), db=app.db))

    def _get_mining_live(self, qs: Dict[str, Any]) -> None:
        """The mining session now."""
        app = self.app
        from . import mining
        return self._json(mining.build_live(app.archive, app.live_state(), app.cfg.journal_dir))

    def _get_mining(self, qs: Dict[str, Any]) -> None:
        """MINING: sessions, hold, limpets, rings."""
        app = self.app
        from . import mining
        from . import capi
        return self._json(mining.build_mining(app.archive, app.db, app.live_state(), app.cfg.journal_dir,
                                              capi_path=capi.path_for(app.cfg.plugin_dir)))

    def _get_ledger(self, qs: Dict[str, Any]) -> None:
        """5.0 GAIN / LOSS of the active commander, per ship, over ?days= (0: all)."""
        app = self.app
        from . import ledger
        try:
            days = float((qs.get("days") or ["0"])[0]) or None
        except ValueError:
            days = None
        app.archive.refresh()
        evs = app.archive.events()
        bal = ((app.live_state() or {}).get("status") or {}).get("balance")
        out = ledger.build_ledger(evs, days, balance_now=bal)
        # B6: the open block - unsold data as UNSOLD DATA values it
        un = app._unsold_now()
        out["open"] = ({"bio": un["bio"]["value"], "bio_count": un["bio"]["count"],
                        "systems": un["exploration"]["systems"], "explo": un["exploration"].get("value")}
                       if un else None)
        names = app.archive.ship_names(evs)
        from .fleet import type_label, upkeep_between
        for s in out["ships"]:
            s["type_name"] = type_label(names, s.get("type"))      # PL2: readable without a localised name
        for d in out["deaths"]:
            d["type_name"] = type_label(names, d.get("type"))
        # PL2: the carrier's upkeep over the period - an estimate from its balance
        car = app.archive.carrier()
        if car:
            out["carrier"]["upkeep"] = upkeep_between(car.get("balances") or [], car.get("transfers") or [],
                                                      out.get("since"))
        # CT2: the carrier's money - Frontier's figures and the journal's
        from . import capi, carriermoney
        out["carrier"]["money"] = carriermoney.build(capi.path_for(app.cfg.plugin_dir), car, evs, out.get("since"))
        return self._json(out)

    def _get_statement(self, qs: Dict[str, Any]) -> None:
        """5.0 GV1: GAIN / LOSS as an annual statement - income statement per
        week, month and year, balance sheet, segments, outlook."""
        app = self.app
        from . import capi, carriermoney, ledger, statement
        app.archive.refresh()
        evs = app.archive.events()
        bal = ((app.live_state() or {}).get("status") or {}).get("balance")
        led = ledger.build_ledger(evs, None, balance_now=bal)
        un = app._unsold_now()
        open_ = {"bio": un["bio"]["value"], "explo": un["exploration"].get("value")} if un else None
        return self._json(statement.build(led, app.archive.carrier(),
                                          carriermoney.frontier(capi.path_for(app.cfg.plugin_dir)),
                                          app.archive.fleet()["ships"], evs, bal, open_))

    def _get_trade(self, qs: Dict[str, Any]) -> None:
        """TRADE (HD1): your sale prices per commodity, the galactic mean and
        - docked - what this market pays."""
        app = self.app
        from . import trade
        app.archive.refresh()
        return self._json(trade.build_trade(app.archive, app.live_state(), app.cfg.journal_dir,
                                            os.path.join(os.path.dirname(app.cfg.ini_path), "market_means.json"),
                                            edd_path=app.archive.edd_source()))

    def _get_statistics(self, qs: Dict[str, Any]) -> None:
        """STATISTICS, with what the FIS has learnt so far."""
        app = self.app
        from . import stats
        try:
            days = float((qs.get("days") or ["0"])[0]) or None
        except ValueError:
            days = None
        out = stats.build_statistics(app.archive, days)
        try:
            # CT2: the carrier's money over the period
            from . import capi, carriermoney
            out["carrier_money"] = carriermoney.build(capi.path_for(app.cfg.plugin_dir), app.archive.carrier(),
                                                      app.archive.events(),
                                                      time.time() - days * 86400 if days else None)
        except Exception:
            out["carrier_money"] = None
        try:
            from . import learn
            # L4: what the FIS has learnt from your own data so far
            out["learning"] = learn.learning_status(app.archive, app.db)
            # SK3: the route, work and fuel models with what they rest on
            out["learning"]["models"] = learn.model_status(app.calib.info, app.live_state(),
                                                           app.calib.model)
            un = app._unsold_now()
            out["learning"]["models"]["value"] = un["exploration"].get("calibration") if un else None
            out["learning"]["finds"] = learn.find_odds(app.db)       # FX3: predicted finds vs scans
            out["learning"]["forecast"] = app.forecasts()               # B-24
            out["learning"]["scoop"] = app.scoop()                      # B-15
            out["bio_rates"] = app.cached("bio_rates", (app.db.mtime(), app.archive.rev),    # BQ1, EA2
                                          lambda: learn.bio_rates(app.db, extra=app.archive_planets()))
            from .shipview import _bodyvalue
            out["sessions"] = stats.play_sessions(app.archive.events(), _bodyvalue(), app.archive.organic_values())
            from . import systime        # own-4: time per system against the route's estimate
            evs = app.archive.events()
            out["systime"] = app.cached("systime", (len(evs), evs[-1].get("timestamp") if evs else None,
                                                    app.db.mtime()),
                                        lambda: systime.build(evs, app.db, app.archive.commander()[0]))
            out["learning"]["reality"] = app.reality(out)                # V0: every model against reality
        except Exception:
            out["learning"] = None
        return self._json(out)

    def _get_galaxy(self, qs: Dict[str, Any]) -> None:
        """GALAXY layers for a mass code and period (cached while nothing changes)."""
        app = self.app
        from . import galaxy
        try:
            mc = int((qs.get("mc") or [""])[0])
        except ValueError:
            mc = None
        try:
            days = float((qs.get("days") or ["0"])[0]) or None
        except ValueError:
            days = None
        live = app.live_state()
        pos = tuple((live.get("system") or {}).get("pos") or ())
        nav = len(live.get("navroute") or [])
        app.archive.refresh()
        sig = (app.db.mtime(), app.archive.rev, pos, nav, mc, days)
        out = app.cached("galaxy:%s:%s" % (mc, days), sig,
                         lambda: galaxy.build_galaxy(app.db, app.archive, live, mc, days))
        return self._json(dict(out, fav_carriers=app.favourite_carriers_at()))

    def _get_survey_export(self, qs: Dict[str, Any]) -> None:
        """The survey sphere as a CSV or JSON file."""
        app = self.app
        m = app.model
        # M14: the survey sphere as a file - CSV or JSON
        fmt = "json" if (qs.get("format") or ["csv"])[0] == "json" else "csv"
        res = m.survey_export(app.db, fmt)
        day = time.strftime("%Y-%m-%d")
        if fmt == "json":
            body = json.dumps(res, ensure_ascii=False, indent=1, default=str).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            body = ("\ufeff" + res).encode("utf-8")   # BOM: Excel reads UTF-8 then
            ctype = "text/csv; charset=utf-8"
        return self._send(200, body, ctype, {
            "Content-Disposition": 'attachment; filename="shbox-survey-%s.%s"' % (day, fmt)})

    def _get_survey(self, qs: Dict[str, Any]) -> None:
        """The survey state (cached while the database does not change),
        with B-24's forecast of the sphere's rest."""
        app = self.app
        m = app.model
        out = dict(app.cached("survey", app.db.mtime(), lambda: m.build_survey(app.db)))
        try:
            out["forecast"] = self.app.sphere_forecast(out)
        except Exception:
            out["forecast"] = None
        return self._json(out)

    PING_S = 15.0                            # quiet game: a ping at least this often

    def _sse(self) -> None:
        q = self.app.hub.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self._sse_write("snapshot", self.app.live_state())
            while True:
                try:
                    ev, data = q.get(timeout=self.PING_S)
                    self._sse_write(ev, data)
                except queue.Empty:
                    # a named event: the page's watchdog sees it (comments it would not)
                    self._sse_write("ping", dict(self.app.watchdog_state(), t=time.time()))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(q)
            self.close_connection = True

    def _sse_write(self, event: str, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        self.wfile.write(("event: %s\ndata: %s\n\n" % (event, payload)).encode("utf-8"))
        self.wfile.flush()

    # what the web folder holds; anything else is served as plain bytes
    STATIC_TYPES = {
        ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        ".woff2": "font/woff2", ".webmanifest": "application/manifest+json",
    }

    def _static(self, path: str, qs: Dict[str, Any]) -> None:
        if path in ("", "/"):
            path = "/index.html"
        root = os.path.realpath(self.app.web_dir)
        # normalise first, then require the result to lie inside the web
        # folder - and once more after resolving links
        full = os.path.normpath(os.path.join(root, path.lstrip("/").replace("/", os.sep)))
        if not full.startswith(root + os.sep):
            return self._error(404, "not found")
        full = os.path.realpath(full)
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self._error(404, "not found")
        # the browser may keep the pages and modules, but asks every time
        # whether they changed (ETag -> 304): an update shows at once, and a
        # tablet on Wi-Fi no longer fetches 1.9 MB (Three.js) per page load -
        # the 3D view gave up after 8 s there (11.11.)
        st = os.stat(full)
        etag = '"%x-%x"' % (int(st.st_mtime_ns // 1000), st.st_size)
        cookie = self._token_cookie(qs)
        if etag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            if cookie:
                # 5.0.1: also here - a page served from the cache otherwise
                # left its modules without the cookie (bare page, 401s)
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            return
        with open(full, "rb") as fh:
            body = fh.read()
        ctype = self.STATIC_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        extra = {"ETag": etag}
        if cookie:
            extra["Set-Cookie"] = cookie
        self._send(200, body, ctype, extra, cache="no-cache")

    COOKIE_DAYS = 30

    def _token_cookie(self, qs: Dict[str, Any]) -> str:
        """The cookie that remembers the token for the module and API
        requests of this page - the stored token (the request's was checked
        equal to it; nothing a request sends ends up in a header), kept
        across browser restarts (5.0.1)."""
        cfg = self.app.cfg
        tok = (qs.get("token") or [""])[0]
        if not (cfg.lan and cfg.token and tok and hmac.compare_digest(tok, cfg.token)):
            return ""     # this PC passes without a token - a wrong one sets nothing
        return "fis_token=%s; Path=/; Max-Age=%d; SameSite=Strict; HttpOnly" % (
            cfg.token, self.COOKIE_DAYS * 86400)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


# POST path -> its Handler method (5.0 JUMP PLAN: was a chain in do_POST)
_POST_ROUTES = {
    "/api/carriers/favourite": Handler._post_favourite,
    "/api/carriers/lookup": Handler._post_lookup,
    "/api/carriers/nearby": Handler._post_nearby,
    "/api/jumpplan/plan": Handler._post_jumpplan,
    "/api/jumpplan/clear": Handler._post_jumpplan_clear,
    "/api/jumpplan/import": Handler._post_jumpplan_import,
    "/api/jumpplan/full": Handler._post_jumpplan_full,
    "/api/jumpplan/online": Handler._post_jumpplan_online,
    "/api/ship/lost_hidden": Handler._post_lost_hidden,
    "/api/unsold/sold": Handler._post_unsold_sold,
    "/api/learning/reset": Handler._post_learning_reset,
    "/api/settings": Handler._post_settings,
}
# bodies larger than 4 KiB: only a Spansh route to import
_POST_LIMITS = {"/api/jumpplan/import": 256 * 1024}

# GET path -> its Handler method (4.12: was one chain of 48)
_GET_ROUTES = {
    "/api/health": Handler._get_health,
    "/api/settings": Handler._get_settings,
    "/api/settings/qr": Handler._get_settings_qr,
    "/api/controls": Handler._get_controls,
    "/api/config": Handler._get_config,
    "/api/events": Handler._get_events,
    "/api/live": Handler._get_live,
    "/api/system/current": Handler._get_system_current,
    "/api/briefing": Handler._get_briefing,
    "/api/ship": Handler._get_ship,
    "/api/vehicle": Handler._get_vehicle,
    "/api/surface": Handler._get_surface,
    "/api/atlas/kinds": Handler._get_atlas_kinds,
    "/api/atlas": Handler._get_atlas,
    "/api/shipstatus": Handler._get_shipstatus,
    "/api/carrier": Handler._get_carrier,
    "/api/carriers/known": Handler._get_carriers_known,
    "/api/jumpplan": Handler._get_jumpplan,
    "/api/mining/live": Handler._get_mining_live,
    "/api/mining": Handler._get_mining,
    "/api/statistics": Handler._get_statistics,
    "/api/ledger": Handler._get_ledger,
    "/api/ledger/statement": Handler._get_statement,
    "/api/trade": Handler._get_trade,
    "/api/galaxy": Handler._get_galaxy,
    "/api/nexthop": Handler._get_nexthop,
    "/api/survey/export": Handler._get_survey_export,
    "/api/survey": Handler._get_survey,
}


def make_server(app: App, host: Optional[str] = None, port: Optional[int] = None) -> ThreadingHTTPServer:
    """The HTTP server for an app, on the configured host and port."""
    handler = type("FISHandler", (Handler,), {"app": app})
    return _Server((host or app.cfg.host, app.cfg.port if port is None else port), handler)


def main(argv: Optional[list] = None) -> int:
    """Start the FIS: settings (first start asks), database, live reader,
    watchers and the HTTP server, until Ctrl+C."""
    # parameters are for development and tests - users start start_fis.bat,
    # the first start asks and remembers the answers in fis.ini
    ap = argparse.ArgumentParser(prog="fis", description="SHBOX FIS - flight information system")
    ap.add_argument("--lan", action="store_true", help="serve the home network (0.0.0.0, token required)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--ini", default=None, help="path of fis.ini")
    ap.add_argument("--db", default=None, help="database (default: the plugin's)")
    ap.add_argument("--journal", default=None, help="journal folder")
    ap.add_argument("--open", action="store_true", help="open the browser")
    ap.add_argument("--setup", action="store_true", help="ask the first-start questions again (fis_settings.bat)")
    ap.add_argument("--no-setup", action="store_true", help="never ask (tests, services)")
    a = ap.parse_args(argv)

    cfg = Config().load(a.ini)
    asked = False
    if not a.no_setup and (a.setup or not cfg.setup_done) and setup.interactive_console():
        # first start (or fis_settings.bat): ask once, remember in fis.ini
        setup.run_setup(cfg)
        asked = True
    if a.lan:
        cfg.lan, cfg.host = True, "0.0.0.0"
    if a.port:
        cfg.port = a.port
    if a.db:
        cfg.db_path = a.db
    if a.journal:
        cfg.journal_dir = a.journal
    if cfg.lan and cfg.ensure_token():
        print("LAN token created and stored in fis.ini.")
    if cfg.lan and not a.no_setup:
        # firewall rule (asked once, only with the user's yes) + where to find the page
        setup.check_lan(cfg, interactive=setup.interactive_console()
                        and (asked or cfg.firewall != "declined"))
    if a.setup:
        print(setup.msg(cfg.language, "saved") % cfg.ini_path)

    app = App(cfg)
    try:
        srv = make_server(app)
    except OSError as e:
        # typical: FIS already running (second double-click) or port taken
        app.stop()
        print("Port %d is in use (%s)." % (cfg.port, e.strerror or e))
        print("Is the FIS already running? Then just open http://127.0.0.1:%d/ -"
              " otherwise pick another port with fis_settings.bat." % cfg.port)
        return 2
    app.live.start()
    app.watch()
    app.watch_db()
    # measure route times from the journals in the background (like the plugin)
    threading.Thread(target=app.calib.run_once, name="fis-calib", daemon=True).start()
    # R1: the Kepler reality check (seconds) ahead of the first STATISTICS visit
    threading.Thread(target=lambda: app.kepler_check(wait=True), name="fis-kepler0", daemon=True).start()
    # ship / fleet / carrier history: one scan of all journals in the background
    threading.Thread(target=lambda: app.archive.refresh(force=True), name="fis-archive",
                     daemon=True).start()
    local = "http://127.0.0.1:%d/" % cfg.port
    print("SHBOX FIS %s - reads only, writes nothing, no AI at runtime." % __version__)
    print("Database  : %s (%s)" % (cfg.db_path, "ok" if app.db.exists else "MISSING"))
    print("Journal   : %s" % cfg.journal_dir)
    if cfg.lan:
        local += "?token=" + cfg.token
    print("This PC   : %s" % local)
    print("Settings  : fis_settings.bat    Stop: Ctrl+C")
    if a.open or (cfg.open_browser and not a.no_setup and not a.setup):
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(local)).start()
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        app.live.stop()
        srv.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
