# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
netgate.py - the plugin's one door to the internet
==================================================
EDSM and Spansh are community services under heavy load. Every request the
plugin makes goes through one Gateway, which keeps them polite:

* one request at a time, never in parallel;
* a minimum pause between two requests to the same service
  (EDSM 2 s, Spansh 1 s, GitHub 60 s), with a little random spread;
* the service's own rate-limit headers are followed: when EDSM says only a
  few requests are left until its reset, the pause grows to spread them
  over the rest of the window, and at zero the service rests until then;
* 429 / 503 answers: wait as long as Retry-After says (or 5 s, 10 s, 20 s
  ... up to 120 s), at most 3 tries - then the service rests for the rest
  of the EDMC session. A wait longer than 120 s is not slept through: the
  service rests until then and the caller gets nothing;
* an honest User-Agent with the plugin version and the repository address,
  so the operators can see who asks and reach us;
* at most DAILY_CAP requests per service and UTC day (EDSM, Spansh: 50 -
  a 50 ly survey needs about 5); then the service rests until midnight UTC;
* an offline switch: nothing is sent at all;
* every attempt is recorded (time, service, endpoint, HTTP status, ok,
  duration) for the call log in the database.

Standard library only (plus `requests` when EDMC provides it).
"""

from __future__ import annotations

import email.utils
import logging
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

REPO_URL = "https://github.com/Shodanki/EDMC_BOXSEARCH"

# minimum seconds between two requests to the same service
MIN_INTERVAL = {"edsm": 2.0, "spansh": 1.0, "github": 60.0}
DEFAULT_INTERVAL = 2.0
JITTER = 0.2              # pause * (1 .. 1.2)
MAX_ATTEMPTS = 3          # tries on 429 / 503
BACKOFF_BASE = 5.0        # 5, 10, 20 ... seconds
MAX_WAIT = 120.0          # longer waits are not slept through
MAX_REST = 3600.0         # a rate-limit reset further away than this is capped
RETRY_STATUS = (429, 503)
SESSION_REST = float("inf")
DAILY_CAP = {"edsm": 50, "spansh": 50}   # requests per UTC day (user, 10.11.)


def user_agent(version: str) -> str:
    return "SHBOXSEARCH/%s (EDMC plugin; +%s)" % (version or "?", REPO_URL)


def _retry_after(value: Optional[str], now: float) -> Optional[float]:
    """Seconds from a Retry-After header (delta seconds or HTTP date)."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - now)


def _header_int(headers: Any, name: str) -> Optional[int]:
    try:
        v = headers.get(name)
    except Exception:
        return None
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


class Gateway:
    """
    request(service, method, url, endpoint=..., **kw) -> response or None.

    None means: no answer to use - offline, the service is resting, or the
    network failed. The caller stops asking that service for now; its local
    and cached data still count.
    """

    def __init__(self, version: str = "",
                 session_factory: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.time,
                 rand: Callable[[], float] = random.random):
        self.ua = user_agent(version)
        self._factory = session_factory or (requests.Session if requests else None)
        self._clock = clock
        self._rand = rand
        self._lock = threading.Lock()          # one request at a time
        self._rec_lock = threading.Lock()
        self._stop = threading.Event()
        self._sessions: Dict[str, Any] = {}
        self._next_ok: Dict[str, float] = {}   # earliest time of the next request
        self._rest_until: Dict[str, float] = {}
        self._rest_why: Dict[str, str] = {}
        self.records: List[Tuple[float, str, str, int, bool, int]] = []
        self.calls: Dict[str, int] = {}       # this session, per service
        self._day: Dict[str, Tuple[int, int]] = {}  # service -> (UTC day, count)
        self.offline = False

    # ----------------------------------------------------------- status
    @property
    def usable(self) -> bool:
        return self._factory is not None

    def resting(self, service: str) -> Optional[str]:
        """Why the service is resting, or None when it may be asked."""
        until = self._rest_until.get(service)
        if until is None:
            return None
        if until != SESSION_REST and self._clock() >= until:
            self._rest_until.pop(service, None)
            self._rest_why.pop(service, None)
            return None
        why = self._rest_why.get(service, "resting")
        if until == SESSION_REST:
            return "%s - resting until EDMC restarts" % why
        return "%s - resting until %s UTC" % (
            why, time.strftime("%H:%M", time.gmtime(until)))

    def today(self, service: str) -> int:
        """Requests to the service on the current UTC day."""
        day, n = self._day.get(service, (-1, 0))
        return n if day == int(self._clock() // 86400) else 0

    def seed_today(self, counts: Dict[str, int]) -> None:
        """Counts from the database call log, so an EDMC restart does not
        reset the daily cap."""
        day = int(self._clock() // 86400)
        for svc, n in counts.items():
            self._day[svc] = (day, max(int(n), self.today(svc)))

    def status(self, service: str) -> Tuple[bool, str]:
        if not self.usable:
            return False, "requests module missing"
        if self.offline:
            return False, "offline mode"
        why = self.resting(service)
        if why:
            return False, why
        cap = DAILY_CAP.get(service)
        if cap:
            return True, "ready (%d of %d today)" % (self.today(service), cap)
        return True, "ready (%d calls this session)" % self.calls.get(service, 0)

    def drain(self) -> List[Tuple[float, str, str, int, bool, int]]:
        """Recorded attempts since the last drain: (ts, service, endpoint,
        http status or 0, ok, milliseconds)."""
        with self._rec_lock:
            out, self.records = self.records, []
        return out

    def stop(self) -> None:
        """Wake every waiting request; nothing more is sent."""
        self._stop.set()

    # ----------------------------------------------------------- internals
    def _rest(self, service: str, until: float, why: str) -> None:
        self._rest_until[service] = until
        self._rest_why[service] = why
        logger.warning("%s: %s", service, self.resting(service) or why)

    def _wait(self, seconds: float) -> bool:
        """Sleep, but wake on stop(). False when stopped."""
        if seconds > 0:
            self._stop.wait(seconds)
        return not self._stop.is_set()

    def _session(self, service: str) -> Any:
        s = self._sessions.get(service)
        if s is None:
            s = self._factory()
            try:
                s.headers.update({"User-Agent": self.ua})
            except Exception:
                pass
            self._sessions[service] = s
        return s

    def _record(self, service: str, endpoint: str, status: int, ok: bool,
                started: float) -> None:
        ms = int(max(0.0, self._clock() - started) * 1000)
        with self._rec_lock:
            self.records.append((self._clock(), service, endpoint, int(status),
                                 bool(ok), ms))
        self.calls[service] = self.calls.get(service, 0) + 1
        self._day[service] = (int(self._clock() // 86400), self.today(service) + 1)

    def _pace_from_headers(self, service: str, resp: Any) -> None:
        """Follow X-Rate-Limit-Remaining / -Reset (EDSM sends them)."""
        headers = getattr(resp, "headers", None)
        if headers is None:
            return
        remaining = _header_int(headers, "X-Rate-Limit-Remaining")
        reset = _header_int(headers, "X-Rate-Limit-Reset")
        if remaining is None or reset is None or reset <= 0:
            return
        now = self._clock()
        # EDMC reads Reset as a Unix time, EDDI as seconds to go - accept both
        if reset > 1_000_000_000:
            reset = int(reset - now)
            if reset <= 0:
                return
        reset = min(reset, MAX_REST)
        if remaining <= 0:
            self._rest(service, now + reset, "rate limit used up")
            return
        spread = reset / float(remaining)
        if spread > MAX_WAIT:
            # too slow to wait for in a worker: rest instead of sleeping
            self._rest(service, now + spread, "rate limit nearly used up")
            return
        if spread > MIN_INTERVAL.get(service, DEFAULT_INTERVAL):
            self._next_ok[service] = max(self._next_ok.get(service, 0.0),
                                         now + spread)

    # ----------------------------------------------------------- request
    def request(self, service: str, method: str, url: str, endpoint: str = "",
                **kw: Any) -> Any:
        if not self.usable or self.offline or self._stop.is_set():
            return None
        if self.resting(service):
            return None
        endpoint = endpoint or url
        with self._lock:
            attempt = 0
            while True:
                if self._stop.is_set() or self.resting(service):
                    return None
                cap = DAILY_CAP.get(service)
                if cap and self.today(service) >= cap:
                    midnight = (int(self._clock() // 86400) + 1) * 86400.0
                    self._rest(service, midnight, "daily cap of %d requests reached" % cap)
                    return None
                gap = self._next_ok.get(service, 0.0) - self._clock()
                if gap > 0 and not self._wait(gap):
                    return None
                started = self._clock()
                pause = MIN_INTERVAL.get(service, DEFAULT_INTERVAL)
                self._next_ok[service] = started + pause * (1.0 + JITTER * self._rand())
                try:
                    resp = self._session(service).request(method, url, **kw)
                except Exception as e:
                    self._record(service, endpoint, 0, False, started)
                    logger.warning("%s %s failed: %s", service, endpoint, e)
                    return None
                status = int(getattr(resp, "status_code", 0) or 0)
                self._record(service, endpoint, status, status == 200, started)
                if status not in RETRY_STATUS:
                    self._pace_from_headers(service, resp)
                    return resp
                attempt += 1
                if attempt >= MAX_ATTEMPTS:
                    self._rest(service, SESSION_REST,
                               "HTTP %d after %d tries" % (status, attempt))
                    return None
                headers = getattr(resp, "headers", None) or {}
                wait = _retry_after(headers.get("Retry-After"), self._clock())
                if wait is None:
                    wait = BACKOFF_BASE * (2 ** (attempt - 1))
                    wait *= 1.0 + JITTER * self._rand()
                if wait > MAX_WAIT:
                    self._rest(service, self._clock() + wait,
                               "HTTP %d, asked to wait %d s" % (status, wait))
                    return None
                logger.info("%s: HTTP %d, waiting %.0f s (try %d of %d)",
                            service, status, wait, attempt + 1, MAX_ATTEMPTS)
                self._next_ok[service] = self._clock() + wait


# ---------------------------------------------------------------------------
# self test - no network: a fake session and a fake clock
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status: int = 200, headers: Optional[Dict[str, str]] = None,
                 body: Any = None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body if body is not None else []

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)


class _FakeSession:
    def __init__(self, script: List[Any], clock: "_FakeClock"):
        self.headers: Dict[str, str] = {}
        self.script = script
        self.clock = clock
        self.sent: List[Tuple[float, str, str]] = []

    def request(self, method: str, url: str, **kw: Any) -> Any:
        self.sent.append((self.clock.t, method, url))
        item = self.script.pop(0) if self.script else _FakeResp()
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClock:
    def __init__(self) -> None:
        self.t = 1_700_000_000.0   # a realistic Unix time

    def __call__(self) -> float:
        return self.t


def _make(script: List[Any]) -> Tuple[Gateway, _FakeSession, _FakeClock]:
    clock = _FakeClock()
    sess = _FakeSession(script, clock)
    gw = Gateway("9.9.9", session_factory=lambda: sess, clock=clock,
                 rand=lambda: 0.0)
    # sleeping advances the fake clock instead of the real one
    gw._wait = lambda s: (setattr(clock, "t", clock.t + max(0.0, s)), True)[1]  # type: ignore
    return gw, sess, clock


def _selftest() -> int:
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    gw, sess, clock = _make([_FakeResp(), _FakeResp()])
    gw.request("edsm", "GET", "u1", "sphere")
    gw.request("edsm", "GET", "u2", "sphere")
    check(sess.sent[1][0] - sess.sent[0][0] >= MIN_INTERVAL["edsm"],
          "two EDSM requests at least %.0f s apart" % MIN_INTERVAL["edsm"])
    check(sess.headers.get("User-Agent", "").startswith("SHBOXSEARCH/9.9.9")
          and REPO_URL in sess.headers["User-Agent"],
          "User-Agent names version and repository")
    rec = gw.drain()
    check(len(rec) == 2 and rec[0][1:5] == ("edsm", "sphere", 200, True)
          and not gw.drain(), "every attempt recorded, drain empties")

    gw, sess, clock = _make([_FakeResp(429, {"Retry-After": "7"}), _FakeResp()])
    r = gw.request("edsm", "GET", "u", "sphere")
    check(r is not None and r.status_code == 200
          and abs(sess.sent[1][0] - sess.sent[0][0] - 7.0) < 0.01,
          "429 with Retry-After 7: waits 7 s, then succeeds")

    gw, sess, clock = _make([_FakeResp(429)] * 3)
    r = gw.request("spansh", "POST", "u", "search")
    check(r is None and len(sess.sent) == 3, "three 429 answers: gives up after 3 tries")
    check(abs(sess.sent[1][0] - sess.sent[0][0] - BACKOFF_BASE) < 0.01
          and abs(sess.sent[2][0] - sess.sent[1][0] - 2 * BACKOFF_BASE) < 0.01,
          "backoff without Retry-After: 5 s, then 10 s")
    r = gw.request("spansh", "POST", "u", "search")
    check(r is None and len(sess.sent) == 3 and "EDMC restarts" in (gw.resting("spansh") or ""),
          "then the service rests for the session - nothing more is sent")
    check(gw.request("edsm", "GET", "u", "sphere") is not None,
          "another service is not affected")

    gw, sess, clock = _make([_FakeResp(503, {"Retry-After": "600"}), _FakeResp()])
    r = gw.request("edsm", "GET", "u", "sphere")
    check(r is None and len(sess.sent) == 1 and gw.resting("edsm"),
          "Retry-After 600 s: not slept through, service rests")
    clock.t += 601
    check(gw.request("edsm", "GET", "u", "sphere") is not None,
          "after the rest the service is asked again")

    gw, sess, clock = _make([
        _FakeResp(200, {"X-Rate-Limit-Remaining": "10", "X-Rate-Limit-Reset": "100"}),
        _FakeResp(200, {"X-Rate-Limit-Remaining": "0", "X-Rate-Limit-Reset": "300"}),
        _FakeResp()])
    gw.request("edsm", "GET", "u", "sphere")
    gw.request("edsm", "GET", "u", "sphere")
    check(sess.sent[1][0] - sess.sent[0][0] >= 10.0,
          "10 requests left for 100 s: next one 10 s later")
    check(gw.request("edsm", "GET", "u", "sphere") is None and len(sess.sent) == 2,
          "limit used up: rests until the reset")

    gw, sess, clock = _make([
        _FakeResp(200, {"X-Rate-Limit-Remaining": "20",
                        "X-Rate-Limit-Reset": str(1_700_000_000 + 200)}),
        _FakeResp()])
    gw.request("edsm", "GET", "u", "sphere")
    gw.request("edsm", "GET", "u", "sphere")
    gap = sess.sent[1][0] - sess.sent[0][0]
    check(9.9 <= gap <= 10.1, "Reset as Unix time (EDMC style): 20 left for 200 s -> 10 s")
    gw, sess, clock = _make([
        _FakeResp(200, {"X-Rate-Limit-Remaining": "1", "X-Rate-Limit-Reset": "3000"}),
        _FakeResp()])
    gw.request("edsm", "GET", "u", "sphere")
    check(gw.request("edsm", "GET", "u", "sphere") is None and len(sess.sent) == 1,
          "1 left for 50 min: rests instead of sleeping in the worker")

    gw, sess, clock = _make([_FakeResp()] * (DAILY_CAP["edsm"] + 1))
    gw.seed_today({"edsm": DAILY_CAP["edsm"] - 2})
    r1 = gw.request("edsm", "GET", "u", "sphere")
    r2 = gw.request("edsm", "GET", "u", "sphere")
    r3 = gw.request("edsm", "GET", "u", "sphere")
    check(r1 is not None and r2 is not None and r3 is None and len(sess.sent) == 2
          and "daily cap" in (gw.resting("edsm") or ""),
          "daily cap %d: counted across restarts, then rests" % DAILY_CAP["edsm"])
    clock.t = (int(clock.t // 86400) + 1) * 86400.0 + 1
    check(gw.request("edsm", "GET", "u", "sphere") is not None and gw.today("edsm") == 1,
          "a new UTC day: asked again, count starts at 1")

    gw, sess, clock = _make([ConnectionError("no route")])
    r = gw.request("spansh", "POST", "u", "search")
    rec = gw.drain()
    check(r is None and rec and rec[0][3] == 0 and rec[0][4] is False,
          "network error: no answer, recorded as status 0")

    gw, sess, clock = _make([_FakeResp()])
    gw.offline = True
    check(gw.request("edsm", "GET", "u", "sphere") is None and not sess.sent
          and not gw.status("edsm")[0], "offline: nothing is sent")
    gw.offline = False
    gw.stop()
    check(gw.request("edsm", "GET", "u", "sphere") is None and not sess.sent,
          "after stop(): nothing is sent")

    # the sources use the gateway: EDSM over 100 ly needs several spheres,
    # a resting EDSM stops the loop at once; Spansh pages are paced
    from sources import EDSMSource, SpanshSource
    gw, sess, clock = _make([_FakeResp(429)] * 3)
    EDSMSource(gw).fetch((0.0, 0.0, 0.0), 250.0)
    check(len(sess.sent) == 3, "EDSM over 100 ly: stops after the rest, no more spheres")
    page = [{"name": "S%d" % i, "x": 1.0, "y": 0.0, "z": 0.0} for i in range(500)]
    gw, sess, clock = _make([_FakeResp(200, body={"results": page}),
                             _FakeResp(200, body={"results": page[:3]})])
    rows = SpanshSource(gw).fetch((0.0, 0.0, 0.0), 50.0)
    check(len(rows) == 500 and len(sess.sent) == 2
          and sess.sent[1][0] - sess.sent[0][0] >= MIN_INTERVAL["spansh"],
          "Spansh pages one after another, paced")

    now = time.time()
    check(_retry_after("Wed, 21 Oct 2099 07:28:00 GMT", now) > 0
          and _retry_after("abc", now) is None, "Retry-After as HTTP date")

    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    raise SystemExit(1 if _selftest() else 0)
