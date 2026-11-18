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

print("on foot aboard the own carrier, parked beside a planet")
# developer's journal 14.11.2026: Docked at a FleetCarrier, then Disembark
# with OnPlanet true - and Status.json carries the planet's latitude
ST.db.ingest_journal_event({"event": "Docked", "timestamp": "2027-01-15T09:00:00Z", "StationName": "V2L-07J",
                            "StationType": "FleetCarrier", "StarSystem": "Test", "SystemAddress": 42,
                            "MarketID": 3712967680})
marks_before = len(ST.db.marks_of(42, "Test A 1"))
ST.db.ingest_journal_event({"event": "Disembark", "timestamp": "2027-01-15T09:01:00Z", "SRV": False,
                            "StarSystem": "Test", "SystemAddress": 42, "Body": "Test A 1", "BodyID": 5,
                            "OnStation": False, "OnPlanet": True})
check(len(ST.db.marks_of(42, "Test A 1")) == marks_before, "no 'on foot' mark on the planet for a walk in the hangar")
client.sent.clear()
FOOT = 1
e = {"event": "Status", "timestamp": "2027-01-15T09:01:05Z", "Flags": 0, "Flags2": FOOT, "GuiFocus": 0,
     "Latitude": 10.0, "Longitude": 20.0, "Altitude": 0.0, "BodyName": "Test A 1", "PlanetRadius": 1_500_000.0}
load.dashboard_entry("Cmdr", False, e)
check(client.shown("nav") == [] and not ST.overlay.mute_targets, "no compass, the route block stays")
ST.db.ingest_journal_event({"event": "Undocked", "timestamp": "2027-01-15T09:10:00Z", "StationName": "V2L-07J",
                            "StationType": "FleetCarrier", "MarketID": 3712967680})
check(not ST.db.aboard_station(), "undocked: the surface counts again")
check(ST.db.aboard_station(1 << 3), "on foot in a station (Flags2): not the surface either")

print("the Rhino dropped from a hover: the ship waits, then leaves at 2.3 km")
R_B = 1_500_000.0
DEG = 180.0 / 3.141592653589793 / R_B          # one metre in degrees


def at(flags, lat, ts, alt=0.0):
    e = {"event": "Status", "timestamp": ts, "Flags": flags, "Flags2": 0, "GuiFocus": 0, "Latitude": lat,
         "Longitude": 0.0, "Altitude": alt, "BodyName": "Test B 1", "PlanetRadius": R_B}
    load.dashboard_entry("Cmdr", False, e)


clock[0] += 60
ST.db.ingest_journal_event({"event": "ApproachBody", "timestamp": "2027-01-15T09:58:00Z", "StarSystem": "Test",
                            "SystemAddress": 42, "Body": "Test B 1", "BodyID": 6})
at(IN_SHIP, 0.0, "2027-01-15T10:00:00Z", alt=8.0)              # hovering just above the ground
ST.db.ingest_journal_event({"event": "LaunchSRV", "timestamp": "2027-01-15T10:00:02Z", "SystemAddress": 42,
                            "SRVType": "mev_rhino", "SRVType_Localised": "SRV Rhino"})
client.sent.clear()
clock[0] += 2
at(SRV, 500 * DEG, "2027-01-15T10:01:00Z")
nav = client.shown("nav")
check(any(t.startswith("SHIP (hover)") for t in nav), "500 m away: the hovering ship waits (%s)" % nav[1:2])
clock[0] += 2
at(SRV, 2400 * DEG, "2027-01-15T10:05:00Z")
kinds = [m["kind"] for m in ST.db.marks_of(42, "Test B 1")]
check("ship_gone" in kinds, "2.4 km away: the moment it left is stored (%s)" % kinds)
clock[0] += 2
at(SRV, 100 * DEG, "2027-01-15T10:06:00Z")
nav = client.shown("nav")
check(any(t.startswith("SHIP AWAY") for t in nav) and not any(t.startswith("SHIP (hover)") for t in nav),
      "back near the drop point: still away - recall it (%s)" % nav[1:2])

print("own-3 round 2: the left line through the hooks (Nomad, ship, SRV)")
load.journal_entry("Cmdr", False, "Test", "Test B 1",
                   {"event": "LaunchVessel", "timestamp": "2027-01-15T10:07:00Z", "VesselType": "lander01",
                    "VesselType_Localised": "Nomad", "ID": 49, "PlayerControlled": True}, {"FID": "F1"})
client.sent.clear()
clock[0] += 2
at(203424076, 0.0, "2027-01-15T10:07:30Z", alt=25.0)          # the user's real Status.json, 18.11. 19:09 UTC
check(client.shown("state") == ["NOMAD GEAR DOWN · HARDPOINTS OUT · LIGHTS ON"],
      "the Nomad flying low: gear, hardpoints, lights (%s)" % client.shown("state"))
real_status = state.ST.mine.status
state.ST.mine.status = lambda e: 1 / 0                          # a failing step before it
client.sent.clear()
clock[0] += 2
at(IN_SHIP | (1 << 2), 0.0, "2027-01-15T10:08:00Z", alt=40.0)
check(client.shown("state") == ["SHIP  GEAR DOWN"], "a failing mining step no longer hides it (%s)"
      % client.shown("state"))
state.ST.mine.status = real_status
load.journal_entry("Cmdr", False, "Test", "Test B 1",
                   {"event": "LaunchSRV", "timestamp": "2027-01-15T10:09:00Z", "SRVType": "testbuggy",
                    "SRVType_Localised": "SRV Scarab", "ID": 50, "PlayerControlled": True}, {"FID": "F1"})
clock[0] += 2
at(SRV | (1 << 8), 0.0, "2027-01-15T10:09:30Z")
check(client.shown("state") == ["SRV   LIGHTS ON"], "the SRV with its lights on (%s)" % client.shown("state"))

print("surface overlay: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
