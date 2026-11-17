# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The overlay's situation column (4.12: bodyvalue.py, situation.py,
cockpitinfo.py): the value formula, the board (priority, time on show,
line limit), every text within 44 characters, the models fed from the
journal, and the plugin end to end - journal events and Status.json in,
lines in the corner across from the other blocks out.

    python tests/situation.py      (from the plugin folder)
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import bodyvalue, cockpitinfo, maintenance, situation, state, uithread  # noqa: E402
from SHBOXSEARCH.overlay import ANCHORS, CockpitOverlay  # noqa: E402
from SHBOXSEARCH.sysdb import CMDR_READY, SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


print("the value formula")
elw = bodyvalue.planet_value("Earthlike body", None, 1.0, first=True, mapped=True, first_map=True)
check(4_400_000 < elw < 4_470_000, "earth-like, first discovered and mapped: about 4.43 M (%d)" % elw)
check(bodyvalue.planet_value("Icy body", None, 0.01) == 500, "a small icy body: the minimum of 500")
check(bodyvalue.star_value("N", 1.4) > 20_000 > bodyvalue.star_value("K", 0.7), "a neutron star pays more than a K star")
no_mass = bodyvalue.body_values({"kind": "Planet", "planet_class": "Water world", "terraform": None, "mass_em": None,
                                 "was_discovered": 1, "was_mapped": 1, "mapped": 0})
check(no_mass["mapped"] > no_mass["now"] > 100_000, "mass not known: a typical mass of the class (%s)" % no_mass)
rows = [{"kind": "Star", "star_type": "K", "stellar_mass": 0.7, "was_discovered": 0, "scanned": 1},
        {"kind": "Planet", "planet_class": "Earthlike body", "terraform": None, "mass_em": 1.0,
         "was_discovered": 0, "was_mapped": 0, "mapped": 0, "scanned": 1},
        {"kind": "Planet", "planet_class": "Icy body", "terraform": None, "mass_em": 0.01,
         "was_discovered": 0, "was_mapped": 0, "mapped": 0, "scanned": 1},
        {"kind": "Planet", "planet_class": "Rocky body", "terraform": None, "mass_em": 0.01, "scanned": 0}]
s = bodyvalue.system_summary(rows, body_count=5)
check((s["scanned"], s["new"], s["to_map"], s["first_map"], s["notable"]) == (3, 3, 1, 1, {"Earthlike body": 1}),
      "system: 3 of 5 scanned, all new, the earth-like worth mapping (%s)" % s)

print("the board")
b = situation.Board()
b.put("session", [("S", "#fff")], 20, 100.0)
b.put("hazard", [("H", "#fff")], 10, 100.0)
b.put("system", [("Y%d" % i, "#fff") for i in range(8)], 30, 100.0)
check([t for t, _c in b.lines(101.0)][:2] == ["H", "S"] or [t for t, _c in b.lines(101.0)][0] == "H",
      "a warning goes first")
check(len(b.lines(101.0)) <= situation.MAX_LINES and [t for t, _c in b.lines(101.0)] == ["H"] + ["Y%d" % i for i in range(8)],
      "an item that no longer fits is left out whole: %s" % [t for t, _c in b.lines(101.0)])
check([t for t, _c in b.lines(111.0)][0] == "Y0", "the warning is gone after its time")
check(b.refresh("system", [("Z", "#fff")]) and b.items["system"][2] == 130.0, "new lines, the same time left")
check(not b.refresh("ring", [("R", "#fff")]), "nothing to refresh when it is not on show")
check([t for t, _c in b.lines(111.0, enabled=["session"])] == ["S"], "only the items switched on")

print("the texts: at most 44 characters")
long_name = "Synuefe ML-L b41-5 ABCDEFGHIJ 11 a"
texts = []
texts += situation.hazard_lines("N") + situation.hazard_lines("DAV") + situation.hazard_lines("H")
texts += situation.risk_lines({"systems": 123, "bodies": 4567, "first": 890, "species": 45, "value": 9.9e9},
                              "interdiction")
texts += situation.carrier_lines(long_name, 2000.0, 1000.0, ly=499.9, tritium=1234, tank=1000)
texts += situation.route_lines(99, ("SCOOP at the latest jump 12/99 K (+3)", "warn"))
texts += situation.landing_lines({"short": long_name, "gravity_g": 3.21, "temp_k": 1234.0,
                                  "atmosphere": "Thick sulphur dioxide atmosphere rich in argon",
                                  "open_genera": [("Stratum", 19_010_800), ("Bacterium", 1_000_000),
                                                  ("Fonticulua", 1_500_000), ("Osseus", None), ("Tussock", 7e6)],
                                  "finds": ["Geological x12", "Guardian x3", "Planetary mining location"]})
texts += situation.system_lines({"scanned": 123, "body_count": 456, "value": 1.23e9, "new": 99,
                                 "notable": {"Earthlike body": 2, "Water world": 13, "Ammonia world": 1,
                                             "terraformable": 22},
                                 "to_map": 33, "map_gain": 9.9e8, "first_map": 31})
texts += situation.ring_lines("Synuefe ML-L b41-5 2 A Ring", [("Low Temperature Diamonds", 3), ("Platinum", 2)],
                              {"low temperature diamonds": 120_000.0})
texts += situation.boxel_lines("Synuefe ML-L b41", 456, 457, 123)
texts += situation.session_lines({"jumps": 999, "scanned": 9999, "first": 999, "mapped": 999, "species": 99,
                                  "earned": 2.5e9}, sold=1.2e9)
over = [t for t, _c in texts if len(t) > 44]
check(not over, "%d lines, none longer than 44 (%s)" % (len(texts), over))
check(not any(ch in t for t, _c in texts for ch in "⚠≈★"), "no symbols an overlay font may lack")
check(situation.landing_lines({"short": "1 a", "gravity_g": 2.5})[0][1] == situation.COL["warn"]
      and situation.landing_lines({"short": "1 a", "gravity_g": 3.2})[0][1] == situation.COL["alert"],
      "high gravity amber, very high red")
bio = situation.landing_lines({"short": "1 a", "open_genera": [("Bacterium", 1_000_000), ("Stratum", 19_010_800)]})
check(bio[1][0].startswith("BIO  Stratum 19.0 M"), "the best paid genus first: %s" % bio[1][0])
car = situation.carrier_lines("Colonia", 1000.0 + 754, 1000.0, ly=500.0, tritium=120, tank=100)
short_line = ("         500 ly · needs ~120 t · has 100 t", situation.COL["alert"])
check(car[0][0] == "CARRIER  12:34  -> Colonia" and car[1] == short_line,
      "countdown, and red when the tank holds less than the jump needs: %s" % car)
check(situation.tritium_t(500.0, 10_000) == 93, "tritium: 5 + 500 x 35000 / 200000 = 92.5 -> 93 t")

print("the models")
ses = situation.Session()
for e in ({"event": "FSDJump"}, {"event": "Scan", "SystemAddress": 1, "BodyID": 1, "WasDiscovered": False},
          {"event": "Scan", "SystemAddress": 1, "BodyID": 1, "WasDiscovered": False},
          {"event": "SAAScanComplete"}, {"event": "ScanOrganic", "ScanType": "Analyse"}):
    ses.feed(e)
got = ses.feed({"event": "SellOrganicData", "BioData": [{"Genus_Localised": "Stratum", "Value": 19_010_800,
                                                        "Bonus": 0}]})
check(ses.summary() == {"jumps": 1, "scanned": 1, "first": 1, "mapped": 1, "species": 1, "earned": 19_010_800}
      and got == 19_010_800, "session: a body scanned twice counts once, the sale is earned")
ses.feed({"event": "LoadGame"})
check(ses.summary()["jumps"] == 0, "LoadGame starts a new session")
check(situation.genus_open(["Bacterium", "Brain Trees", "Stratum"], ["Bacterium Aurasus", "Roseum Brain Tree"])
      == ["Stratum"], "open genera: none of their species analysed")
check(situation.genus_open(["Bacterium", "Brain Trees"], [{"species": "Ostrinum Brain Tree", "genus": "Brain Trees",
                                                           "variant": None, "ts": "2026-11-17T15:34:11Z"}])
      == ["Bacterium"], "open genera from the database's species entries (dicts, not names)")
cw = situation.CarrierWatch()
cw.feed({"event": "CarrierStats", "FuelLevel": 800, "SpaceUsage": {"TotalCapacity": 25000, "FreeSpace": 15000}})
cw.feed({"event": "CarrierJumpRequest", "SystemName": "Colonia", "timestamp": "2027-01-15T08:00:00Z",
         "DepartureTime": "2027-01-15T08:15:10Z"})
check((cw.fuel, cw.used, cw.departure - cw.requested) == (800, 10_000, 910.0), "carrier: tank, used space, departure")
check(cw.feed({"event": "CarrierJumpCancelled"}) and cw.departure is None, "a cancelled jump is gone")

print("the plugin: journal and Status.json in, the column out")


class Client:
    def __init__(self):
        self.sent = []

    def send_message(self, mid, text, colour, x, y, ttl=4, size="normal"):
        self.sent.append((mid, text, x, y))

    def shown(self, group="info"):
        last = {}
        for mid, text, _x, _y in self.sent:
            if mid.startswith("shbox-%s-" % group):
                last[mid] = text
        return [t for t in last.values() if t]


ST = state.ST
ST.db = SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
ST.db.set_meta(CMDR_READY, "test")
client = Client()
ST.overlay = CockpitOverlay(client=client)
cfg = {}
plugin_pkg.use_settings(cfg)
uithread._run_async = lambda fn, *a, label="": fn(*a)
STATE = {"FID": "F42"}
T = "2027-01-15T08:%02d:00Z"
_real_time = time.time
later = [0.0]
time.time = lambda: _real_time() + later[0]       # the board's items run out as time goes on


def ev(e, minute=0):
    e = dict(e, timestamp=T % minute)
    load.journal_entry("Cmdr", False, "", "", e, STATE)


def info():
    client.sent.clear()
    cockpitinfo.draw()
    return client.shown()


ev({"event": "LoadGame", "Commander": "Cmdr", "FID": "F42"})
ev({"event": "SellOrganicData", "MarketID": 1, "BioData": [
    {"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum", "Species_Localised": "Stratum Tectonicas",
     "Value": 19_010_800, "Bonus": 0}]})
ev({"event": "FSDJump", "StarSystem": "Test Sys", "SystemAddress": 99, "StarPos": [1.0, 2.0, 3.0]}, 1)
ev({"event": "FSSDiscoveryScan", "SystemAddress": 99, "BodyCount": 5, "Progress": 0.2}, 2)
lines = info()
check(not any(t.startswith("SYSTEM") for t in lines), "after the honk with nothing scanned yet: no value to name")
ev({"event": "Scan", "ScanType": "Detailed", "StarSystem": "Test Sys", "SystemAddress": 99, "BodyID": 1,
    "BodyName": "Test Sys 1", "PlanetClass": "Earthlike body", "MassEM": 1.0, "WasDiscovered": False,
    "WasMapped": False, "Landable": False, "DistanceFromArrivalLS": 400.0}, 3)
ev({"event": "Scan", "ScanType": "Detailed", "StarSystem": "Test Sys", "SystemAddress": 99, "BodyID": 2,
    "BodyName": "Test Sys 2", "PlanetClass": "Rocky body", "MassEM": 0.05, "WasDiscovered": False,
    "WasMapped": False, "Landable": True, "SurfaceGravity": 25.0, "SurfaceTemperature": 905.0,
    "Atmosphere": "thin ammonia atmosphere", "DistanceFromArrivalLS": 800.0}, 4)
ev({"event": "FSSAllBodiesFound", "SystemName": "Test Sys", "SystemAddress": 99, "Count": 5}, 5)
lines = info()
check(lines and lines[0].startswith("SYSTEM  2/5 scanned") and "2 new" in lines[0], "SYSTEM after all bodies: %s" % lines[:1])
check(any(t.startswith("*  1 ELW") for t in lines), "the earth-like is named")
check(any(t.startswith("DSS  ") for t in lines), "and that mapping it pays")
x_info = [x for mid, _t, x, _y in client.sent if mid.startswith("shbox-info-")]
check(x_info and x_info[0] == ANCHORS["top-right"][0], "drawn in the corner across from the other blocks")

ev({"event": "SAASignalsFound", "SystemAddress": 99, "BodyName": "Test Sys 2", "BodyID": 2,
    "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 2},
                {"Type": "$SAA_SignalType_Geological;", "Count": 3}],
    "Genuses": [{"Genus": "$Codex_Ent_Bacterial_Genus_Name;", "Genus_Localised": "Bacterium"},
                {"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum"}]}, 6)
ev({"event": "ApproachBody", "StarSystem": "Test Sys", "SystemAddress": 99, "Body": "Test Sys 2", "BodyID": 2}, 7)
lines = info()
land = [t for t in lines if t.startswith("LANDING")]
check(land and "2.55 g !" in land[0], "landing card with the gravity warning: %s" % land)
check(any("905 K !" in t and "ammonia" in t for t in lines), "temperature and atmosphere")
bio = [t for t in lines if t.startswith("BIO")]
check(bio and bio[0].startswith("BIO  Stratum 19.0 M · Bacterium"), "the best paid genus first: %s" % bio)
check(any(t.startswith("FINDS  Geological x3") for t in lines), "and what else is there")
ev({"event": "Touchdown", "SystemAddress": 99, "Body": "Test Sys 2", "BodyID": 2, "Latitude": 1.0,
    "Longitude": 2.0, "PlayerControlled": True}, 8)
check(not any(t.startswith("LANDING") for t in info()), "landed: the card has done its job")

print("danger: what is at stake")
load.dashboard_entry("Cmdr", False, {"event": "Status", "Flags": 1 << 22, "Flags2": 0, "GuiFocus": 0})
lines = info()
risk = [t for t in lines if t.startswith("RISK")]
check(risk and "in danger" in risk[0], "in danger: %s" % risk)
check(lines and lines[0].startswith("RISK"), "the warning stands first")
ev({"event": "HullDamage", "Health": 0.42, "PlayerPilot": True, "Fighter": False}, 9)
check(any("hull 42 %" in t for t in info()), "hull low: the risk line says so")

print("the arrival star")
ev({"event": "StartJump", "JumpType": "Hyperspace", "StarSystem": "Hot", "SystemAddress": 7, "StarClass": "N"}, 10)
lines = info()
check(lines and lines[0].startswith("! NEUTRON STAR"), "a neutron star ahead stands first: %s" % lines[:1])
cfg[state.CFG["overlay_info_warn"]] = False
check(not any(t.startswith(("! NEUTRON", "RISK")) for t in info()), "warnings switched off: gone")
cfg[state.CFG["overlay_info_warn"]] = True

print("the carrier, the sale, docking")
now = time.time()
dep = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 600))
ev({"event": "CarrierJumpRequest", "CarrierID": 7, "SystemName": "Colonia", "SystemID": 5, "DepartureTime": dep}, 11)
car = [t for t in info() if t.startswith("CARRIER")]
check(car and "-> Colonia" in car[0] and ("9:5" in car[0] or "10:0" in car[0]), "countdown: %s" % car)
ev({"event": "CarrierJumpCancelled", "CarrierID": 7}, 12)
check(not any(t.startswith("CARRIER") for t in info()), "cancelled: gone")
later[0] += 60                                    # at the station: the warnings have run out
ev({"event": "MultiSellExplorationData", "Discovered": [{"SystemName": "Test Sys", "NumBodies": 2}],
    "BaseValue": 3_000_000, "Bonus": 1_000_000, "TotalEarnings": 4_000_000}, 13)
lines = info()
check(any(t == "SOLD  4.0 M Cr - well done" for t in lines), "the sale as a success message: %s" % lines)
check(any(t.startswith("SESSION  1 jumps · 2 bodies") for t in lines), "with the session's tally")
cfg[state.CFG["overlay_info_session"]] = False
check(not any(t.startswith(("SOLD", "SESSION")) for t in info()), "session switched off: gone")
cfg[state.CFG["overlay_info_session"]] = True

print("a game screen in front: nothing drawn, back afterwards")
ST.overlay.set_focus(6)
check(info() == [], "galaxy map open: the column waits")
ST.overlay.set_focus(0)
check(info() != [], "back in the cockpit: drawn again")

print("the start: what you were paid, read from the journals")
jdir = tempfile.mkdtemp()
with open(os.path.join(jdir, "Journal.2027-01-14T080000.01.log"), "w", encoding="utf-8") as fh:
    for e in ({"event": "MarketSell", "Type": "platinum", "SellPrice": 231_000, "Count": 10, "TotalSale": 2_310_000},
              {"event": "SellOrganicData", "BioData": [{"Genus_Localised": "Osseus", "Value": 4_000_000}]},
              {"event": "CarrierStats", "FuelLevel": 700, "SpaceUsage": {"TotalCapacity": 25000, "FreeSpace": 20000}}):
        fh.write(json.dumps(dict(e, timestamp="2027-01-14T08:00:00Z")) + "\n")
maintenance._journal_dir = lambda: jdir
cockpitinfo.bootstrap()
check(cockpitinfo.PRICES.market.get("platinum") == 231_000 and cockpitinfo.PRICES.of_genus("Osseus") == 4_000_000
      and cockpitinfo.PRICES.of_genus("Stratum") == 19_010_800, "prices from the journals, the live ones kept")
check(cockpitinfo.CARRIER.fuel == 700, "the carrier's tank from CarrierStats")
ev({"event": "SAASignalsFound", "SystemAddress": 99, "BodyName": "Test Sys 2 A Ring", "BodyID": 9,
    "Signals": [{"Type": "Platinum", "Type_Localised": "Platinum", "Count": 2}]}, 14)
ring = [t for t in info() if "RING" in t or "Platinum" in t]
check(any("Platinum x2 · sold 231 k/t" in t for t in ring), "a ring: its hotspots and your price: %s" % ring)

print("situation: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
