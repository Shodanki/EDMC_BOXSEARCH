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

Exploration data: only counted (its value needs a formula - B6): bodies
you scanned yourself (Scan, not a nav beacon's NavBeaconDetail) and mapped
(SAAScanComplete) that were not part of an earlier sale of their system
(MultiSellExplorationData / SellExplorationData). A honk alone is no data:
honking a system whose bodies you sold before leaves nothing to sell
(11.11.: six such systems were shown as unsold).

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
# the defaults of the settings page (fis.ini unsold_*), in M Cr / systems
DEFAULT_LIMITS = {"sell_mcr": WARN_CR // 1_000_000, "sell_systems": WARN_SYSTEMS,
                  "moderate_mcr": RISK_MODERATE_CR // 1_000_000, "high_mcr": RISK_HIGH_CR // 1_000_000}


def build_unsold(events: List[Dict[str, Any]], values: Optional[Dict[str, Dict[str, int]]] = None,
                 limits: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """What is unsold and what its loss would cost. ``limits`` (M Cr and
    systems, keys as DEFAULT_LIMITS) are the commander's own; missing keys
    take the defaults."""
    values = values or {}
    lim = dict(DEFAULT_LIMITS, **(limits or {}))
    warn_cr, warn_systems = lim["sell_mcr"] * 1_000_000, lim["sell_systems"]
    risk_moderate, risk_high = lim["moderate_mcr"] * 1_000_000, lim["high_mcr"] * 1_000_000
    u = _Unsold()
    for e in events:
        ev = e.get("event")
        handler = _UNSOLD.get(ev)
        if handler is not None:
            handler(u, ev, e, parse_ts(e.get("timestamp")))
    bio, scanned, mapped, first_sys = u.bio, u.scanned, u.mapped, u.first_sys
    items, total, priced, unknown = _priced(bio, values)
    systems = set(scanned) | set(mapped)
    advice = None
    if total >= warn_cr or len(systems) >= warn_systems:
        advice = "sell"
    ff_bio = sum(1 for x in bio if x["footfall"])
    first_sys &= systems
    risk = ("high" if total >= risk_high else
            "moderate" if total >= risk_moderate or first_sys or ff_bio else "low")
    return {"bio": {"count": len(bio), "value": total, "priced": priced, "unknown": unknown,
                    "first": sum(1 for x in bio if x["footfall"]), "items": items[-12:],
                    "since": u.last_sale["bio"]},
            "exploration": {"systems": len(systems),
                            "mapped": sum(len(v) for v in mapped.values()),
                            "bodies": sum(len(v) for v in scanned.values()),
                            "since": u.last_sale["exploration"]},
            "sell": _where_to_sell(u, systems),
            "lost_last": u.lost, "advice": advice,
            "warn_cr": warn_cr, "warn_systems": warn_systems,
            # what a loss would cost and what is irreplaceable
            "risk": risk, "first_systems": len(first_sys), "footfall_bio": ff_bio,
            "risk_cr": {"moderate": risk_moderate, "high": risk_high}}


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

    def __init__(self) -> None:
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

    def sold_data(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """Exploration data sold, by system."""
        sold = [d.get("SystemName") for d in e.get("Discovered") or []] or (e.get("Systems") or [])
        for nm in sold:
            self.sold_scan.setdefault(nm, set()).update(self.scanned.pop(nm, ()))
            self.sold_map.setdefault(nm, set()).update(self.mapped.pop(nm, ()))
            self.first_sys.discard(nm)
        self.last_sale["exploration"] = ts

    def died(self, ev: str, e: Dict[str, Any], ts: Optional[float]) -> None:
        """The data is gone, not sold: those bodies can be scanned again."""
        n_sys = len(set(self.scanned) | set(self.mapped))
        if self.bio or n_sys:
            self.lost = {"ts": ts, "bio": len(self.bio), "systems": n_sys}
        self.bio, self.scanned, self.mapped = [], {}, {}
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
