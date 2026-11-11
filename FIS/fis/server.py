# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""HTTP server: static web files, JSON API and Server-Sent Events.

Standard library only (ThreadingHTTPServer). Default bind 127.0.0.1; with
--lan it binds 0.0.0.0 and every request needs the token from fis.ini, as
`?token=...` or header `X-FIS-Token`.
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
        self.hub = live.hub if live else Hub()
        self.live = live or LiveTracker(cfg.journal_dir, self.hub, cfg.poll_s)
        self.web_dir = web_dir
        self.started = time.time()
        self._cache: Dict[str, Tuple[Any, Any]] = {}
        self._cache_lock = threading.Lock()
        self._stop = threading.Event()
        from .fleet import Archive
        self.archive = Archive(cfg.journal_dir)
        from .favourites import FavouriteStore
        # personal (K2): next to fis.ini, never in the repository
        self.favourites = FavouriteStore(os.path.join(os.path.dirname(cfg.ini_path), "favourites.json"))
        # K5: the one online lookup of the FIS (on a click, through the plugin's gateway)
        from .online import CarrierLookup
        self.lookup = CarrierLookup(__version__, calls_today=self._calls_today,
                                    offline=self._plugin_offline)
        from .calib import Calibrator
        self.calib = Calibrator(cfg.journal_dir, model.plugin().sysroute, self._leg_ls)

    def _leg_ls(self, id64: int, a: str, b: str, at: float) -> Optional[float]:
        """Distance body a -> body b at time `at`, from the plugin's orbits."""
        try:
            return self.model.plugin().sysroute.leg_distance_ls(self.db.bodies_of(int(id64)),
                                                           a, b, at=at)
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
        self._stop.set()

    def live_state(self) -> Dict[str, Any]:
        return self.live.snapshot()

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
    def system(self, id64: int) -> Dict[str, Any]:
        live = self.live_state()
        fx = live.get("last_fix") or {}
        cur = live.get("system") or {}
        # positions move along their orbits; a 30 s bucket is plenty
        sig = (self.db.mtime(), int(time.time() // 30), cur.get("id64"),
               fx.get("body_id"), fx.get("body"),
               int((fx.get("ts") or 0) // 60), id(self.calib.model),
               tuple(self.cfg.filters), self.cfg.skip_arrival, self.archive.rev)
        self.calib.maybe_refresh()
        cm, om = self.calib.model, self.calib.order_model
        out = self.cached("sys:%d" % id64, sig, lambda: self.model.build_system(
            self.db, id64, live, self.cfg.filters, cost_model=cm, order_model=om,
            skip_arrival=self.cfg.skip_arrival, archive=self.archive))
        return self._with_favourites(self._with_carrier(out, id64))

    def _with_favourites(self, out: Dict[str, Any]) -> Dict[str, Any]:
        """K4: a star at your favourite carriers among the points of interest."""
        if not out.get("poi"):
            return out
        try:
            from .carriers import mark_favourite_pois
            favs = self.favourites.get(self.archive.commander()[0])["favourites"]
        except Exception:
            return out
        if not favs:
            return out
        return dict(out, poi=mark_favourite_pois(out["poi"], favs))

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
        current system - from the journal and the stored Spansh lookup, no
        request. Cached per journal change, favourites file and minute."""
        cur = (live or {}).get("system") or {}
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

    def current_id64(self) -> Optional[int]:
        cur = self.live_state().get("system") or {}
        if cur.get("id64"):
            return int(cur["id64"])
        row = self.db.last_visited()
        return int(row["id64"]) if row is not None and row["id64"] else None

    # ---------------------------------------------------------- watchdog
    WATCH_S = 5.0
    STALL_S = 20.0

    def watchdog_state(self) -> Dict[str, Any]:
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
    server_version = "SHBOX-FIS/" + __version__
    app: App  # set on the class by make_server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet console
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
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"fis_token=([A-Za-z0-9_\-]+)", cookie)
        if not tok and m:
            tok = m.group(1)
        return bool(cfg.token) and hmac.compare_digest(tok, cfg.token)

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
        return {"language": cfg.language, "open_browser": cfg.open_browser, "lan": cfg.lan,
                "port": cfg.port, "ini": cfg.ini_path, "running_lan": self.app.lan_at_start,
                # on the game PC only: the address for the tablet, with the token
                "lan_urls": setup.lan_urls(cfg.port, cfg.token) if cfg.lan and cfg.token else [],
                "firewall": fw}

    def do_POST(self) -> None:
        wait = self._braked()
        if wait is not None:
            self.close_connection = True
            return self._too_many(wait)
        url = urlparse(self.path)
        # read the (small) body first: answering before it was read makes
        # Windows reset the connection instead of delivering the answer
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        raw = self.rfile.read(n) if 0 < n <= 4096 else b""
        if n > 4096 or n < 0:
            self.close_connection = True
            return self._error(400, "bad request")
        if url.path == "/api/carriers/favourite":
            return self._post_favourite(raw)
        if url.path == "/api/carriers/lookup":
            return self._post_lookup(raw)
        if url.path != "/api/settings":
            return self._error(404, "not found")
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
        lang = str(body.get("language", cfg.language)).lower()
        cfg.language = lang if lang in config_mod.LANGUAGES else cfg.language
        cfg.open_browser = bool(body.get("open_browser", cfg.open_browser))
        cfg.lan = bool(body.get("lan", cfg.lan))
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
            name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
            return name in self.LOCAL_HOSTS
        return self._authorised({})

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
        return self._json({"callsign": cs, "favourite": fav is not None, "note": (fav or {}).get("note", "")})

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

    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                          default=str).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    # ------------------------------------------------------------- verbs
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        wait = self._braked()
        if wait is not None:
            return self._too_many(wait)
        url = urlparse(self.path)
        qs = parse_qs(url.query)
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
        except Exception as exc:
            traceback.print_exc()
            try:
                return self._error(500, "%s: %s" % (type(exc).__name__, exc))
            except OSError:
                return None

    def _api(self, path: str, qs: Dict[str, Any]) -> None:
        app = self.app
        m = app.model
        if path == "/api/health":
            return self._json(app.health())
        if path == "/api/settings":
            if not self._local():
                return self._error(403, "settings only on the game PC")
            return self._json(self._settings())
        if path == "/api/settings/qr":
            # the tablet address WITH token as QR code - same rule as the
            # settings: only the game PC itself ever sees it
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
        if path == "/api/config":
            # addresses for other devices, never the token (that stays on this PC)
            return self._json({"language": app.cfg.language, "lan": app.cfg.lan,
                               "port": app.cfg.port,
                               "lan_urls": setup.lan_urls(app.cfg.port, "") if app.cfg.lan else []})
        if path == "/api/events":
            return self._sse()
        if path == "/api/live":
            return self._json(app.live_state())
        if path == "/api/system/current":
            id64 = app.current_id64()
            if not id64:
                return self._error(404, "no current system yet")
            return self._json(app.system(id64))
        mm = _RE_SYS.match(path)
        if mm:
            return self._json(app.system(int(mm.group(1))))
        mm = _RE_BODY.match(path)
        if mm:
            out = m.build_body(app.db, int(mm.group(1)), int(mm.group(2)), app.archive)
            if out is None:
                return self._error(404, "body not found")
            return self._json(out)
        if path == "/api/briefing":
            live = app.live_state()
            out = m.build_briefing(app.db, live)
            out["carriers_here"] = app.carriers_here(live)
            return self._json(out)
        if path == "/api/ship":
            return self._json(m.build_ship(app.live_state()))
        if path == "/api/surface":
            sid = (qs.get("sys") or [None])[0]
            body = (qs.get("body") or [None])[0]
            out = m.build_surface(app.db, app.live_state(),
                                  int(sid) if sid and sid.isdigit() else None, body or None)
            if out.get("life"):
                out["backpack"] = m.backpack(app.cfg.journal_dir)     # on foot (M5)
            return self._json(out)
        if path == "/api/atlas/kinds":
            return self._json({"view": (qs.get("view") or ["signals"])[0],
                               "kinds": m.build_atlas_kinds(app.db, (qs.get("view") or ["signals"])[0])})
        if path == "/api/atlas":
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
        if path == "/api/shipstatus":
            from . import shipview
            live = app.live_state()
            try:
                live = dict(live, fuel_warning=m._fuel_state(live).warning() if live.get("ship") else None)
            except Exception:
                pass
            return self._json(shipview.build_shipstatus(live, app.archive, app.cfg.journal_dir, app.db))
        if path == "/api/carrier":
            from . import shipview
            from . import capi
            return self._json(shipview.build_carrier(app.archive, app.live_state(),
                                                     journal_dir=app.cfg.journal_dir,
                                                     capi_path=capi.path_for(app.cfg.plugin_dir)))
        if path == "/api/carriers/known":
            from . import carriers
            return self._json(carriers.build_known(app.archive, app.favourites, app.live_state()))
        if path == "/api/mining/live":
            from . import mining
            return self._json(mining.build_live(app.archive, app.live_state(), app.cfg.journal_dir))
        if path == "/api/mining":
            from . import mining
            from . import capi
            return self._json(mining.build_mining(app.archive, app.db, app.live_state(), app.cfg.journal_dir,
                                                  capi_path=capi.path_for(app.cfg.plugin_dir)))
        if path == "/api/statistics":
            from . import stats
            try:
                days = float((qs.get("days") or ["0"])[0]) or None
            except ValueError:
                days = None
            return self._json(stats.build_statistics(app.archive, days))
        if path == "/api/galaxy":
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
        if path == "/api/survey/export":
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
        if path == "/api/survey":
            return self._json(app.cached("survey", app.db.mtime(),
                                         lambda: m.build_survey(app.db)))
        return self._error(404, "unknown endpoint")

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
        with open(full, "rb") as fh:
            body = fh.read()
        ctype = self.STATIC_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        extra = {}
        cfg = self.app.cfg
        if cfg.lan and cfg.token and (qs.get("token") or [""])[0]:
            # remember the token for the module and API requests of this
            # page - the stored one: the request's token was checked equal
            # to it, and nothing a request sends ends up in a header
            extra["Set-Cookie"] = "fis_token=%s; Path=/; SameSite=Strict; HttpOnly" % cfg.token
        self._send(200, body, ctype, extra)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def make_server(app: App, host: Optional[str] = None, port: Optional[int] = None) -> ThreadingHTTPServer:
    handler = type("FISHandler", (Handler,), {"app": app})
    return _Server((host or app.cfg.host, app.cfg.port if port is None else port), handler)


def main(argv: Optional[list] = None) -> int:
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
