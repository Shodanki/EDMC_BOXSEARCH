# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Complexity ratchet (4.11): EDMC measures plugins with
``flake8 --max-complexity 15 --select C901``. Every function of the plugin
and the FIS stays at 15 or below - except the older functions listed in
LEGACY, which may not grow beyond the value they had when the list was
made, and leave it once they are split up. A new function above 15, or a
listed one that got more complex, fails.

    python tests/complexity.py      (from the plugin folder; needs flake8's mccabe)
"""
import ast
import os
import sys

import mccabe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 15
SKIP_DIRS = {"tests", "edts_pgnames", "regionmap", "vendor", "__pycache__", ".git", ".github"}

# measured 13.11.2026 (4.11): what may not grow; split them up over time
LEGACY = {
    ("FIS/fis/calib.py", "measure"): 19,
    ("FIS/fis/carriers.py", "build_known"): 19,
    ("FIS/fis/carriers.py", "docking_access"): 16,
    ("FIS/fis/carriers.py", "known_carriers"): 20,
    ("FIS/fis/fleet.py", "Archive._read"): 16,
    ("FIS/fis/fleet.py", "Archive.carrier"): 18,
    ("FIS/fis/fleet.py", "Archive.fleet"): 29,
    ("FIS/fis/galaxy.py", "build_galaxy"): 16,
    ("FIS/fis/learn.py", "learning_status"): 16,
    ("FIS/fis/live.py", "LiveTracker.feed"): 53,
    ("FIS/fis/live.py", "LiveTracker.feed_status"): 17,
    ("FIS/fis/materials.py", "stock"): 19,
    ("FIS/fis/mining.py", "build_mining"): 37,
    ("FIS/fis/model.py", "_build_surface"): 36,
    ("FIS/fis/model.py", "build_atlas"): 20,
    ("FIS/fis/model.py", "build_body"): 23,
    ("FIS/fis/model.py", "build_briefing"): 24,
    ("FIS/fis/model.py", "build_system"): 33,
    ("FIS/fis/model.py", "system_poi"): 23,
    ("FIS/fis/science.py", "body_report"): 42,
    ("FIS/fis/science.py", "system_report"): 34,
    ("FIS/fis/server.py", "Handler._api"): 51,
    ("FIS/fis/server.py", "Handler._post_lost_hidden"): 16,
    ("FIS/fis/server.py", "Handler.do_POST"): 21,
    ("FIS/fis/shipview.py", "build_shipstatus"): 19,
    ("FIS/fis/unsold.py", "build_unsold"): 24,
    ("boxelplan.py", "Planner.build"): 43,
    ("journalscan.py", "WorkMeter.feed"): 19,
    ("overlay.py", "briefing_lines"): 16,
    ("surfacenav.py", "body_state"): 19,
    ("sysdb.py", "SystemDB._cmdr_carried"): 22,
    ("sysdb.py", "SystemDB._migrate"): 24,
    ("sysdb.py", "SystemDB._surface_event"): 16,
    ("sysdb.py", "SystemDB.ingest_journal_event"): 56,
    ("sysroute.py", "plan_route"): 18,
    ("sysroute.py", "resolve_positions"): 22,
}


def measure():
    """(file, function) -> complexity for everything above LIMIT."""
    found = {}
    for top, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(top, fn)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            with open(path, encoding="utf-8") as fh:
                tree = compile(fh.read(), path, "exec", ast.PyCF_ONLY_AST)
            visitor = mccabe.PathGraphingAstVisitor()
            visitor.preorder(tree, visitor)
            for graph in visitor.graphs.values():
                c = graph.complexity()
                if c > LIMIT:
                    found[(rel, graph.entity)] = c
    return found


def main() -> int:
    found = measure()
    bad = []
    for key, c in sorted(found.items()):
        allowed = LEGACY.get(key, LIMIT)
        if c > allowed:
            bad.append("%s %s: %d (allowed %d)" % (key[0], key[1], c, allowed))
    gone = sorted(k for k in LEGACY if k not in found)
    print("functions above %d: %d (listed legacy: %d)" % (LIMIT, len(found), len(LEGACY)))
    for line in bad:
        print("  [FAIL] " + line)
    if gone:
        print("  now at or below %d - remove from LEGACY: %s" % (LIMIT, ", ".join("%s %s" % k for k in gone)))
    print("complexity: %s" % ("all OK" if not bad else "%d FAILED" % len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
