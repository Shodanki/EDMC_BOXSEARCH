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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.boxelplan import (ProspectCalibration, _wilson, bundled_probe_prefix)  # noqa: E402


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


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
