# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Ship, fleet and carrier knowledge from the commander's own journals.

The live tracker follows only the newest journals. Ship fitting history (the
last `Loadout` of every ship you have flown), the hangar (`StoredShips`) and
the carrier (`CarrierStats`, jumps, tritium, bank transfers) need the whole
history, so this module scans all journals once - only lines that mention one
of the events below are parsed - and afterwards only files that changed.

Pure reading. Nothing here is sent anywhere, nothing is written.

Also here, because the views need them:
  * module names from the journal's internal ids ("int_shieldgenerator_size6_
    class2" -> "Shield Generator 6D") - our own short wording
  * role ratings of a fitting (combat, mining, transport, exploration,
    passengers) - a rule of thumb from the modules, shown with its reasons
  * the carrier's tritium use per jump, fitted on the commander's own jumps
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

EVENTS = ("Loadout", "StoredShips", "ShipyardSwap", "ShipyardBuy", "ShipyardNew",
          "ShipyardSell", "ShipyardTransfer", "SellShipOnRebuy", "CarrierStats",
          "CarrierLocation", "CarrierJump", "CarrierJumpRequest", "CarrierJumpCancelled",
          "CarrierDepositFuel", "CarrierBankTransfer", "CarrierFinance", "CarrierCrewServices",
          "CarrierNameChange", "FSDJump", "Location", "ShipTargeted", "Commander", "LoadGame",
          "SAAScanComplete", "SellOrganicData",
          # unsold data at risk (M4)
          "ScanOrganic", "FSSDiscoveryScan", "MultiSellExplorationData", "SellExplorationData",
          "Resurrect",
          "ProspectedAsteroid", "MiningRefined", "LaunchDrone", "AsteroidCracked",
          # surface vehicles: ground mining with the Rhino (M2)
          "LaunchSRV", "DockSRV", "LaunchVessel", "DockVessel",
          "Statistics", "Rank", "Progress", "Reputation", "MarketSell", "CargoTransfer",
          # raw materials (jumponium)
          "Materials", "MaterialCollected", "MaterialDiscarded", "Synthesis", "EngineerCraft",
          "MaterialTrade", "TechnologyBroker", "MissionCompleted", "ScientificResearch",
          # hazard log and where it happened
          "UnderAttack", "Interdicted", "EscapeInterdiction", "HullDamage", "HeatWarning", "HeatDamage",
          "ShieldState", "CockpitBreached", "SystemsShutdown", "Died", "JetConeDamage", "JetConeBoost",
          "FighterDestroyed", "SRVDestroyed", "ApproachBody", "LeaveBody", "SupercruiseExit", "Touchdown",
          "Docked",
          # points of interest in SYSTEM (M10): stations, carriers, beacons
          "FSSSignalDiscovered",
          # known carriers (K1): where you docked, what you started there
          "Undocked", "MissionAccepted", "CommunityGoalJoin",
          # which ring the rocks were prospected in (fis/prospect.py)
          "SupercruiseEntry")
_NEEDLES = tuple(('"event":"%s"' % e).encode() for e in EVENTS)

# carrier tritium per jump: 5 + ly * (load + tritium + BASE) / DIV, rounded.
# Fitted on 12 of the commander's own jumps (35-500 ly, 4300-8400 t load):
# every jump within +-1 t. Load = SpaceUsage Cargo + ShipPacks + ModulePacks.
TRITIUM_BASE = 26500.0
TRITIUM_DIV = 175000.0
CARRIER_MAX_JUMP = 500.0
CARRIER_TANK = 1000


def tritium_for_jump(ly: float, load_t: float, tritium_t: float) -> int:
    return int(round(5 + ly * (load_t + tritium_t + TRITIUM_BASE) / TRITIUM_DIV))


def carrier_trip(ly: float, load_t: float, tank: int) -> Dict[str, Any]:
    """Tritium for a trip of `ly` in equal jumps of at most 500 ly. Tritium
    on board weighs too: when the tank is short, the need is worked out for
    a carrier that carries it."""
    n = max(1, int(math.ceil(ly / CARRIER_MAX_JUMP - 1e-9)))
    hop = ly / n

    def cost(start: float) -> int:
        left, total = float(start), 0
        for _ in range(n):
            need = tritium_for_jump(hop, load_t, left)
            total += need
            left -= need
        return total

    need = cost(tank)
    if need > tank:
        start = need
        for _ in range(4):
            start = cost(start)
        need = start
    return {"ly": round(ly, 1), "jumps": n, "need": int(need), "enough": need <= tank,
            "short": max(0, int(need) - int(tank))}


def carrier_range(tritium: int, load_t: float, hop_ly: float = CARRIER_MAX_JUMP
                  ) -> Dict[str, Any]:
    """Full jumps of `hop_ly` the tank allows, then what is left for a short one."""
    left, jumps, ly = int(tritium), 0, 0.0
    while True:
        need = tritium_for_jump(hop_ly, load_t, left)
        if need > left:
            break
        left -= need
        jumps += 1
        ly += hop_ly
        if jumps > 200:
            break
    # a last, shorter jump with what remains
    extra = 0.0
    if left > 5:
        lo, hi = 0.0, hop_ly
        for _ in range(30):
            mid = (lo + hi) / 2
            if tritium_for_jump(mid, load_t, left) <= left:
                lo = mid
            else:
                hi = mid
        extra = lo
    return {"jumps": jumps, "ly": round(ly + extra, 0), "per_jump": tritium_for_jump(
        hop_ly, load_t, tritium), "left_after": left}


# --------------------------------------------------------------- names

_CLASS = {"1": "E", "2": "D", "3": "C", "4": "B", "5": "A"}
_NAMES = [
    # (pattern on the internal id, English name) - our own short wording
    ("int_powerplant", "Power Plant"), ("int_engine", "Thrusters"),
    ("int_hyperdrive_overcharge", "FSD (SCO)"), ("int_hyperdrive", "Frame Shift Drive"),
    ("int_lifesupport", "Life Support"), ("int_powerdistributor", "Power Distributor"),
    ("int_sensors", "Sensors"), ("int_fueltank", "Fuel Tank"),
    ("int_shieldgenerator_size\\d+_class\\d+_fast", "Bi-Weave Shield"),
    ("int_shieldgenerator_size\\d+_class\\d+_strong", "Prismatic Shield"),
    ("int_shieldgenerator", "Shield Generator"), ("int_shieldcellbank", "Shield Cell Bank"),
    ("int_guardianshieldreinforcement", "Guardian Shield Reinf."),
    ("int_hullreinforcement", "Hull Reinforcement"), ("int_guardianhullreinforcement", "Guardian Hull Reinf."),
    ("int_modulereinforcement", "Module Reinforcement"), ("int_guardianmodulereinforcement", "Guardian Module Reinf."),
    ("int_metaalloyhullreinforcement", "Meta-Alloy Hull Reinf."),
    ("int_cargorack", "Cargo Rack"), ("int_corrosionproofcargorack", "Corrosion-proof Cargo"),
    ("int_fuelscoop", "Fuel Scoop"), ("int_refinery", "Refinery"),
    ("int_repairer", "AFM Unit"), ("int_detailedsurfacescanner", "Detailed Surface Scanner"),
    ("int_guardianfsdbooster", "Guardian FSD Booster"), ("int_supercruiseassist", "Supercruise Assist"),
    ("int_dockingcomputer_advanced", "Adv. Docking Computer"), ("int_dockingcomputer", "Docking Computer"),
    ("int_buggybay", "Planetary Vehicle Hangar"), ("int_mkiilargebuggybay", "Vehicle Hangar (Nomad)"),
    ("int_fighterbay", "Fighter Hangar"), ("int_passengercabin", "Passenger Cabin"),
    ("int_dronecontrol_prospector", "Prospector Limpets"), ("int_dronecontrol_collection", "Collector Limpets"),
    ("int_dronecontrol_fueltransfer", "Fuel Transfer Limpets"), ("int_dronecontrol_repair", "Repair Limpets"),
    ("int_dronecontrol_resourcesiphon", "Hatch Breaker Limpets"), ("int_dronecontrol_decontamination", "Decontamination Limpets"),
    ("int_dronecontrol_recon", "Recon Limpets"), ("int_dronecontrol_unkvesselresearch", "Research Limpets"),
    ("int_multidronecontrol_mining", "Mining Multi-Limpet"), ("int_multidronecontrol_operations", "Operations Multi-Limpet"),
    ("int_multidronecontrol_rescue", "Rescue Multi-Limpet"), ("int_multidronecontrol_xeno", "Xeno Multi-Limpet"),
    ("int_multidronecontrol_universal", "Universal Multi-Limpet"),
    ("int_planetapproachsuite", "Planetary Approach Suite"), ("int_stellarbodydiscoveryscanner", "Discovery Scanner"),
    ("int_codexscanner", "Codex Scanner"),
    ("hpt_mining_abrblstr", "Abrasion Blaster"), ("hpt_mining_seismchrgwarhd", "Seismic Charge"),
    ("hpt_mining_subsurfdispmisle", "Sub-surface Missile"), ("hpt_mininglaser", "Mining Laser"),
    ("hpt_mrascanner", "Pulse Wave Analyser"), ("hpt_cloudscanner", "Wake Scanner"),
    ("hpt_crimescanner", "Kill Warrant Scanner"), ("hpt_cargoscanner", "Manifest Scanner"),
    ("hpt_shieldbooster", "Shield Booster"), ("hpt_heatsinklauncher", "Heat Sink Launcher"),
    ("hpt_chafflauncher", "Chaff Launcher"), ("hpt_electroniccountermeasure", "ECM"),
    ("hpt_plasmapointdefence", "Point Defence"), ("hpt_antiunknownshutdown", "Shutdown Field Neutraliser"),
    ("hpt_xenoscanner", "Xeno Scanner"),
    ("hpt_pulselaserburst", "Burst Laser"), ("hpt_pulselaser", "Pulse Laser"), ("hpt_beamlaser", "Beam Laser"),
    ("hpt_multicannon", "Multi-cannon"), ("hpt_atmulticannon", "AX Multi-cannon"),
    ("hpt_cannon", "Cannon"), ("hpt_slugshot", "Fragment Cannon"), ("hpt_railgun", "Rail Gun"),
    ("hpt_plasmaaccelerator", "Plasma Accelerator"), ("hpt_atdumbfiremissile", "AX Missile Rack"),
    ("hpt_basicmissilerack", "Seeker Missile Rack"), ("hpt_dumbfiremissilerack", "Missile Rack"),
    ("hpt_drunkmissilerack", "Pack-Hound"), ("hpt_minelauncher", "Mine Launcher"),
    ("hpt_advancedtorppylon", "Torpedo Pylon"), ("hpt_atventdisruptorpylon", "Guardian Nanite Torpedo"),
    ("hpt_guardian_gausscannon", "Guardian Gauss"), ("hpt_guardian_plasmalauncher", "Guardian Plasma"),
    ("hpt_guardian_shardcannon", "Guardian Shard"), ("hpt_flakmortar", "Remote Flak"),
    ("hpt_flechettelauncher", "Flechette Launcher"), ("hpt_causticmissile", "Enzyme Missile"),
]
_NAME_RE = [(re.compile(p), n) for p, n in _NAMES]


_ARMOUR = {"grade1": "Lightweight Alloy", "grade2": "Reinforced Alloy", "grade3": "Military Grade",
           "mirrored": "Mirrored Surface", "reactive": "Reactive Surface"}


def module_name(item: Optional[str]) -> str:
    """Short English name with size/class (6D), mount (F/G/T) where it applies."""
    it = (item or "").lower()
    if "_armour_" in it:
        return next((v for k, v in _ARMOUR.items() if k in it), "Armour")
    base = None
    for rx, n in _NAME_RE:
        if rx.match(it):
            base = n
            break
    if base is None:
        base = it.replace("hpt_", "").replace("int_", "").replace("_", " ").strip() or "?"
    m = re.search(r"size(\d+)_class(\d)", it)
    if m:
        base += " %s%s" % (m.group(1), _CLASS.get(m.group(2), m.group(2)))
    mount = {"fixed": "F", "gimbal": "G", "turret": "T"}
    for k, v in mount.items():
        if "_%s_" % k in it or it.endswith("_" + k):
            base += " (%s)" % v
            break
    for k, v in (("_small", " S"), ("_medium", " M"), ("_large", " L"), ("_huge", " H"), ("_tiny", "")):
        if k in it and it.startswith("hpt_") and not m:
            base += v
            break
    return base


def readable_module(localised: Optional[str], raw: Optional[str] = None) -> str:
    """The game's own module name - unless it is still a $..._name; key:
    some variants come unlocalised (AfmuRepairs on the free fighter hangar:
    "$Int_FighterBayMk2_Size5_Class1_Name; (Free)"). Then our own name."""
    if localised and "$" not in localised:
        return localised
    key = re.sub(r"[$;]|_name\b| \(free\)|_free\b", "", (raw or localised or "").lower()).strip()
    return module_name(key) if key else "?"


def slot_group(slot: str) -> str:
    s = slot or ""
    if s.startswith("TinyHardpoint"):
        return "utility"
    if "Hardpoint" in s:
        return "hardpoints"
    if s in ("PowerPlant", "MainEngines", "FrameShiftDrive", "LifeSupport", "PowerDistributor",
             "Radar", "FuelTank", "Armour"):
        return "core"
    if s.startswith(("Slot", "Military")):
        return "optional"
    return "cosmetic"


def slot_size(slot: str) -> Optional[int]:
    m = re.search(r"Size(\d+)", slot or "")
    if m:
        return int(m.group(1))
    for k, v in (("Tiny", 0), ("Small", 1), ("Medium", 2), ("Large", 3), ("Huge", 4)):
        if (slot or "").startswith(k + "Hardpoint"):
            return v
    return None


# --------------------------------------------------------------- roles

_MINING = ("hpt_mininglaser", "hpt_mining_abrblstr", "hpt_mining_seismchrgwarhd",
           "hpt_mining_subsurfdispmisle")
_UTILITY_NOT_WEAPON = ("hpt_shieldbooster", "hpt_heatsinklauncher", "hpt_chafflauncher",
                       "hpt_electroniccountermeasure", "hpt_plasmapointdefence",
                       "hpt_antiunknownshutdown", "hpt_cloudscanner", "hpt_crimescanner",
                       "hpt_cargoscanner", "hpt_mrascanner", "hpt_xenoscanner")


def _clamp(v: float) -> int:
    return int(max(0, min(5, round(v))))


def rate_loadout(lo: Dict[str, Any], vehicles: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """
    Role ratings 0-5 from a fitting, each with the facts it rests on. A rule of
    thumb for a quick look at the hangar, not a simulation: weapons by mount
    size, shield by size and class, cargo and jump range in steps.

    M3: `vehicles` = surface vehicles launched from this ship so far ("SRV
    Rhino", "SRV Scarab", "Nomad" - the fitting only says "hangar", the
    journal's LaunchSRV says which). Exploration counts exobiology: without
    any vehicle hangar at most 4, the Nomad hangar adds one step. Mining
    counts ground mining: a hangar from which the Rhino was launched rates
    at least 2 even without mining tools.
    """
    vehicles = set(vehicles or ())
    mods = lo.get("Modules") or []
    items = [(m.get("Slot") or "", (m.get("Item") or "").lower()) for m in mods]
    weapons = [(s, i) for s, i in items if "Hardpoint" in s and not s.startswith("Tiny")
               and not i.startswith(_MINING)]
    wsize = sum((slot_size(s) or 1) for s, _i in weapons)
    mining = [i for _s, i in items if i.startswith(_MINING)]
    shield = next((i for _s, i in items if i.startswith("int_shieldgenerator")), None)
    sh = 0.0
    if shield:
        m = re.search(r"size(\d+)_class(\d)", shield)
        if m:
            sh = int(m.group(1)) * (0.6 + 0.1 * int(m.group(2)))
    boosters = sum(1 for _s, i in items if i.startswith("hpt_shieldbooster"))
    hrp = sum(1 for _s, i in items if "hullreinforcement" in i)
    armour = next((i for s, i in items if s == "Armour"), "")
    armour_pts = 2 if ("mirrored" in armour or "reactive" in armour) else (
        1 if "grade3" in armour or "grade2" in armour else 0)
    cargo = int(lo.get("CargoCapacity") or 0)
    jump = float(lo.get("MaxJumpRange") or 0.0)
    has = lambda p: any(i.startswith(p) for _s, i in items)   # noqa: E731
    cabins = sum(1 for _s, i in items if i.startswith("int_passengercabin"))

    # a large ship full of medium guns and a big A shield reaches 5; a few
    # small guns on an explorer stay at 1-2
    combat = (wsize / 6.0 + sh / 4.0 + boosters * 0.25 + hrp * 0.3 + armour_pts * 0.4) if weapons else 0
    mine = (len(mining) * 1.2 + (1.5 if has("int_refinery") else 0)
            + (0.6 if has("int_dronecontrol_prospector") else 0)
            + (0.6 if has("int_dronecontrol_collection") or has("int_multidronecontrol_mining") else 0)
            + (0.5 if has("hpt_mrascanner") else 0)) if mining else 0
    trans = 0 if cargo < 8 else (1 if cargo < 32 else 2 if cargo < 100 else 3 if cargo < 250 else
                                 4 if cargo < 500 else 5)
    expl = 0 if jump < 15 else (1 if jump < 25 else 2 if jump < 35 else 3 if jump < 45 else
                                4 if jump < 60 else 5)
    nomad_bay = has("int_mkiilargebuggybay")      # the flying Nomad needs its own bay
    srv_bay = has("int_buggybay") or nomad_bay
    if nomad_bay:
        expl = min(5, expl + 1) if expl >= 2 else expl
    elif not srv_bay:
        expl = min(expl, 4)
    rhino = srv_bay and any("rhino" in v.lower() for v in vehicles)
    if rhino:
        mine = max(mine, 2.0)
    if not has("int_fuelscoop"):
        expl = min(expl, 1)
    if not has("int_detailedsurfacescanner"):
        expl = min(expl, 2)
    pax = 0 if not cabins else min(5, 1 + cabins)
    # search and rescue: repair and fuel limpets for others, fuel to give,
    # a scoop to refill. The rescue / universal multi-limpet controller
    # counts for repair, fuel transfer and decontamination; a dedicated fuel
    # transfer controller carries more.
    mlc = has("int_multidronecontrol_rescue") or has("int_multidronecontrol_universal")
    repair = has("int_dronecontrol_repair") or mlc
    fuel_lt = has("int_dronecontrol_fueltransfer")
    tank = float((lo.get("FuelCapacity") or {}).get("Main") or 0.0)
    sar = 0.0
    if repair or fuel_lt or mlc:
        sar = ((1.5 if repair else 0) + (1.5 if fuel_lt else 1.0 if mlc else 0)
               + (1.5 if tank >= 150 else 1.0 if tank >= 100 else 0.5 if tank >= 64 else 0)
               + (0.5 if has("int_fuelscoop") else 0)
               + (0.3 if has("int_dronecontrol_decontamination") or mlc else 0)
               + (0.2 if has("int_dronecontrol_collection") or has("int_multidronecontrol_operations") else 0))
    roles = {"combat": _clamp(combat), "mining": _clamp(mine), "transport": trans,
             "exploration": expl, "passengers": pax, "sar": _clamp(sar)}
    why = {
        "combat": "%d weapons%s%s%s" % (len(weapons), (", " + module_name(shield)) if shield else ", no shield",
                                        (", %d boosters" % boosters) if boosters else "",
                                        (", %d HRP" % hrp) if hrp else ""),
        "mining": ", ".join(sorted({module_name(i) for i in mining}
                                   | ({"ground mining (SRV Rhino)"} if rhino else set()))) or "no mining tools",
        "transport": "%d t cargo" % cargo,
        "exploration": "%.1f ly%s%s%s" % (jump, "" if has("int_fuelscoop") else ", no scoop",
                                          ", DSS" if has("int_detailedsurfacescanner") else ", no DSS",
                                          ", Nomad hangar" if nomad_bay else ", SRV hangar" if srv_bay
                                          else ", no vehicle hangar"),
        "passengers": "%d cabins" % cabins if cabins else "no cabins",
        "sar": ", ".join(x for x in (
            "rescue limpets" if mlc else ("repair limpets" if repair else ""),
            "fuel transfer limpets" if fuel_lt else "",
            "%d t fuel" % tank if tank else "",
            "scoop" if has("int_fuelscoop") else "no scoop") if x) if (repair or fuel_lt or mlc) else "no repair or fuel limpets",
    }
    # ties go to the specialised role - every hull carries some guns
    pref = ("mining", "exploration", "sar", "passengers", "transport", "combat")
    best = max(pref, key=lambda k: (roles[k], -pref.index(k)))
    return {"roles": roles, "why": why, "primary": best if roles[best] > 0 else None}


# --------------------------------------------------------------- archive

class Archive:
    """Relevant journal events from every journal, rescanned when files change."""

    MIN_RESCAN_S = 20.0

    def __init__(self, journal_dir: str) -> None:
        self.journal_dir = journal_dir
        self._files: Dict[str, Tuple[Tuple[int, int], List[Dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._scanned = 0.0
        self.rev = 0

    def refresh(self, force: bool = False) -> None:
        if not force and time.time() - self._scanned < self.MIN_RESCAN_S:
            return
        with self._lock:
            self._scanned = time.time()
            paths = sorted(glob.glob(os.path.join(self.journal_dir, "Journal.*.log")))
            changed = False
            for p in paths:
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                sig = (int(st.st_mtime), st.st_size)
                old = self._files.get(p)
                if old and old[0] == sig:
                    continue
                self._files[p] = (sig, self._read(p))
                changed = True
            for p in list(self._files):
                if p not in paths:
                    del self._files[p]
                    changed = True
            if changed:
                self.rev += 1

    @staticmethod
    def _read(path: str) -> List[Dict[str, Any]]:
        # one journal folder can hold several commanders: every event is
        # tagged with the commander (FID) that was logged in when it happened
        out: List[Dict[str, Any]] = []
        fid = None
        try:
            with open(path, "rb") as fh:
                for raw in fh:
                    if b'"event"' not in raw:
                        continue
                    compact = raw.replace(b" ", b"")
                    if not any(n in compact for n in _NEEDLES):
                        continue
                    try:
                        e = json.loads(raw.decode("utf-8", errors="replace"))
                    except ValueError:
                        continue
                    if e.get("event") in ("Commander", "LoadGame"):
                        fid = e.get("FID") or fid
                        out.append({"event": "Commander", "timestamp": e.get("timestamp"),
                                    "_fid": fid, "Name": e.get("Name") or e.get("Commander")})
                        if e.get("event") == "LoadGame":      # session start (hazard log)
                            out.append({"event": "LoadGame", "timestamp": e.get("timestamp"), "_fid": fid})
                        continue
                    if e.get("event") in ("FSDJump", "Location"):
                        # the coordinates (carrier jump distances) - and for a
                        # Location the docking: loading the game on a pad
                        # writes no Docked, only Location with Docked: true
                        slim = {"event": e["event"], "timestamp": e.get("timestamp"),
                                "StarSystem": e.get("StarSystem"), "StarPos": e.get("StarPos"),
                                "SystemAddress": e.get("SystemAddress"), "JumpDist": e.get("JumpDist")}
                        if e.get("Docked"):
                            slim.update({k: e.get(k) for k in ("Docked", "StationName",
                                                               "StationType", "MarketID")})
                        e = slim
                    elif e.get("event") == "ShipTargeted":
                        if not str(e.get("PilotName") or "").startswith("$RolePanel2_unmanned"):
                            continue
                        e = {"event": "ShipTargeted", "timestamp": e.get("timestamp"),
                             "Ship": e.get("Ship"), "Ship_Localised": e.get("Ship_Localised")}
                    e["_fid"] = fid
                    out.append(e)
        except OSError:
            pass
        return out

    def commander(self) -> Tuple[Optional[str], Optional[str]]:
        """(FID, name) of the commander logged in last."""
        self.refresh()
        with self._lock:
            last = None
            for _p, (_s, lst) in sorted(self._files.items()):
                for e in lst:
                    if e["event"] == "Commander" and e.get("_fid"):
                        last = e
        return (last["_fid"], last.get("Name")) if last else (None, None)

    def events(self, fid: Optional[str] = None) -> List[Dict[str, Any]]:
        """Events of one commander (default: the one logged in last)."""
        self.refresh()
        if fid is None:
            fid = self.commander()[0]
        with self._lock:
            evs = [e for _p, (_s, lst) in sorted(self._files.items()) for e in lst
                   if e["event"] != "Commander" and (fid is None or e.get("_fid") in (fid, None))]
        evs.sort(key=lambda e: e.get("timestamp") or "")
        return evs

    # -------------------------------------------------------------- ships
    def ship_names(self, evs: Iterable[Dict[str, Any]]) -> Dict[str, str]:
        """Internal ship type -> display name, learnt from the journal itself."""
        names: Dict[str, str] = {}
        for e in evs:
            if e["event"] == "StoredShips":
                for s in (e.get("ShipsHere") or []) + (e.get("ShipsRemote") or []):
                    if s.get("ShipType_Localised"):
                        names[(s.get("ShipType") or "").lower()] = s["ShipType_Localised"]
            elif e["event"] in ("ShipyardSwap", "ShipyardBuy", "ShipyardNew", "ShipTargeted"):
                for k in ("ShipType", "Ship", "StoreOldShip", "SellOldShip"):
                    loc = e.get(k + "_Localised")
                    if e.get(k) and loc:
                        names[str(e[k]).lower()] = loc
        return names

    def fleet(self) -> Dict[str, Any]:
        """Every ship you own: where it is, its last known fitting and roles."""
        evs = self.events()
        names = self.ship_names(evs)
        loadouts: Dict[int, Dict[str, Any]] = {}
        sold: Dict[int, str] = {}
        stored: Optional[Dict[str, Any]] = None
        current = None
        for e in evs:
            ev = e["event"]
            if ev == "Loadout" and e.get("ShipID") is not None:
                loadouts[int(e["ShipID"])] = e
                current = int(e["ShipID"])
                sold.pop(int(e["ShipID"]), None)
            elif ev == "StoredShips":
                stored = e
            elif ev in ("ShipyardSell", "SellShipOnRebuy") and e.get("SellShipID") is not None:
                sold[int(e["SellShipID"])] = e.get("timestamp") or ""
            elif ev == "ShipyardSwap" and e.get("SellShipID") is not None:
                sold[int(e["SellShipID"])] = e.get("timestamp") or ""
        ships: Dict[int, Dict[str, Any]] = {}

        def entry(sid: int) -> Dict[str, Any]:
            return ships.setdefault(sid, {"id": sid})

        if stored:
            for where, lst in (("here", stored.get("ShipsHere") or []),
                               ("remote", stored.get("ShipsRemote") or [])):
                for s in lst:
                    sid = s.get("ShipID")
                    if sid is None:
                        continue
                    it = entry(int(sid))
                    it.update(type=(s.get("ShipType") or "").lower(), name=s.get("Name"),
                              value=s.get("Value"), hot=s.get("Hot"),
                              location=(stored.get("StationName") if where == "here"
                                        else s.get("StarSystem")),
                              system=(stored.get("StarSystem") if where == "here"
                                      else s.get("StarSystem")),
                              in_transit=bool(s.get("InTransit")), stored_at=where)
        stored_ts = stored.get("timestamp") if stored else ""
        # StoredShips never lists the ship you sit in: the one active when the
        # list was written belongs to the fleet even when its Loadout is older
        active_at_list = None
        for e in evs:
            if (e.get("timestamp") or "") > stored_ts:
                break
            if e["event"] == "Loadout" and e.get("ShipID") is not None:
                active_at_list = int(e["ShipID"])
        # ship ids come back after selling: a fitting belongs to a hangar entry
        # only when the hull type matches; otherwise try same type + same name
        by_name: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for e in evs:
            if e["event"] == "Loadout" and e.get("ShipName"):
                by_name[((e.get("Ship") or "").lower(), e["ShipName"].strip().lower())] = e
        fits: Dict[int, Dict[str, Any]] = {}
        for sid, it in ships.items():
            lo = loadouts.get(sid)
            if lo is not None and (lo.get("Ship") or "").lower() == it["type"]:
                fits[sid] = lo
            elif it.get("name"):
                alt = by_name.get((it["type"], it["name"].strip().lower()))
                if alt is not None:
                    fits[sid] = alt
        for sid, lo in loadouts.items():
            if sid in ships or sid in sold:
                continue
            # not in the last hangar list: only ships bought or flown since
            if stored and (lo.get("timestamp") or "") < stored_ts and sid not in (current, active_at_list):
                continue
            entry(sid)["type"] = (lo.get("Ship") or "").lower()
            fits[sid] = lo
        # M3: which surface vehicles each ship has launched (LaunchSRV says
        # the type; the fitting only knows a hangar)
        vehicles: Dict[int, set] = {}
        cur_sid: Optional[int] = None
        for e in evs:
            if e["event"] == "Loadout" and e.get("ShipID") is not None:
                cur_sid = int(e["ShipID"])
            elif e["event"] in ("LaunchSRV", "LaunchVessel") and cur_sid is not None:
                vehicles.setdefault(cur_sid, set()).add(
                    e.get("SRVType_Localised") or e.get("VesselType_Localised")
                    or e.get("SRVType") or e.get("VesselType") or "SRV")
        for sid, lo in fits.items():
            it = ships[sid]
            it["vehicles"] = sorted(vehicles.get(sid, ()))
            it["name"] = it.get("name") or lo.get("ShipName")
            it["ident"] = lo.get("ShipIdent")
            it["loadout_ts"] = lo.get("timestamp")
            it["hull"] = lo.get("HullHealth")
            it["rebuy"] = lo.get("Rebuy")
            it["value"] = it.get("value") or ((lo.get("HullValue") or 0) + (lo.get("ModulesValue") or 0)) or None
            it["jump"] = lo.get("MaxJumpRange")
            it["cargo"] = lo.get("CargoCapacity")
            it["rating"] = rate_loadout(lo, it["vehicles"])
            it["modules"] = len([m for m in lo.get("Modules") or [] if slot_group(m.get("Slot")) != "cosmetic"])
        if current is not None and current in ships:
            ships[current]["current"] = True
        for it in ships.values():
            it["type_name"] = names.get(it.get("type") or "", (it.get("type") or "?").replace("_", " ").title())
        stored_info = ({"station": stored.get("StationName"), "system": stored.get("StarSystem"),
                        "market_id": stored.get("MarketID"), "ts": stored.get("timestamp")}
                       if stored else None)
        order = sorted(ships.values(), key=lambda s: (not s.get("current"), s.get("stored_at") != "here",
                                                      s.get("type_name") or ""))
        return {"ships": order, "hangar": stored_info, "names": names}

    def dss(self, sys_id64: int, body_id: int) -> Optional[Dict[str, Any]]:
        """Last surface scan of a body: probes used against the efficiency target."""
        last = None
        for e in self.events():
            if (e["event"] == "SAAScanComplete" and e.get("SystemAddress") == sys_id64
                    and e.get("BodyID") == body_id):
                last = e
        if last is None:
            return None
        p, tg = last.get("ProbesUsed"), last.get("EfficiencyTarget")
        return {"probes": p, "target": tg, "efficient": p is not None and tg is not None and p <= tg,
                "ts": last.get("timestamp")}

    def organic_values(self) -> Dict[str, Dict[str, int]]:
        """Species -> value and first-logged bonus, from your own sales of organic data."""
        out: Dict[str, Dict[str, int]] = {}
        for e in self.events():
            if e["event"] != "SellOrganicData":
                continue
            for b in e.get("BioData") or []:
                name = b.get("Species_Localised") or b.get("Species")
                if name:
                    out[name] = {"value": int(b.get("Value") or 0), "bonus": int(b.get("Bonus") or 0)}
        return out

    def current_loadout(self) -> Optional[Dict[str, Any]]:
        last = None
        for e in self.events():
            if e["event"] == "Loadout":
                last = e
        return last

    # ------------------------------------------------------------ carrier
    def own_carrier_events(self) -> List[Dict[str, Any]]:
        """events() without the CarrierJumps of someone else's carrier: riding
        along on a stranger's carrier (docked or aboard on foot) writes a
        CarrierJump too, and that moved "your" carrier in CARRIER and GALAXY
        - for a commander without a carrier it even invented one."""
        from .carriers import own_jump_flags
        evs = self.events()
        return [e for e, foreign in zip(evs, own_jump_flags(evs)) if not foreign]

    def carrier(self) -> Optional[Dict[str, Any]]:
        evs = self.own_carrier_events()
        stats = loc = None
        pos: Dict[str, Any] = {}
        jumps: List[Dict[str, Any]] = []
        transfers: List[Dict[str, Any]] = []
        balances: List[Tuple[float, int]] = []
        pend = None
        cur = None
        fuel = None
        load = None
        services: Dict[str, Any] = {}
        arrived_ts = None        # CarrierLocation is written at every login; the
        for e in evs:            # day the carrier arrived is the last jump
            ev = e["event"]
            if e.get("StarPos") and e.get("StarSystem"):
                pos[e["StarSystem"]] = e["StarPos"]
            if ev == "CarrierStats":
                su = e.get("SpaceUsage") or {}
                load = (su.get("Cargo") or 0) + (su.get("ShipPacks") or 0) + (su.get("ModulePacks") or 0)
                if pend and pend.get("arrived") and not pend.get("dep"):
                    pend["after"] = e.get("FuelLevel")
                    jumps.append(pend)
                    pend = None
                fuel = e.get("FuelLevel")
                stats = e
                bal = (e.get("Finance") or {}).get("CarrierBalance")
                if bal is not None:
                    balances.append((parse_ts(e.get("timestamp")) or 0.0, int(bal)))
            elif ev == "CarrierDepositFuel":
                if pend:
                    pend["dep"] = True
                fuel = e.get("Total")
            elif ev == "CarrierJumpRequest":
                pend = {"from": cur, "to": e.get("SystemName"), "body": e.get("Body"),
                        "before": fuel, "load": load, "ts": e.get("timestamp"),
                        "departure": e.get("DepartureTime")}
            elif ev == "CarrierJumpCancelled":
                pend = None
            elif ev in ("CarrierLocation", "CarrierJump"):
                # the first report from the target is the arrival; later logins
                # (CarrierLocation again) until the next CarrierStats are not
                if pend and not pend.get("arrived") and e.get("StarSystem") == pend["to"]:
                    pend["arrived"] = e.get("timestamp")
                    arrived_ts = e.get("timestamp")
                elif ev == "CarrierJump" or e.get("StarSystem") != cur:
                    arrived_ts = e.get("timestamp")
                cur = e.get("StarSystem")
                loc = e
            elif ev == "CarrierBankTransfer":
                transfers.append({"ts": parse_ts(e.get("timestamp")) or 0.0,
                                  "deposit": e.get("Deposit") or 0, "withdraw": e.get("Withdraw") or 0})
            elif ev == "CarrierCrewServices":
                services[e.get("CrewRole") or "?"] = e.get("Operation")
        if stats is None:
            return None
        hist = []
        for j in jumps[-12:]:
            a, b = pos.get(j["from"]), pos.get(j["to"])
            ly = math.dist(a, b) if a and b else None
            hist.append({"from": j["from"], "to": j["to"], "ly": round(ly, 1) if ly else None,
                         "used": (j["before"] - j["after"]) if j.get("before") is not None and j.get("after") is not None else None,
                         "predicted": tritium_for_jump(ly, j["load"] or 0, j["before"] or 0) if ly else None,
                         "ts": j.get("arrived") or j.get("ts")})
        pending = None
        if pend and not pend.get("arrived"):
            a, b = pos.get(pend["from"]), pos.get(pend["to"])
            ly = math.dist(a, b) if a and b else None
            pending = {"to": pend["to"], "body": pend.get("body"), "departure": pend.get("departure"),
                       "ly": round(ly, 1) if ly else None,
                       "tritium": tritium_for_jump(ly, load or 0, fuel or 0) if ly else None}
        return {"stats": stats, "location": loc, "arrived": arrived_ts, "fuel": fuel, "load": load,
                "jumps": hist, "pending": pending, "upkeep": weekly_cost(balances, transfers),
                "services_changed": services}


def weekly_cost(balances: List[Tuple[float, int]], transfers: List[Dict[str, Any]],
                min_days: float = 10.0) -> Optional[Dict[str, Any]]:
    """
    What the carrier costs per week, estimated from its balance over time
    with your own bank transfers taken out. Market income (other commanders
    trading at the carrier) cannot be separated, so the estimate can come out
    too low or even positive - then it says so instead of inventing a number.
    """
    if len(balances) < 2:
        return None
    t0, b0 = balances[0]
    t1, b1 = balances[-1]
    days = (t1 - t0) / 86400.0
    if days < min_days:
        return None
    net_tr = sum(x["deposit"] - x["withdraw"] for x in transfers if t0 < x["ts"] <= t1)
    drift = (b1 - b0 - net_tr) / days * 7.0           # credits per week, negative = cost
    return {"per_week": int(round(-drift)) if drift < 0 else None, "drift_per_week": int(round(drift)),
            "days": round(days, 0), "since": t0}
