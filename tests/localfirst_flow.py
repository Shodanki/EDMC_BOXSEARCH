# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Local-first flow test (4.6, L2/L3): load.py against a fake galaxy - no
network, no EDMC (its modules are stubbed). Survey start asks the nearest
shell only, the next shell when needed, valid shells are never asked
again, reload/offline/EDSM-off behave.

    python tests/localfirst_flow.py      (from the plugin folder)
"""
import json
import math
import os
import random
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ("config", "theme", "myNotebook", "monitor", "l10n", "companion", "plug",
          "EDMCLogging", "ttkHyperlinkLabel"):
    sys.modules[m] = mock.MagicMock()
try:                                  # CI images may lack Tk; no window is opened
    import tkinter  # noqa: F401
except ImportError:
    for m in ("tkinter", "tkinter.filedialog", "tkinter.ttk"):
        sys.modules[m] = mock.MagicMock()

import netgate  # noqa: E402
netgate.MIN_INTERVAL = {"edsm": 0.0, "spansh": 0.0, "github": 0.0}
import load  # noqa: E402
import shells  # noqa: E402
from sysdb import SystemDB  # noqa: E402
from boxelplan import Planner  # noqa: E402

random.seed(4)
GAL = []
for i in range(400):
    r = 60 * random.random() ** (1 / 3)
    d = [random.gauss(0, 1) for _ in range(3)]
    n = math.sqrt(sum(v * v for v in d))
    GAL.append(("Fake %d" % i, [r * v / n for v in d]))


class Resp:
    def __init__(self, body):
        self.status_code = 200
        self.headers = {}
        self._b = body

    def json(self):
        return self._b

    def raise_for_status(self):
        pass


class Sess:
    log = []

    def __init__(self):
        self.headers = {}

    def request(self, method, url, **kw):
        if "edsm" in url:
            p = kw["params"]
            c = (p["x"], p["y"], p["z"])
            lo, hi = p.get("minRadius", 0), p["radius"]
            Sess.log.append(("edsm", lo, hi))
            out = [{"name": n, "coords": {"x": x[0], "y": x[1], "z": x[2]}}
                   for n, x in GAL if lo <= math.dist(x, c) <= hi]
            return Resp(out)
        body = json.loads(kw["data"])
        f = body["filters"]["distance"]
        lo, hi = float(f["min"]), float(f["max"])
        Sess.log.append(("spansh", lo, hi))
        rc = body["reference_coords"]
        c = (rc["x"], rc["y"], rc["z"])
        out = [{"name": n, "x": x[0], "y": x[1], "z": x[2]}
               for n, x in GAL if lo <= math.dist(x, c) <= hi]
        return Resp({"results": out[:500]})


cfg = {load.CFG["src_edd"]: False}
load.cfg_bool = lambda k, d=False: cfg.get(k, d)
load.cfg_int = lambda k, d=0: d
load._set_status = lambda m: None
load._ui = lambda f, *a, **k: None
load._update_route_targets = lambda: None
ran = []
load._run_async = lambda fn, *a, label="", **kw: ran.append(label) or fn(*a, **kw)
ST = load.ST
ST.net._factory = Sess

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


with tempfile.TemporaryDirectory() as d:
    ST.db = SystemDB(os.path.join(d, "t.sqlite"))
    ST.planner = Planner(ST.db)
    ST.active, ST.center, ST.radius, ST.start_system = True, (0.0, 0.0, 0.0), 50.0, "Fake 0"
    ST.cur_pos = (0.0, 0.0, 0.0)

    # 1) start: shell 0-25 from both; plan finds nothing left (fake names)
    #    -> extends once more to 25-50, then stops at the radius
    load._start_worker()
    check(Sess.log[:2] == [("spansh", 0.0, 25.0), ("edsm", 0.0, 25.0)],
          "start: first shell 0-25 ly from Spansh and EDSM")
    check(ST.horizon == 25.0 and len(Sess.log) == 2 and ST.flight,
          "targets left inside 25 ly: the next shell waits")
    ST.cur_pos = (16.0, 0.0, 0.0)
    load._maybe_extend()
    check(ST.horizon == 50.0 and ("spansh", 25.0, 50.0) in Sess.log
          and ("edsm", 25.0, 50.0) in Sess.log and len(Sess.log) == 4,
          "10 ly from the edge -> next shell 25-50, then stop at 50 ly")
    ST.cur_pos = (0.0, 0.0, 0.0)
    n_db = ST.db.cx.execute("SELECT COUNT(*) FROM systems").fetchone()[0]
    inside = sum(1 for _, x in GAL if math.dist(x, (0, 0, 0)) <= 50)
    check(n_db == inside, "every system of the sphere stored once (%d)" % inside)
    check(len(ST.db.valid_shells("edsm")) == 2 and len(ST.db.valid_shells("spansh")) == 2,
          "both shells remembered per service")
    calls = ST.db.external_calls_since(0)
    check(calls == 4, "call log: 4 requests")

    # 2) EDMC restart with the survey running: valid shells, no request
    Sess.log.clear()
    load._resume_worker()
    check(Sess.log == [] and ST.horizon == 50.0, "restart: shells still valid - no request")

    # 3) shells expire -> restart plans nothing until asked, then asks shell 1
    #    (F2: no phantom plan with radius 0, even with no position known)
    ST.db.cx.execute("UPDATE fetched_shells SET expires_at=?", (time.time() - 1,))
    ST.db.cx.commit()
    ST.cur_pos = None
    seen = []
    real_build = ST.planner.build
    ST.planner.build = lambda c, r, **kw: seen.append(r) or real_build(c, r, **kw)
    load._resume_worker()
    ST.planner.build = real_build
    check(Sess.log == [("spansh", 0.0, 25.0), ("edsm", 0.0, 25.0)]
          and ST.horizon == 25.0 and ST.flight,
          "expired: asked again, nearest shell first, then a real plan")
    check(seen and min(seen) > 0, "no plan built with radius 0 (phantom probes)")
    ST.cur_pos = (0.0, 0.0, 0.0)

    # 4) reload button: the shells up to the horizon again - and no further (F3)
    Sess.log.clear()
    load._reload_online()
    check(Sess.log == [("spansh", 0.0, 25.0), ("edsm", 0.0, 25.0)],
          "reload: shells up to the horizon asked again, not beyond")

    # 5) offline: nothing sent, the plan uses local data to the radius
    Sess.log.clear()
    ST.net.offline = True
    load._start_worker()
    check(Sess.log == [] and ST.horizon == 50.0, "offline: no request, horizon = sphere")
    ST.net.offline = False

    # 6) a new survey 3 ly away: its shells count as fetched (>= 90 %)
    Sess.log.clear()
    ST.center = (3.0, 0.0, 0.0)
    load._start_worker()
    check(not any(lo == 0.0 for _, lo, _ in Sess.log) and ST.horizon >= 25.0,
          "survey 3 ly away: the valid 0-25 shell is not asked again")

    # 7) EDSM switched off: only Spansh asked
    Sess.log.clear()
    cfg[load.CFG["src_edsm"]] = False
    ST.center = (200.0, 0.0, 0.0)
    load._start_worker()
    check(Sess.log and all(s == "spansh" for s, _, _ in Sess.log),
          "EDSM off: only Spansh asked")
    cfg[load.CFG["src_edsm"]] = True

    # 8) EDDiscovery current (its source is Spansh): Spansh is not asked,
    #    its systems come from EDD's file; EDSM is still asked (L4e)
    class FakeEDD:
        name, priority, last_ok, truncated = "EDDiscovery", 10, False, False
        busy, current, reads = False, True, []

        def available(self):
            return (False, "EDD database busy") if self.busy else (True, "ok")

        def set_reference(self, *a):
            pass

        def is_current(self, service, now=None):
            return self.current and service == "spansh"

        def fetch(self, center, radius, progress=None, r_min=0.0):
            self.reads.append((r_min, radius))
            self.last_ok = not self.busy
            if self.busy:
                return []
            return [{"name": n, "x": x[0], "y": x[1], "z": x[2], "id64": None}
                    for n, x in GAL if r_min <= math.dist(x, center) <= radius]

    edd = FakeEDD()
    ST.sources.sources["edd"] = edd
    cfg[load.CFG["src_edd"]] = True
    Sess.log.clear()
    ST.center = (400.0, 0.0, 0.0)
    load._start_worker()
    check(Sess.log and all(svc == "edsm" for svc, _, _ in Sess.log),
          "EDD current: only EDSM asked, Spansh's data from EDD")
    check(any(r == (0.0, 25.0) for r in edd.reads),
          "EDD read locally for the shell instead")
    check("Spansh covered by EDDiscovery" in load._external_today_line(),
          "statistics say so")

    # 9) EDDiscovery busy (EDD running): noted, read again later - no
    #    online request instead of it
    edd.busy, edd.reads = True, []
    Sess.log.clear()
    ST.center = (800.0, 0.0, 0.0)
    load._start_worker()
    check(ST.edd_pending and ("spansh", 0.0, 25.0) in Sess.log,
          "EDD busy: noted; not current any more, so Spansh is asked")
    edd.busy = False
    ST.edd_next_try = 0.0
    ST.edd_retrying = False
    load._maybe_extend()
    check(not ST.edd_pending and edd.reads[-1] == (0.0, ST.radius),
          "EDD free again: read on the next plan, locally")
    cfg[load.CFG["src_edd"]] = False

    # 10) daily cap reached: nothing is sent, the plan uses local data
    Sess.log.clear()
    ST.net.seed_today({"edsm": netgate.DAILY_CAP["edsm"],
                       "spansh": netgate.DAILY_CAP["spansh"]})
    ST.center = (1200.0, 0.0, 0.0)
    # the commander flies at the sphere's edge (far outside, nothing would be
    # fetched at all - see shells.needs_next)
    ST.cur_pos = (1245.0, 0.0, 0.0)
    load._start_worker()
    check(Sess.log == [] and ST.horizon == ST.radius,
          "daily cap %d reached: no request, local plan" % netgate.DAILY_CAP["edsm"])
    check("50 of 50" in load._external_today_line(), "statistics show the count")

    # 11) a second commander on this PC: nothing of the first one's place stays
    ST.cmdr, ST.cur_system, ST.cur_id64 = "Alpha", "Old System", 4711
    ST.route_done = {3, 4}
    load.journal_entry("Beta", False, None, None,
                       {"event": "LoadGame", "timestamp": "2026-11-11T07:00:00Z"}, {})
    load.journal_entry("Beta", False, None, None, {"event": "StartUp"}, {})
    check(ST.cur_id64 is None and ST.awaiting_position and not ST.route_done
          and "route recheck" not in ran[-1:],
          "commander switch: old system and ticks dropped, no route for it")
    load._resolve_current_system()
    check(ST.cur_id64 is None, "and nothing guessed from the other commander's journals")
    load.journal_entry("Beta", False, None, None,
                       {"event": "Location", "StarSystem": "New System", "SystemAddress": 815,
                        "StarPos": [1.0, 2.0, 3.0], "timestamp": "2026-11-11T07:00:05Z"}, {})
    check(ST.cur_id64 == 815 and not ST.awaiting_position,
          "the new commander's Location sets the system")
    ST.db.close()

print("failures: %d" % fails)
sys.exit(1 if fails else 0)
