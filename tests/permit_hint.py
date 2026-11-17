# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Permit hint (5.0, PM1): sphere targets that EDDiscovery lists as permit-
locked get "permit (EDD)" in their detail - they stay in the plan, the
game decides. Switched off with the EDD source.

    python tests/permit_hint.py      (from the plugin folder)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import planning, state  # noqa: E402
from SHBOXSEARCH.boxelplan import K_NEW, K_PROBE, Target  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


class FakeEDD:
    def permit_ids(self):
        return {111, 333}


class FakeSources:
    sources = {"edd": FakeEDD()}


ST = state.ST
cfg = {}
plugin_pkg.use_settings(cfg)
ST.sources = FakeSources()
plan = {"flight": [Target("Locked A", K_NEW, 5.0, id64=111, detail="12 bodies"), Target("Open B", K_NEW, 6.0, id64=222)],
        "probe": [Target("Locked C", K_PROBE, 7.0, id64=333), Target("Unknown D", K_PROBE, 8.0)]}
n = planning._mark_permits(plan)
check(n == 2, "two targets on EDD's permit list (%d)" % n)
check(plan["flight"][0].detail == "12 bodies, permit (EDD)", "the note follows the detail: %r" % plan["flight"][0].detail)
check(plan["probe"][0].detail == "permit (EDD)" and not plan["flight"][1].detail and not plan["probe"][1].detail,
      "only the listed ones; none without an id64")
check(len(plan["flight"]) == 2 and len(plan["probe"]) == 2, "nothing removed - a hint, not a ban")
planning._mark_permits(plan)
check(plan["flight"][0].detail.count("permit (EDD)") == 1, "marked once, also when the plan is marked again")
cfg[state.CFG["src_edd"]] = False
plan2 = {"flight": [Target("Locked A", K_NEW, 5.0, id64=111)], "probe": []}
check(planning._mark_permits(plan2) == 0 and not plan2["flight"][0].detail, "EDD switched off: no hint")
print("permit hint: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
