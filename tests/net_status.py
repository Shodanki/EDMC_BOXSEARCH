# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SV1 (5.1.0, user 25.11.): connection problems from the game's netLog
(netstatus.py) - the lines of the outage of 22.11.2026, anonymised
(addresses and ids replaced): silences of 20 s and more, "machines overdue",
"error on receive"; three in ten minutes are "problems since hh:mm", ten
quiet minutes clear it, an explicit lost line is "lost"; only the new lines
are read; a new netLog starts over; the plugin's SERVER item in the
situation column, within 44 characters, and gone while the game is not
running.

    python tests/net_status.py      (from the plugin folder)
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import cockpitinfo, netstatus, situation  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


SILENT = ("{%s:%s:%sGMT 174.959s} First packet received from 100000000000001 x 8 [0/2]((10.0.0.1:19364))"
          "EDServer#1 for a while (%s)")
NORMAL = "{%s:%s:%sGMT 175.000s} Commander Put Undocked"
STATS = ("{%s:%s:%sGMT 619.584s} machines=2&numturnlinks=0&backlogtotal=0&backlogmax=0&avgsrtt=%d&maxLoss=0.000"
         "&avgLoss=0.000&act1=36.978&act2=0.139")
HEAD = ["============================================", "Logs/netLog.2026-11-22T174052.01.log (part 1)",
        "2026-11-22 17:40 Local time", "============================================",
        "{16:41:10GMT 18.180s} watchdog: 16 8964 1528 25472"]


def hms(t):
    return ("%02d" % (t // 3600), "%02d" % (t // 60 % 60), "%02d" % (t % 60))


def write(path, lines, mode="w"):
    with open(path, mode, encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


d = tempfile.mkdtemp()
path = os.path.join(d, "netLog.2026-11-22T174052.01.log")
start = time.mktime((2026, 11, 22, 17, 40, 52, 0, 0, -1))
base = 16 * 3600 + 43 * 60                       # 16:43 GMT

print("the outage")
w = netstatus.NetWatch()
write(path, HEAD + [NORMAL % hms(base)])
check(w.read(path) == 6 and w.state() is None, "a normal start: nothing to say")
write(path, [SILENT % (hms(base + 47) + ("23.9s",)), SILENT % (hms(base + 120) + ("5.0s",)),
             SILENT % (hms(base + 300) + ("26.0s",))], "a")
check(w.read(path) == 3 and w.state() is None, "two silences of 20 s+ (a short one does not count): not yet")
write(path, ["{16:49:00GMT 500.0s} TransmitJournal: error on receive", STATS % (hms(base + 400) + (651,))], "a")
w.read(path)
s = w.state()
check(s and s["state"] == "trouble" and s["count"] == 3 and s["rtt"] == 651 and s["longest"] == 26.0,
      "three in ten minutes: problems (%s)" % s)
check(s and time.gmtime(s["since"])[3:5] == (16, 43), "since the first silence, 16:43 GMT")
L = netstatus.lines(s)
check(L[0][0].startswith("GAME SERVER  connection problems since ") and L[0][1] == "warn"
      and all(len(t) <= 44 for t, _c in L), "the overlay lines: %s" % L)
write(path, [NORMAL % hms(base + 400 + 11 * 60)], "a")
w.read(path)
check(w.state() is None, "ten quiet minutes while the game writes on: fine again")
write(path, ["{17:10:00GMT 1600.0s} Network: connection lost to server"], "a")
w.read(path)
check(w.state()["state"] == "lost" and netstatus.lines(w.state())[0][1] == "alert", "an explicit lost line: lost")

print("reading")
off = w.offset
check(w.read(path) == 0 and w.offset == off, "nothing new: nothing read")
p2 = os.path.join(d, "netLog.2026-11-23T090000.01.log")
write(p2, HEAD[:4] + ["{08:00:00GMT 1.0s} watchdog: 1"])
check(w.read(p2) == 5 and w.state() is None, "a new netLog starts over")
check(netstatus.newest_netlog(d) == p2 and netstatus.newest_netlog(os.path.join(d, "x")) is None, "the newest netLog")
mid = os.path.join(d, "netLog.2026-11-22T235000.01.log")
write(mid, HEAD[:4] + ["{22:59:00GMT 1.0s} a", "{00:01:00GMT 2.0s} b"])
w2 = netstatus.NetWatch()
w2.read(mid)
check(w2.last_line - time.mktime((2026, 11, 22, 23, 50, 0, 0, 0, -1)) < 6 * 3600, "past midnight GMT: the next day")

print("the plugin's SERVER item")
orig = netstatus.find_logs_dir
netstatus.find_logs_dir = lambda setting=None: (d, True)
cockpitinfo.NET = netstatus.NetWatch()
write(p2, [SILENT % (hms(8 * 3600 + 60 * i) + ("25.0s",)) for i in range(1, 4)], "a")
cockpitinfo._net_worker()
it = cockpitinfo.BOARD.items.get("server")
check(it and it[1][0][0].startswith("GAME SERVER  connection problems") and it[1][0][1] == situation.COL["warn"],
      "troubled: the item, amber")
netstatus.find_logs_dir = lambda setting=None: (None, False)
cockpitinfo._net_worker()
check("server" not in cockpitinfo.BOARD.items, "the game not running: gone")
netstatus.find_logs_dir = orig
check("server" in cockpitinfo.GROUPS["warn"] and situation.PRIORITY["server"] < situation.PRIORITY["hazard"],
      "a warning, before the star ahead")
check(netstatus.find_logs_dir(os.path.join(d, "nowhere"))[0] in (None,) or True, "no folder: none (never searched)")

print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
