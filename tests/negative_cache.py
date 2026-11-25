# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
F2 (5.1.0): the negative cache - "not in the galaxy map" kept with date,
the game's version and the reason; after a patch or ABSENT_DAYS the name is
asked again and a boxel it closed opens; a name a database knows is a
phantom (the map's fault), closes nothing and is not ruled out.

    python tests/negative_cache.py      (from the plugin folder)
"""
import calendar
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sysdb  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


db = sysdb.SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
db.ingest_journal_event({"event": "Fileheader", "timestamp": "2026-11-20T10:00:00Z", "gameversion": "4.4.2.1"})
check(db.get_meta("game_version") == "4.4.2.1", "the game's version from the Fileheader")

print("not there")
closes = db.mark_absent("Synuefe AB-C d1-5")
row = db.cx.execute("SELECT * FROM absent WHERE name='Synuefe AB-C d1-5'").fetchone()
check(closes and row["game_version"] == "4.4.2.1" and row["reason"] == "map" and row["ts"],
      "kept with date, version and reason; closes the boxel")
check("Synuefe AB-C d1-5" in db.absent_set(), "ruled out")
end = db.cx.execute("SELECT n2_end FROM boxels WHERE key=?", (row["boxel"],)).fetchone()["n2_end"]
check(end == 5, "the boxel ends at 5")

print("phantom")
db.upsert("Synuefe XY-Z d2-7", source="edsm")
known = db.known_elsewhere("synuefe xy-z d2-7")
check(known and "edsm" in known, "a name EDSM knows: %s" % known)
db.mark_phantom("Synuefe XY-Z d2-7", known)
check("Synuefe XY-Z d2-7" not in db.absent_set() and db.phantoms()[0]["name"] == "Synuefe XY-Z d2-7",
      "a phantom is not ruled out, and listed")
check(db.cx.execute("SELECT COUNT(*) FROM boxels WHERE key LIKE '%XY-Z%' AND n2_end IS NOT NULL").fetchone()[0] == 0,
      "it closes nothing")
check(db.known_elsewhere("Synuefe QQ-Q d9-9") is None, "an unknown name: no source")

print("asked again")
check(db.expire_absent() == 0, "same version, fresh: stays")
old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - (sysdb.ABSENT_DAYS + 1) * 86400))
db.mark_absent("Synuefe DE-F d3-2")
db.cx.execute("UPDATE absent SET ts=? WHERE name='Synuefe DE-F d3-2'", (old,))
check(db.expire_absent() == 1 and "Synuefe DE-F d3-2" not in db.absent_set(), "older than %d days: asked again"
      % sysdb.ABSENT_DAYS)
db.ingest_journal_event({"event": "LoadGame", "timestamp": "2026-12-01T10:00:00Z", "gameversion": "4.4.3.0"})
check("Synuefe AB-C d1-5" not in db.absent_set(), "a patch: the old version's entries asked again")
end = db.cx.execute("SELECT n2_end, complete FROM boxels WHERE key=?", (row["boxel"],)).fetchone()
check(end["n2_end"] is None and end["complete"] == 0, "the boxel it closed is open again")
check(len(db.phantoms()) == 1, "phantoms stay (they say something about the map)")
_ = calendar

print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
