# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of boxelplan.py (moved from the module in 4.12, N7 - verbatim).

    python tests/boxelplan_selftest.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.boxelplan import (  # noqa: E402
    K_PROBE, ProspectCalibration, Target, _queues, _wilson, bundled_probe_prefix, probe_factors)
from SHBOXSEARCH.sysdb import Q_CONFIRMED, SystemDB  # noqa: E402


def _selftest() -> int:
    """python boxelplan.py - the probe bundle prefix."""
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    class T:
        def __init__(self, key):
            self.boxel_key = key

    q = [T("Synuefe VA-I b2"), T("Synuefe VA-I b2"), T("Synuefe VA-I b3"),
         T("Synuefe XV-C d"), T("Synuefe VA-I b17")]
    p, b = bundled_probe_prefix(q)
    check(p == "Synuefe VA-I b" and b == ["Synuefe VA-I b2", "Synuefe VA-I b3",
                                          "Synuefe VA-I b17"],
          "same sector, letters and mass code: one prefix for three boxels")
    p, b = bundled_probe_prefix([T("Col 285 Sector AB-C d12"), T("Col 285 Sector AB-C d13"),
                                 T("Col 285 Sector ZZ-Y d4")])
    check(p == "Col 285 Sector AB-C d" and len(b) == 2,
          "sector of several words stays whole; other letter group left out")
    p, b = bundled_probe_prefix([T("Synuefe XV-C d"), T("Synuefe VA-I b2")])
    check(p == "Synuefe XV-C d" and b == ["Synuefe XV-C d"],
          "nothing to bundle: the single boxel's own prefix")
    # H3 #7: calibration on own probe outcomes
    c = ProspectCalibration()
    check(c.score(0, 2.5) == 2.5 and c.score(1, 6.0) == 6.0,
          "no outcomes: the formula itself")
    for _ in range(70):
        c.add(0, 2.5, False)
    check(not c.active() and c.score(0, 2.5) == 2.5,
          "misses alone (as in the real survey, 0 of 131) change nothing")
    for _ in range(40):
        c.add(0, 3.5, False)                       # band 3 never paid in mass code a
    for _ in range(10):
        c.add(0, 0.5, True)                        # band 0 always did
    check(c.active() and c.score(0, 0.5) > c.score(0, 3.5),
          "measured outcomes turn the order round: %.2f vs %.2f"
          % (c.score(0, 0.5), c.score(0, 3.5)))
    check(abs(c.score(0, 1.5) - 1.5) < 1e-9,
          "a band without outcomes keeps its formula score")
    check(c.score(0, 3.5) < c.score(2, 3.5) < 3.5,
          "a mass code without outcomes leans on all mass codes, less strongly")
    sm = {x["band"]: x for x in c.summary()}
    check(sm[3]["n"] == 40 and sm[3]["hits"] == 0 and not sm[3]["thin"]
          and sm[0]["thin"] and sm[0]["rate"] == 1.0 and sm[1]["n"] == 0,
          "summary per band with thin marker")
    lo, hi = _wilson(0, 40)
    check(lo == 0.0 and 0.05 < hi < 0.1, "Wilson range of 0 of 40: 0-%.0f%%" % (100 * hi))
    check(ProspectCalibration.band(0.99) == 0 and ProspectCalibration.band(4.0) == 4,
          "band edges")
    p, b = bundled_probe_prefix([T("Synuefe VA-I b2"), T("Synuefe VA-I b3")], n=1)
    check(p == "Synuefe VA-I b2-" and len(b) == 1, "n=1: just the next boxel")
    check(bundled_probe_prefix([]) == ("", []), "empty queue")
    print("failures: %d" % fails)
    return fails


def _probe_selftest() -> int:
    """FX4: probes ordered by their mass code's own outcomes."""
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    check(probe_factors({0: [1, 300], 1: [0, 10]}) == {}, "one hit: every mass code alike")
    f = probe_factors({0: [2, 319], 1: [2, 13], 2: [0, 2]})
    check(f[1] > 5 > 1 > f[2] > f[0] > 0.3, "measured 18.11.: a %.2f, b %.2f, c %.2f" % (f[0], f[1], f[2]))
    near_a = Target("Synuefe AA-A a1-5", K_PROBE, 10.0, mc=0, boxel_key="Synuefe AA-A a1")
    far_b = Target("Synuefe AA-A b1-5", K_PROBE, 30.0, mc=1, boxel_key="Synuefe AA-A b1")
    for t in (near_a, far_b):
        t.dist_origin = t.dist
    _f, probe, _c = _queues([near_a, far_b], {})
    check(probe[0] is near_a, "without outcomes: the nearer probe first")
    _f, probe, _c = _queues([near_a, far_b], {}, f)
    check(probe[0] is far_b, "with outcomes: b three times as far, but first")

    db = SystemDB(os.path.join(tempfile.mkdtemp(), "p.sqlite"))
    for n in ("Synuefe AB-C a1-1", "Synuefe AB-C a1-2", "Synuefe AB-C b1-9", "Hambula"):
        db.cx.execute("INSERT INTO absent (name, boxel, n2, ts) VALUES (?, '', 0, '')", (n,))
    for n, src in (("Synuefe QD-B a13-0", "fsdtarget"), ("Synuefe XY-Z b2-0", "fsdtarget"),
                   ("Synuefe XY-Z b2-1", "fsdtarget,EDSM"), ("Glaston", "fsdtarget")):
        db.cx.execute("INSERT INTO systems (name, quality, sources) VALUES (?, ?, ?)", (n, Q_CONFIRMED, src))
    db.cx.commit()
    out = db.probe_outcomes()
    check(out == {0: [1, 3], 1: [1, 2]}, "outcomes per mass code; named and database-known left out: %s" % out)
    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if (_selftest() + _probe_selftest()) else 0)
