# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Open biological signals (4.11.1, biosig.py): one signal per genus, but Brain
Trees can be several species on one body - the cases of the developer's
journals.

    python tests/biosig.py      (from the plugin folder)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import biosig  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


BT = "Brain Trees"


def done(*species):
    return [{"species": s, "genus": biosig.genus_of(s)} for s in species]


print("names")
check(biosig.species_name("Bacterium Acies - White") == "Bacterium Acies", "the variant goes")
check(biosig.genus_of("Lividum Brain Tree") == BT and biosig.genus_of("Stratum Tectonicas") == "Stratum",
      "genus from the species name")

print("Odyssey genera: signals minus species analysed, as before")
r = biosig.open_bio(3, ["Bacterium", "Stratum", "Fungoida"], done("Bacterium Acies"))
check(r["open"] == 2 and not r["multi"], "three genera, one analysed: 2 open")
check(biosig.open_bio(3, [], done("Bacterium Acies"))["open"] == 2, "before the DSS: 3 signals - 1")
check(biosig.open_bio(1, ["Stratum"], done("Stratum Tectonicas"))["open"] == 0, "done")

print("Brain Trees: one signal, several species")
# Synuefe ML-L b41-5 3 a, 13.11.2026: Lividum analysed, Roseum only in the codex
r = biosig.open_bio(1, [BT], done("Lividum Brain Tree"), ["Lividum Brain Tree", "Roseum Brain Tree"])
check(r["open"] == 1 and r["open_species"] == ["Roseum Brain Tree"] and r["multi"] == [BT],
      "one analysed, one more seen: still open (was 'done' up to 4.11.0)")
# HIP 31189 A 1 d, 05.11.2026: three species, all analysed
three = ["Gypseeum Brain Tree", "Roseum Brain Tree", "Lividum Brain Tree"]
check(biosig.open_bio(1, [BT], done(*three), three)["open"] == 0, "three seen, three analysed: done")
check(biosig.open_bio(1, [BT], [], [])["open"] == 1, "signalled, nothing seen yet: 1 open")
check(biosig.open_bio(1, [BT], [], ["Roseum Brain Tree", "Lividum Brain Tree"])["open"] == 2,
      "two seen, none analysed: 2 open")
check(biosig.open_bio(2, [BT, "Bacterium"], done("Bacterium Vesicula"), [])["open"] == 1,
      "with an Odyssey genus beside it")
print("before the DSS (genera unknown)")
check(biosig.open_bio(1, [], done("Lividum Brain Tree"), ["Lividum Brain Tree", "Roseum Brain Tree"])["open"] == 1,
      "the codex shows a second species")
check(biosig.open_bio(1, [], [], ["Roseum Brain Tree"])["open"] == 1, "seen only: counted once, not twice")
check(biosig.open_bio(2, [], [], ["Roseum Brain Tree", "Lividum Brain Tree"])["open"] == 3,
      "two signals, two brain trees seen: the other genus plus both species")

print("the plugin's panel line (sysdb.system_progress) from journal events")
import tempfile  # noqa: E402
from sysdb import SystemDB, CURRENT  # noqa: E402

A, BODY = 11673318073697, 10


def ev(t, name, **kw):
    return dict({"timestamp": "2026-11-13T16:%02d:00Z" % t, "event": name}, **kw)


with tempfile.TemporaryDirectory() as d:
    db = SystemDB(os.path.join(d, "t.sqlite"))
    db.set_commander("F1", "Tester")
    for e in (ev(0, "FSDJump", StarSystem="Synuefe ML-L b41-5", SystemAddress=A, StarPos=[1.0, 2.0, 3.0]),
              ev(1, "Scan", StarSystem="Synuefe ML-L b41-5", SystemAddress=A, BodyID=BODY,
                 BodyName="Synuefe ML-L b41-5 3 a", PlanetClass="Rocky body", Landable=True,
                 ScanType="Detailed", DistanceFromArrivalLS=800.0),
              ev(2, "SAASignalsFound", SystemAddress=A, BodyID=BODY, BodyName="Synuefe ML-L b41-5 3 a",
                 Signals=[{"Type": "$SAA_SignalType_Biological;", "Count": 1}],
                 Genuses=[{"Genus": "$Codex_Ent_Brancae_Name;", "Genus_Localised": "Brain Trees"}]),
              ev(3, "CodexEntry", Name="$Codex_Ent_SeedEFGH_Name;", Name_Localised="Lividum Brain Tree",
                 SubCategory_Localised="Organic structures", Category_Localised="Biological and Geological",
                 System="Synuefe ML-L b41-5", SystemAddress=A, BodyID=BODY, Latitude=-45.3, Longitude=10.0),
              ev(4, "ScanOrganic", ScanType="Analyse", Genus="$Codex_Ent_Brancae_Name;", Genus_Localised="Brain Trees",
                 Species_Localised="Lividum Brain Tree", Variant_Localised="Lividum Brain Tree",
                 SystemAddress=A, Body=BODY),
              ev(5, "CodexEntry", Name="$Codex_Ent_Seed_Name;", Name_Localised="Roseum Brain Tree",
                 SubCategory_Localised="Organic structures", Category_Localised="Biological and Geological",
                 System="Synuefe ML-L b41-5", SystemAddress=A, BodyID=BODY, Latitude=-45.1, Longitude=10.2)):
        db.ingest_journal_event(e)
    p = db.system_progress(A, CURRENT)
    check(p["bio_signals_open"] == 1 and p["bio_open"] == ["Synuefe ML-L b41-5 3 a"],
          "one signal, Lividum analysed, Roseum seen: 1 open (was 0 up to 4.11.0) %r"
          % ((p["bio_signals_open"], p["bio_open"]),))
    db.ingest_journal_event(ev(6, "ScanOrganic", ScanType="Analyse", Genus_Localised="Brain Trees",
                               Species_Localised="Roseum Brain Tree", SystemAddress=A, Body=BODY))
    p = db.system_progress(A, CURRENT)
    check(p["bio_signals_open"] == 0 and p["bio_open"] == [], "both analysed: done")
    db.cx.close()

print("biosig: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
