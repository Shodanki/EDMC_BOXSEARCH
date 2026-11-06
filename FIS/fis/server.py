"""HTTP server: static web files, JSON API and Server-Sent Events.

Standard library only (ThreadingHTTPServer). Default bind 127.0.0.1; with
--lan it binds 0.0.0.0 and every request needs the token from fis.ini, as
`?token=...` or header `X-FIS-Token`.
"""

from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import queue
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import __version__, setup
from .config import WEB_DIR, Config
from .data import Database
from .live import Hub, LiveTracker

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

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

    # ------------------------------------------------------------ routes
    def system(self, id64: int) -> Dict[str, Any]:
        live = self.live_state()
        fx = live.get("last_fix") or {}
        cur = live.get("system") or {}
        # positions move along their orbits; a 30 s bucket is plenty
        sig = (self.db.mtime(), int(time.time() // 30), cur.get("id64"),
               fx.get("body_id"), fx.get("body"),
               int((fx.get("ts") or 0) // 60), id(self.calib.model))
        self.calib.maybe_refresh()
        cm, om = self.calib.model, self.calib.order_model
        out = self.cached("sys:%d" % id64, sig, lambda: self.model.build_system(
            self.db, id64, live, self.cfg.filters, cost_model=cm, order_model=om))
        return self._with_carrier(out, id64)

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

    def health(self) -> Dict[str, Any]:
        live = self.live_state()
        return {
            "ok": True, "version": __version__, "uptime_s": round(time.time() - self.started, 1),
            "db": self.db.health(),
            "journal": {"dir": self.cfg.journal_dir, "exists": os.path.isdir(self.cfg.journal_dir),
                        "file": live.get("journal"), "last_event": live.get("last_event"),
                        "errors": self.live.errors},
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
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if not self._authorised(qs):
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
            return self._json(m.build_briefing(app.db, app.live_state()))
        if path == "/api/ship":
            return self._json(m.build_ship(app.live_state()))
        if path == "/api/surface":
            sid = (qs.get("sys") or [None])[0]
            body = (qs.get("body") or [None])[0]
            return self._json(m.build_surface(app.db, app.live_state(),
                                              int(sid) if sid and sid.isdigit() else None,
                                              body or None))
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
            return self._json(app.cached("galaxy:%s:%s" % (mc, days), sig,
                                         lambda: galaxy.build_galaxy(app.db, app.archive, live, mc, days)))
        if path == "/api/survey":
            return self._json(app.cached("survey", app.db.mtime(),
                                         lambda: m.build_survey(app.db)))
        return self._error(404, "unknown endpoint")

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
                    ev, data = q.get(timeout=15.0)
                    self._sse_write(ev, data)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(q)
            self.close_connection = True

    def _sse_write(self, event: str, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        self.wfile.write(("event: %s\ndata: %s\n\n" % (event, payload)).encode("utf-8"))
        self.wfile.flush()

    def _static(self, path: str, qs: Dict[str, Any]) -> None:
        if path in ("", "/"):
            path = "/index.html"
        root = os.path.realpath(self.app.web_dir)
        full = os.path.realpath(os.path.join(root, path.lstrip("/").replace("/", os.sep)))
        if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
            return self._error(404, "not found")
        with open(full, "rb") as fh:
            body = fh.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        extra = {}
        tok = (qs.get("token") or [""])[0]
        if self.app.cfg.lan and tok:
            # remember the token for the module and API requests of this page
            extra["Set-Cookie"] = "fis_token=%s; Path=/; SameSite=Strict; HttpOnly" % tok
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
