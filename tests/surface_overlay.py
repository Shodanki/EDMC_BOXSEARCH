# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The overlay on the ground (4.12): landed in the Rhino the compass to the
ship stays on screen while Status.json is quiet (it used to run out after
4 s and came back only when a side panel was opened), the route block steps
aside on the ground and comes back on lift-off, the compass goes when you
leave the body - and mining and the ground each lift only their own reason.

    python tests/surface_overlay.py      (from the plugin folder)
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import panel, state  # noqa: E402
from SHBOXSEARCH.overlay import CockpitOverlay  # noqa: E402
from SHBOXSEARCH.sysdb import SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


class Client:
    """Records what the overlay sends, by block."""

    def __init__(self):
        self.sent = []

    def send_message(self, mid, text, colour, x, y, ttl=4, size="normal"):
        self.sent.append((mid, text, ttl))

    def shown(self, group):
        """The block's lines with text, from the last time it was drawn."""
        last = {}
        for mid, text, _ttl in self.sent:
            if mid.startswith("shbox-%s-" % group):
                last[mid] = text
        return [t for t in last.values() if t]


class Frame:
    """panel._frame: after() only queues - the test runs the timers."""

    def __init__(self):
        self.timers = []

    def after(self, ms, fn):
        self.timers.append((ms, fn))

    def run(self):
        todo, self.timers = self.timers, []
        for _ms, fn in todo:
            fn()


clock = [1_800_000_000.0]
time.time = lambda: clock[0]
ST = state.ST
ST.db = SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
ST.cur_id64 = 42
client = Client()
ST.overlay = CockpitOverlay(client=client)
frame = Frame()
panel._frame = frame
ST.db.ingest_journal_event({"event": "Touchdown", "timestamp": "2027-01-15T08:00:00Z", "SystemAddress": 42,
                            "Body": "Test A 1", "BodyID": 5, "Latitude": 10.0, "Longitude": 20.0,
                            "PlayerControlled": True})
ST.db.ingest_journal_event({"event": "LaunchSRV", "timestamp": "2027-01-15T08:01:00Z",
                            "SRVType": "combat_multicrew_srv_01", "SRVType_Localised": "SRV Rhino"})
ST.overlay.show_targets(None, [])
ST.overlay._last_targets = [("NEXT TARGETS", "#fff"), ("1 Test A 2", "#fff")]
ST.overlay.draw("targets", ST.overlay._last_targets, ttl=900)

SRV, LANDED, IN_SHIP = 1 << 26, 2, 1 << 24


def status(flags, lat=10.01, lon=20.0, alt=0.0, body="Test A 1"):
    e = {"event": "Status", "timestamp": "2027-01-15T08:05:00Z", "Flags": flags, "Flags2": 0,
         "GuiFocus": 0}
    if lat is not None:
        e.update(Latitude=lat, Longitude=lon, Altitude=alt, BodyName=body, PlanetRadius=1_500_000.0)
    load.dashboard_entry("Cmdr", False, e)


print("in the Rhino on the ground")
status(SRV)
nav = client.shown("nav")
check(nav and any("SHIP" in t.upper() for t in nav), "the compass points to the ship (%s)" % nav[:2])
check(ST.overlay.mute_targets and client.shown("targets") == [], "the route block stepped aside")
check(len(frame.timers) == 1, "one redraw timer runs")

print("standing still: Status.json writes nothing for a minute")
before = len([s for s in client.sent if s[0].startswith("shbox-nav-")])
for _ in range(30):
    clock[0] += 2.0
    frame.run()
after = len([s for s in client.sent if s[0].startswith("shbox-nav-")])
check(after > before + 25, "the compass is sent again while nothing changes (%d -> %d)" % (before, after))
check(len(frame.timers) == 1, "still exactly one timer")
check(client.shown("nav") == nav, "the same lines - the position has not changed")

print("mining and the ground lift only their own reason")
ST.overlay.mute_route(True, "mining")
ST.overlay.mute_route(False, "surface")
check(ST.overlay.mute_targets, "mining still hides the route after the ground let go")
ST.overlay.mute_route(False, "mining")
check(not ST.overlay.mute_targets and client.shown("targets"), "both gone: the route is back")
status(SRV)
check(ST.overlay.mute_targets, "on the ground again: hidden again")

print("lift off and leave")
clock[0] += 2.0
status(IN_SHIP, alt=40_000.0)
check(not ST.overlay.mute_targets and client.shown("targets"), "lifted off: the route block is back")
frame.run()
check(frame.timers == [], "high above the body: the redraw timer stops")
clock[0] += 2.0
status(SRV)
clock[0] += 2.0
status(IN_SHIP, lat=None)
check(client.shown("nav") == [] and ST._nav_args is None, "away from the body: the compass is gone")
frame.run()
check(frame.timers == [], "and no timer left")

print("surface overlay: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
