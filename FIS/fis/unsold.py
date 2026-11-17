# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
M4: data you carry and lose when the ship is destroyed - from the journal.

Exobiology: every ScanOrganic "Analyse" since it was sold. A SellOrganicData
takes the species it lists off the pending list (you can sell a part); a
death (Died) loses everything not sold. The value comes from your own
earlier sales of the same species (one price per species, 42 of 42 stable
in the user's sales). The first-discovery bonus (4x the value on top, so 5x
in all) counts only on a body of YOUR FIRST FOOTFALL - user 11.11., checked
against 153 own sales: every analysis on a first-footfall body paid it;
WasLogged false (almost always set) says nothing about it. 15 sales paid the
bonus without a first footfall (first to sell that species from the body,
which no journal shows) - those stay at the base value: never promise
money the data cannot prove. Species
you never sold have no known value - they are counted, not priced.

Exploration data: bodies you scanned yourself (Scan, not a nav beacon's
NavBeaconDetail) and mapped (SAAScanComplete) that were not part of an
earlier sale of their system (MultiSellExplorationData / SellExplorationData).
A honk alone is no data: honking a system whose bodies you sold before
leaves nothing to sell (11.11.: six such systems were shown as unsold).

B6 (5.0): its value is the plugin's bodyvalue estimate (the community's
formula) of exactly those bodies, calibrated on your own sales: at every
sale the same replay knows what the sold systems' bodies were estimated at,
so earnings / estimate of the sales with an estimate of at least 1 M Cr
gives a factor (median) and a range (lowest to highest). Measured on the
developer's journals, 17.11.2026: 0.91, 0.75-1.29 from 12 sales; smaller
sales scatter by up to 30 times (data scanned before the first journal).
Shown with "~", the range and the number of sales; fewer than three such
sales: the formula alone, marked as not calibrated. A reset of the model
(learnreset part "value") leaves the older sales out.

Risk (user, 11.11.): what a loss would cost - below 50 M Cr low, from
50 M moderate, from 100 M high. The data that is really valuable comes
first: systems you discovered first (the arrival star's scan said
WasDiscovered false) and species analysed on a body where you made the
first footfall (Scan WasFootfalled false, then you disembarked there).
Either of them makes the risk at least moderate.

The four limits (sell advice in M Cr and systems, moderate and high risk in
M Cr) are the user's defaults of 11.11.; since 4.11 each commander sets
their own on the FIS settings page (fis.ini, section [fis], unsold_*).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

from .live import parse_ts, star_pos

BONUS_FACTOR = 4                 # first footfall: 4x the base value on top (own sales)
WARN_CR = 50_000_000             # from here on the sheet advises to sell
WARN_SYSTEMS = 100
RISK_MODERATE_CR = 50_000_000    # user 11.11.: below this a loss is a low risk
RISK_HIGH_CR = 100_000_000       # ... from here on a real one
# 5.0: a station buys cartographic data only from systems at least this far
# away (the user's own sales: none closer than 25 ly in 7 station sales); a
# fleet carrier with Universal Cartographics buys it at any distance (23 of
# 26 carrier sales held systems under 20 ly, often the carrier's own)
STATION_MIN_LY = 20.0
CAL_MIN_EST = 1_000_000          # B6: sales below this estimate scatter too much to calibrate
CAL_MIN_SALES = 3                # ... and fewer such sales give no factor
# the defaults of the settings page (fis.ini unsold_*), in M Cr / systems
DEFAULT_LIMITS = {"sell_mcr": WARN_CR // 1_000_000, "sell_systems": WARN_SYSTEMS,
                  "moderate_mcr": RISK_MODERATE_CR // 1_000_000, "high_mcr": RISK_HIGH_CR // 1_000_000}


def build_unsold(events: List[Dict[str, Any]], values: Optional[Dict[str, Dict[str, int]]] = None,
                 limits: Optional[Dict[str, int]] = None, body_value: Any = None,
                 value_since: Optional[float] = None) -> Dict[str, Any]:
    """What is unsold and what its loss would cost. ``limits`` (M Cr and
    systems, keys as DEFAULT_LIMITS) are the commander's own; missing keys
    take the defaults. ``body_value`` is the plugin's bodyvalue module (B6;
    without it the exploration data is only counted), ``value_since`` the
    last reset of its calibration."""
    values = values or {}
    lim = dict(DEFAULT_LIMITS, **(limits or {}))
    warn_cr, warn_systems = lim["sell_mcr"] * 1_000_000, lim["sell_systems"]
    risk_moderate, risk_high = lim["moderate_mcr"] * 1_000_000, lim["high_mcr"] * 1_000_000
    u = _Unsold(body_value)
    for e in events:
        ev = e.get("event")
        handler = _UNSOLD.get(ev)
        if handler is not None:
            handler(u, ev, e, parse_ts(e.get("timestamp")))
    bio, scanned, mapped, first_sys = u.bio, u.scanned, u.mapped, u.first_sys
    items, total, priced, unknown = _priced(bio, values)
    systems = set(scanned) | set(mapped)
    cal = calibration(u.sales, value_since)
    explo = _explo_value(sum(u.system_est(nm)[0] for nm in systems), cal) if body_value else None
    bio_total = total
    if explo and explo["calibrated"]:
        total += explo["mid"]                 # what a loss would cost: bio and exploration
    if u.lost and body_value:
        u.lost["explo"] = _explo_value(u.lost.pop("explo_est", 0.0), cal)
        u.lost["bio_value"] = _priced(u.lost.pop("bio_items", []), values)[1]
    advice = None
    if total >= warn_cr or len(systems) >= warn_systems:
        advice = "sell"
    ff_bio = sum(1 for x in bio if x["footfall"])
    first_sys &= systems
    risk = ("high" if total >= risk_high else
            "moderate" if total >= risk_moderate or first_sys or ff_bio else "low")
    return {"bio": {"count": len(bio), "value": bio_total, "priced": priced, "unknown": unknown,
                    "first": sum(1 for x in bio if x["footfall"]), "items": items[-12:],
                    "since": u.last_sale["bio"]},
            "exploration": {"systems": len(systems),
                            "mapped": sum(len(v) for v in mapped.values()),
                            "bodies": sum(len(v) for v in scanned.values()),
                            "since": u.last_sale["exploration"],
                            "value": explo, "calibration": cal},
            "total": total,
            "sell": _where_to_sell(u, systems),
            "lost_last": u.lost, "advice": advice,
            "warn_cr": warn_cr, "warn_systems": warn_systems,
            # what a loss would cost and what is irreplaceable
            "risk": risk, "first_systems": len(first_sys), "footfall_bio": ff_bio,
            "risk_cr": {"moderate": risk_moderate, "high": risk_high}}


def calibration(sales: List[Tuple[Optional[float], float, float]],
                since: Optional[float] = None) -> Dict[str, Any]:
    """
    B6: earnings / estimate of your own exploration sales - (time, estimate,
    earnings) as the replay saw them. Only sales from `since` on with an
    estimate of at least CAL_MIN_EST count: factor = median, lo / hi = the
    lowest and highest, n = how many; below CAL_MIN_SALES no factor.
    """
    use = [earned / est for ts, est, earned in sales
           if est >= CAL_MIN_EST and earned > 0 and (since is None or (ts is not None and ts >= since))]
    out: Dict[str, Any] = {"n": len(use), "sales": len(sales), "since": since, "min_est": CAL_MIN_EST,
                           "factor": None, "lo": None, "hi": None}
    if len(use) >= CAL_MIN_SALES:
        use.sort()
        mid = len(use) // 2
        med = use[mid] if len(use) % 2 else (use[mid - 1] + use[mid]) / 2.0
        out.update(factor=round(med, 3), lo=round(use[0], 3), hi=round(use[-1], 3))
    return out


def _explo_value(est: float, cal: Dict[str, Any]) -> Dict[str, Any]:
    """The estimate with the calibration: ~mid, lo-hi and n; the formula
    alone (calibrated False) without enough own sales."""
    est = int(round(est))
    if cal.get("factor") is None:
        return {"est": est, "mid": est, "lo": None, "hi": None, "n": cal.get("n", 0), "calibrated": False}
    return {"est": est, "mid": int(round(est * cal["factor"])), "lo": int(round(est * cal["lo"])),
            "hi": int(round(est * cal["hi"])), "n": cal["n"], "calibrated": True}


def _scan_row(e: Dict[str, Any]) -> Dict[str, Any]:
    """What bodyvalue needs of a Scan event."""
    return {"star": e.get("StarType"), "smass": e.get("StellarMass"), "pc": e.get("PlanetClass"),
            "tf": e.get("TerraformState") or "", "mass": e.get("MassEM"),
            "first": e.get("WasDiscovered") is False, "first_map": e.get("WasMapped") is False,
            "eff": True}


def _row_values(bv: Any, r: Dict[str, Any]) -> Tuple[float, float]:
    """(scan value, value once mapped) of one body row."""
    if r["star"]:
        v = bv.star_value(r["star"], r["smass"], r["first"])
        return float(v), float(v)
    if not r["pc"]:
        return 0.0, 0.0
    m = r["mass"] if r["mass"] is not None else bv.TYPICAL_MASS_EM.get(r["pc"], bv.TYPICAL_MASS_DEFAULT)
    scan = bv.planet_value(r["pc"], r["tf"], m, r["first"])
    full = bv.planet_value(r["pc"], r["tf"], m, r["first"], mapped=True, first_map=r["first_map"],
                           efficient=r["eff"])
    return float(scan), float(full)


def _where_to_sell(u: "_Unsold", systems: Set[str]) -> Dict[str, Any]:
    """5.0: where the exploration data can be sold from here. A station takes
    only systems at least STATION_MIN_LY away; a carrier with Universal
    Cartographics takes everything. Systems without a known position are
    counted apart - never guessed."""
    near, far, unknown = 0, 0, 0
    for nm in systems:
        pos = u.pos.get(nm)
        if pos is None or u.here is None:
            unknown += 1
        elif math.dist(pos, u.here) < STATION_MIN_LY:
            near += 1
        else:
            far += 1
    carrier = None
    if u.carrier_system:
        cpos = u.pos.get(u.carrier_system)
        carrier = {"system": u.carrier_system, "uc": u.carrier_uc,
                   "ly": round(math.dist(cpos, u.here), 1) if cpos and u.here else None}
    return {"min_ly": STATION_MIN_LY, "station_now": far, "too_near": near, "no_position": unknown,
            "carrier": carrier}


def _priced(bio: List[Dict[str, Any]], values: Dict[str, Dict[str, int]]
            ) -> Tuple[List[Dict[str, Any]], int, int, int]:
    """Each unsold species with its value (first footfall bonus included):
    (items, total, how many priced, how many without a known price)."""
    priced, unknown = 0, 0
    total = 0
    items = []
    for x in bio:
        v = values.get(x["species"])
        val = None
        if v and v.get("value"):
            val = v["value"] * (1 + BONUS_FACTOR if x["footfall"] else 1)
            total += val
            priced += 1
        else:
            unknown += 1
        items.append(dict(x, value=val))
    return items, total, priced, unknown


class _Unsold:
    """build_unsold's replay of the journal: what is carried unsold."""

    def __init__(self, body_value: Any = None) -> None:
        self.bv = body_value                          # plugin bodyvalue (B6), None: only counted
        self.rows: Dict[str, Dict[Any, Dict[str, Any]]] = {}   # system -> body -> value fields
        self.sales: List[Tuple[Optional[float], float, float]] = []   # (time, estimate, earnings)
        self.bio: List[Dict[str, Any]] = []
        self.scanned: Dict[str, Set[Any]] = {}        # system -> bodies scanned, not sold yet
        self.mapped: Dict[str, Set[Any]] = {}         # system -> bodies mapped, not sold yet
        self.sold_scan: Dict[str, Set[Any]] = {}      # system -> bodies whose scan was sold
        self.sold_map: Dict[str, Set[Any]] = {}       # system -> bodies whose map was sold
        self.names: Dict[Any, str] = {}               # SystemAddress -> name (jumps, honks)
        self.last_sale: Dict[str, Optional[float]] = {"bio": None, "exploration": None}
        self.lost: Optional[Dict[str, Any]] = None
        self.first_sys: Set[str] = set()              # discovered first by you, not sold yet
        self.no_foot: Set[Any] = set()                # (address, body name): nobody walked there
        self.first_foot: Set[Any] = set()             # (address, body id): your first footfall
        self.pos: Dict[str, List[float]] = {}         # system -> StarPos (5.0)
        self.here: Optional[List[float]] = None       # the last known position
        self.carrier_system: Optional[str] = None     # where the own carrier stands
        self.carrier_uc = False                       # ... and whether it buys cartographic data

    def arrival(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """A system's name by its address, and where it lies."""
        if e.get("SystemAddress") is not None:
            self.names[e["SystemAddress"]] = e.get("StarSystem")
        pos = star_pos(e.get("StarPos"))
        if pos is not None:
            self.here = pos
            if e.get("StarSystem"):
                self.pos[e["StarSystem"]] = pos

    def carrier_at(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """CarrierLocation (at login): where the own fleet carrier stands."""
        if e.get("CarrierType", "FleetCarrier") == "FleetCarrier" and e.get("StarSystem"):
            self.carrier_system = e["StarSystem"]

    def carrier_stats(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """CarrierStats: is Universal Cartographics (crew role Exploration) on board and on?"""
        crew = [c for c in e.get("Crew") or [] if c.get("CrewRole") == "Exploration"]
        if crew:
            self.carrier_uc = bool(crew[0].get("Activated")) and crew[0].get("Enabled") is not False

    def organic(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """A species analysed: carried until sold."""
        if e.get("ScanType") == "Analyse":
            sp = e.get("Species_Localised") or e.get("Species") or "?"
            self.bio.append({"species": sp, "variant": e.get("Variant_Localised") or e.get("Variant"),
                             "ts": ts, "system": self.names.get(e.get("SystemAddress")),
                             "footfall": (e.get("SystemAddress"), e.get("Body")) in self.first_foot})

    def disembark(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """On foot where nobody walked before: your first footfall."""
        if e.get("OnPlanet") and (e.get("SystemAddress"), e.get("Body")) in self.no_foot:
            self.first_foot.add((e.get("SystemAddress"), e.get("BodyID")))

    def sold_bio(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """Organic data sold: those species are no longer carried."""
        bio = self.bio
        for b in e.get("BioData") or []:
            sp = b.get("Species_Localised") or b.get("Species")
            for i, x in enumerate(bio):
                if x["species"] == sp:
                    del bio[i]
                    break
        self.last_sale["bio"] = ts

    def discovery(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """The honk names the system."""
        nm = e.get("SystemName") or self.names.get(e.get("SystemAddress"))
        if e.get("SystemAddress") is not None and nm:
            self.names[e["SystemAddress"]] = nm

    def scan(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """A body scanned (not by a nav beacon): carried until sold."""
        if e.get("ScanType") == "NavBeaconDetail":
            return
        nm = e.get("StarSystem") or self.names.get(e.get("SystemAddress"))
        body = e.get("BodyID") if e.get("BodyID") is not None else e.get("BodyName")
        if nm and body is not None and body not in self.sold_scan.get(nm, ()):
            self.scanned.setdefault(nm, set()).add(body)
            old = self.rows.setdefault(nm, {}).get(body)
            self.rows[nm][body] = dict(_scan_row(e), eff=old["eff"]) if old else _scan_row(e)
            if e.get("WasDiscovered") is False and not e.get("DistanceFromArrivalLS"):
                self.first_sys.add(nm)             # the arrival star was undiscovered
        if e.get("WasFootfalled") is False and e.get("Landable"):
            self.no_foot.add((e.get("SystemAddress"), e.get("BodyName")))

    def mapping(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """A body mapped: carried until sold."""
        nm = self.names.get(e.get("SystemAddress"))
        body = e.get("BodyID") if e.get("BodyID") is not None else e.get("BodyName")
        if nm and body is not None and body not in self.sold_map.get(nm, ()):
            self.mapped.setdefault(nm, set()).add(body)
            r = self.rows.get(nm, {}).get(body)
            if r is not None and e.get("ProbesUsed") is not None and e.get("EfficiencyTarget") is not None:
                r["eff"] = e["ProbesUsed"] <= e["EfficiencyTarget"]

    def system_est(self, nm: str) -> Tuple[float, int]:
        """B6: the bodyvalue estimate of what is unsold in a system - a body
        scanned and mapped at its mapped value, a map sold apart from its scan
        at the difference - and how many bodies have no value fields."""
        if self.bv is None:
            return 0.0, 0
        rows, scanned, mapped = self.rows.get(nm, {}), self.scanned.get(nm, set()), self.mapped.get(nm, set())
        est, missing = 0.0, 0
        for body in scanned | mapped:
            r = rows.get(body)
            if r is None:
                missing += 1
                continue
            scan, full = _row_values(self.bv, r)
            if body in scanned:
                est += full if body in mapped else scan
            else:
                est += full - scan
        return est, missing

    def sold_data(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """Exploration data sold, by system."""
        sold = [d.get("SystemName") for d in e.get("Discovered") or []] or (e.get("Systems") or [])
        est = sum(self.system_est(nm)[0] for nm in sold)
        earned = float(e.get("TotalEarnings") or e.get("Earnings") or 0)
        if est > 0:
            self.sales.append((ts, est, earned))          # B6: the calibration's raw data
        for nm in sold:
            self.rows.pop(nm, None)
            self.sold_scan.setdefault(nm, set()).update(self.scanned.pop(nm, ()))
            self.sold_map.setdefault(nm, set()).update(self.mapped.pop(nm, ()))
            self.first_sys.discard(nm)
        self.last_sale["exploration"] = ts

    def died(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """The data is gone, not sold: those bodies can be scanned again."""
        lost_sys = set(self.scanned) | set(self.mapped)
        n_sys = len(lost_sys)
        if self.bio or n_sys:
            # B6: with what it was worth (valued in build_unsold)
            self.lost = {"ts": ts, "bio": len(self.bio), "systems": n_sys,
                         "explo_est": sum(self.system_est(nm)[0] for nm in lost_sys),
                         "bio_items": list(self.bio)}
        self.bio, self.scanned, self.mapped, self.rows = [], {}, {}, {}
        self.first_sys = set()


# journal event -> its _Unsold handler (4.12)
_UNSOLD = {
    "CarrierLocation": _Unsold.carrier_at, "CarrierStats": _Unsold.carrier_stats,
    "FSDJump": _Unsold.arrival, "Location": _Unsold.arrival, "CarrierJump": _Unsold.arrival,
    "ScanOrganic": _Unsold.organic,
    "Disembark": _Unsold.disembark,
    "SellOrganicData": _Unsold.sold_bio,
    "FSSDiscoveryScan": _Unsold.discovery,
    "Scan": _Unsold.scan,
    "SAAScanComplete": _Unsold.mapping,
    "MultiSellExplorationData": _Unsold.sold_data, "SellExplorationData": _Unsold.sold_data,
    "Died": _Unsold.died,
}
