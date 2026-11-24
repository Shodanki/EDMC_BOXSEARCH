# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Bio display, variant 1 (5.1.0, user 24.11.2026): every collectable bio of a
body - finished paler, begun as before, not started violet - in the FIS's
PLANET; in the overlay finished species paler with "✓" (the own window
strikes them through), and a switch that hides them. One state logic for
both: biosig.species_rows.

  * species_rows: order finished / begun / not started, a genus none of
    whose species is done or begun, Brain Trees seen in the codex;
  * a replay: ScanOrganic names the body by "Body" (its BodyID), the DSS
    the genera - the FIS's PLANET lists them with values from own sales;
  * the overlay's compass block with and without the switch, and the own
    overlay window drawing the line struck through.

    python tests/bio_display.py      (from the plugin folder)
"""
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "FIS"))
import plugin_pkg  # noqa: E402
plugin_pkg.import_plugin()
from SHBOXSEARCH import biosig, overlaywin, sysdb  # noqa: E402
from SHBOXSEARCH.surfacenav import compass_lines  # noqa: E402
from SHBOXSEARCH.sysdb import SystemDB  # noqa: E402

fails = 0
sys.stdout.reconfigure(errors="backslashreplace")      # a Windows console cannot print every mark


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


print("one state logic: biosig.species_rows")
rows = biosig.species_rows([{"species": "Bacterium Cerbrus", "genus": "Bacterium"}],
                           [{"species": "Stratum Tectonicas - Green", "genus": "Stratum", "samples": 2}],
                           ["Bacterium", "Stratum", "Tussock", "Brain Trees"],
                           ["Roseum Brain Tree - Pink"])
check([(r["species"], r["state"], r["samples"]) for r in rows]
      == [("Bacterium Cerbrus", "done", 3), ("Stratum Tectonicas", "begun", 2),
          ("Roseum Brain Tree", "todo", 0), (None, "todo", 0)],
      "finished, begun, not started (%r)" % [(r["species"] or r["genus"], r["state"]) for r in rows])
check(rows[3]["genus"] == "Tussock", "a genus nobody started: a row without a species")
bt = biosig.species_rows([], [], ["Brain Trees"], ["Roseum Brain Tree", "Lividum Brain Tree"])
check([r["species"] for r in bt] == ["Roseum Brain Tree", "Lividum Brain Tree"],
      "Brain Trees: every species the codex saw, the genus not again")

print("a replay: ScanOrganic names the body by its BodyID")
A = 8008
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
    ev = [{"timestamp": "2026-11-20T10:00:00Z", "event": "Commander", "FID": "F9", "Name": "Tester"},
          {"timestamp": "2026-11-20T10:00:01Z", "event": "LoadGame", "FID": "F9", "Commander": "Tester"},
          {"timestamp": "2026-11-20T10:01:00Z", "event": "FSDJump", "StarSystem": "Bio Sys", "SystemAddress": A,
           "StarPos": [3.0, 0.0, 0.0]},
          {"timestamp": "2026-11-20T10:02:00Z", "event": "Scan", "ScanType": "Detailed", "StarSystem": "Bio Sys",
           "SystemAddress": A, "BodyName": "Bio Sys 5 a", "BodyID": 12, "PlanetClass": "Rocky body",
           "Radius": 1500000.0, "Landable": True, "DistanceFromArrivalLS": 500.0},
          {"timestamp": "2026-11-20T10:03:00Z", "event": "SAASignalsFound", "SystemAddress": A,
           "BodyName": "Bio Sys 5 a", "BodyID": 12,
           "Signals": [{"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 3}],
           "Genuses": [{"Genus_Localised": g} for g in ("Bacterium", "Stratum", "Tussock")]}]
    for kind in ("Log", "Sample", "Sample", "Analyse"):
        ev.append({"timestamp": "2026-11-20T10:1%d:00Z" % len(ev), "event": "ScanOrganic", "ScanType": kind,
                   "SystemAddress": A, "Body": 12, "Genus_Localised": "Bacterium",
                   "Species_Localised": "Bacterium Cerbrus", "Variant_Localised": "Bacterium Cerbrus - Teal"})
    ev.append({"timestamp": "2026-11-20T11:00:00Z", "event": "SellOrganicData", "MarketID": 1, "BioData": [
        {"Species_Localised": "Bacterium Cerbrus", "Value": 1689800, "Bonus": 0},
        {"Species_Localised": "Tussock Pennata", "Value": 5853800, "Bonus": 0},
        {"Species_Localised": "Tussock Ventusa", "Value": 3227700, "Bonus": 0}]})
    with open(os.path.join(d, "Journal.2026-11-20T100000.01.log"), "w", encoding="utf-8") as fh:
        for e in ev:
            fh.write(json.dumps(e) + "\n")
    path = os.path.join(d, "p.sqlite")
    db = SystemDB(path)
    db.set_meta(sysdb.CMDR_READY, "2026-11-01T00:00:00Z")
    db.import_journals(d)
    db.cx.close()
    sys.path.insert(0, os.path.dirname(HERE))          # the FIS imports the plugin's modules plainly
    from fis import model
    from fis.data import Database
    from fis.fleet import Archive
    out = {"body": "Bio Sys 5 a", "id64": A, "bio": [
        {"species": "Stratum Tectonicas", "genus": "Stratum", "samples": 2, "points": [[1, 1]], "done": False}]}
    model._surface_bio_all(Database(path), Archive(d), out)
    got = [(r["species"] or r["genus"], r["state"], r.get("value"), bool(r.get("est")))
           for r in out["bio_all"]["rows"]]
    check(got == [("Bacterium Cerbrus", "done", 1689800, False), ("Stratum Tectonicas", "begun", None, False),
                  ("Tussock", "todo", 4540750, True)],
          "PLANET: analysed by BodyID, begun, not started with ~ the mean of its genus (%r)" % got)
    check(out["bio_all"]["signals"] == 3, "three signals")

print("overlay: finished species paler, struck through in the own window")
marks = [{"ts": "1", "kind": "touchdown", "label": "b", "detail": None, "lat": 0.0, "lon": 0.0},
         {"ts": "2", "kind": "bio_log", "label": "Bacterium Cerbrus", "detail": "Bacterium", "lat": 0.001, "lon": 0.0},
         {"ts": "3", "kind": "bio_analyse", "label": "Bacterium Cerbrus", "detail": "Bacterium",
          "lat": 0.002, "lon": 0.0},
         {"ts": "4", "kind": "bio_log", "label": "Stratum Tectonicas", "detail": "Stratum", "lat": 0.003, "lon": 0.0}]
COL = {"head": "H", "data": "D", "warn": "W", "dim": "M", "new": "N"}
here = {"lat": 0.0, "lon": 0.0, "heading": 0.0}
lines = compass_lines(here, marks, 400000.0, sig_bio=3, genera=["Bacterium", "Stratum", "Tussock"], colours=COL)
done = [ln for ln in lines if ln[0].startswith(biosig.DONE_MARK)]
check(done == [(biosig.DONE_MARK + "Bacterium Cerbrus 3/3", "M")], "one pale ✓ line for the finished species (%r)"
      % lines)
check(any(ln[0].startswith("Stratum Tectoni 1/3") and ln[1] == "N" for ln in lines), "the begun species as before")
hid = compass_lines(here, marks, 400000.0, sig_bio=3, genera=["Bacterium", "Stratum", "Tussock"], colours=COL,
                    hide_done=True)
check(not any(biosig.DONE_MARK in ln[0] or "Bacterium Cerbrus" in ln[0] for ln in hid[1:]),
      "switch on: the finished species is left out (%r)" % hid)


class Canvas:
    def __init__(self):
        self.texts = []

    def delete(self, what):
        self.texts = []

    def create_text(self, x, y, **kw):
        self.texts.append((kw["text"], kw["font"]))


class Top:
    def deiconify(self):
        pass

    def withdraw(self):
        pass

    def after(self, ms, fn):
        pass


cv = Canvas()
q = []
client = overlaywin.WindowClient(q.append, root=lambda: "root", in_front=lambda: True,
                                 window_factory=lambda root: (Top(), cv, 1280, 960), clock=lambda: 1000.0)
client.send_message("nav-1", biosig.DONE_MARK + "Bacterium Cerbrus 3/3", "M", 10, 10, ttl=10, size="normal")
client.send_message("nav-2", "Stratum Tectonicas 1/3", "N", 10, 30, ttl=10, size="normal")
while q:
    q.pop()()
fonts = dict(cv.texts)
check(fonts.get("Bacterium Cerbrus 3/3", ("",))[-1] == "overstrike", "own window: drawn struck through, no ✓")
check(len(fonts.get("Stratum Tectonicas 1/3", ())) == 2, "other lines unchanged")
check(threading.current_thread() is threading.main_thread(), "drawn on the main thread")

print("bio display: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
