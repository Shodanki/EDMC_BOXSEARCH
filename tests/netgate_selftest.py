# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of netgate.py (moved from the module in 4.12, N7 - verbatim).

    python tests/netgate_selftest.py      (from the plugin folder)
"""
from typing import Any, Dict, List, Optional, Tuple
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.netgate import (BACKOFF_BASE, DAILY_CAP, Gateway, MIN_INTERVAL, REPO_URL,  # noqa: E402
                                 _retry_after, user_agent)


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
    check(user_agent("9.9.9", "EDCD-EDMarketConnector-6.1.2")
          == "EDCD-EDMarketConnector-6.1.2 SHBOXSEARCH/9.9.9 (EDMC plugin; +%s)" % REPO_URL,
          "inside EDMC: EDMC's User-Agent first, ours appended")
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
    from SHBOXSEARCH.sources import EDSMSource, SpanshSource
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

    # A6 (5.1.0): a service waiting for its pause does not hold the lock -
    # another service is asked meanwhile; still one request at a time
    import threading
    import time as _t
    out: List[Any] = []
    busy = [0, 0]                                   # requests out now, most at once

    class _Slow:
        headers: Dict[str, str] = {}

        def request(self, method: str, url: str, **kw: Any) -> Any:
            busy[0] += 1
            busy[1] = max(busy[1], busy[0])
            _t.sleep(0.05)
            busy[0] -= 1
            return _FakeResp()

    gw = Gateway("9.9.9", session_factory=_Slow, rand=lambda: 0.0)
    gw._next_ok["spansh"] = _t.time() + 0.6         # Spansh must wait its pause
    th = threading.Thread(target=lambda: out.append(("spansh", gw.request("spansh", "GET", "s"), _t.time())))
    th.start()
    _t.sleep(0.05)
    t0 = _t.time()
    gw.request("edsm", "GET", "e")
    edsm_s = _t.time() - t0
    th.join()
    check(edsm_s < 0.3, "EDSM answered in %.2f s while Spansh waited its pause" % edsm_s)
    check(out and out[0][1] is not None, "Spansh asked after its pause")
    check(busy[1] == 1, "never two requests out at once (%d)" % busy[1])

    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    raise SystemExit(1 if _selftest() else 0)
