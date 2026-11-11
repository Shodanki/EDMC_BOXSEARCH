# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
K1: fleet carriers of other commanders you know from your own journals.

Without a carrier of your own (or as well as it) you meet other carriers:
you dock at them, you start missions or a community goal from them, you ride
along when they jump, and the FSS lists every carrier in a system you pass.
This module collects that per carrier - the last known position with time
and source, how often you docked, what you started there - so a carrier you
want to find again (K2 favourites) has at least its last known position.

Sources, in the order of the journal (only the commander logged in last):

  Docked / Location docked at a FleetCarrier  callsign + MarketID + system
  FSSSignalDiscovered FleetCarrier            "NAME CALLSIGN" seen in a system
  CarrierJump while docked there              the carrier moved, you with it
  MissionAccepted / CommunityGoalJoin         while docked: "started from"

The key is the callsign: FSS sightings carry no MarketID, and a carrier's
callsign never changes (its name can). Your own carrier is left out - the
CARRIER view has it already. Read only, nothing is sent anywhere.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional

# "SOME NAME K7Q-12Z" - the FSS signal of a fleet carrier
_SIGNAL = re.compile(r"^(.*?)\s*\b([A-Z0-9]{3}-[A-Z0-9]{3})$")
_CALLSIGN = re.compile(r"^[A-Z0-9]{3}-[A-Z0-9]{3}$")
MAX_STARTED = 8              # missions / CGs remembered per carrier


def parse_signal(signal: Optional[str]) -> Optional[Dict[str, str]]:
    """'SOME NAME K7Q-12Z' -> {'name': 'SOME NAME', 'callsign': 'K7Q-12Z'}."""
    m = _SIGNAL.match((signal or "").strip())
    if not m:
        return None
    return {"name": m.group(1).strip(), "callsign": m.group(2)}


def is_callsign(s: Any) -> bool:
    return isinstance(s, str) and bool(_CALLSIGN.match(s))


def own_carrier_ids(evs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """MarketID and callsign of the commander's own carrier, if any."""
    out: Dict[str, Any] = {"market_id": None, "callsign": None}
    for e in evs:
        if e.get("event") == "CarrierStats" and e.get("CarrierType", "FleetCarrier") == "FleetCarrier":
            out = {"market_id": e.get("CarrierID"), "callsign": e.get("Callsign")}
        elif (e.get("event") == "CarrierLocation" and e.get("CarrierID")
              and e.get("CarrierType", "FleetCarrier") == "FleetCarrier"):
            out["market_id"] = e.get("CarrierID")
    return out


class DockTracker:
    """Where the commander is docked, event by event (None = not docked)."""

    def __init__(self) -> None:
        self.at: Optional[Dict[str, Any]] = None

    def feed(self, e: Dict[str, Any]) -> None:
        ev = e.get("event")
        if ev == "Docked" or (ev == "Location" and e.get("Docked")):
            self.at = {"type": e.get("StationType"), "name": e.get("StationName"),
                       "market_id": e.get("MarketID")}
        elif ev in ("Undocked", "FSDJump", "LoadGame", "Died", "Resurrect") or (
                ev == "Location" and not e.get("Docked")):
            self.at = None

    def carrier(self) -> Optional[Dict[str, Any]]:
        """The fleet carrier we are docked at (on foot aboard counts)."""
        if self.at and self.at.get("type") == "FleetCarrier":
            return self.at
        return None


def known_carriers(evs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """callsign -> what the journal tells about that carrier."""
    own = own_carrier_ids(evs)
    systems: Dict[int, Dict[str, Any]] = {}      # SystemAddress -> name, pos
    dock = DockTracker()
    out: Dict[str, Dict[str, Any]] = {}

    def is_own(cs: Optional[str], mid: Any) -> bool:
        return bool((mid and mid == own["market_id"]) or (cs and cs == own["callsign"]))

    def entry(cs: str) -> Dict[str, Any]:
        return out.setdefault(cs, {"callsign": cs, "name": None, "market_id": None,
                                   "system": None, "id64": None, "pos": None, "ts": None,
                                   "how": None, "first_ts": None, "docked_n": 0,
                                   "last_docked": None, "sightings": 0, "started": []})

    def place(c: Dict[str, Any], e: Dict[str, Any], how: str, a: Any = None) -> None:
        ts = e.get("timestamp")
        a = a if a is not None else e.get("SystemAddress")
        s = systems.get(a) if a is not None else None
        c["first_ts"] = c["first_ts"] or ts
        if c["ts"] and ts and ts < c["ts"]:
            return
        c["ts"], c["how"], c["id64"] = ts, how, a
        c["system"] = e.get("StarSystem") or (s or {}).get("name")
        c["pos"] = e.get("StarPos") or (s or {}).get("pos")

    for e in evs:
        ev = e.get("event")
        if e.get("SystemAddress") is not None and e.get("StarSystem"):
            s = systems.setdefault(e["SystemAddress"], {})
            s["name"] = e["StarSystem"]
            if e.get("StarPos"):
                s["pos"] = e["StarPos"]
        before = dock.carrier()
        dock.feed(e)
        here = dock.carrier()
        if ev == "FSSSignalDiscovered" and e.get("SignalType") == "FleetCarrier":
            p = parse_signal(e.get("SignalName"))
            if not p or is_own(p["callsign"], None):
                continue
            c = entry(p["callsign"])
            if p["name"]:
                c["name"] = p["name"]
            c["sightings"] += 1
            place(c, e, "sighted")
        elif ev in ("Docked", "Location") and here and here is not before:
            cs = here.get("name")
            if not is_callsign(cs) or is_own(cs, here.get("market_id")):
                continue
            c = entry(cs)
            c["market_id"] = here.get("market_id") or c["market_id"]
            if ev == "Docked":
                c["docked_n"] += 1
            c["last_docked"] = e.get("timestamp")
            place(c, e, "docked")
        elif ev == "CarrierJump" and here:
            cs = here.get("name")
            if not is_callsign(cs) or is_own(cs, here.get("market_id")):
                continue
            place(entry(cs), e, "jump")
        elif ev in ("MissionAccepted", "CommunityGoalJoin") and here:
            cs = here.get("name")
            if not is_callsign(cs) or is_own(cs, here.get("market_id")):
                continue
            c = entry(cs)
            if ev == "MissionAccepted":
                item = {"kind": "mission", "ts": e.get("timestamp"),
                        "name": e.get("LocalisedName") or e.get("Name"),
                        "commodity": e.get("Commodity_Localised") or e.get("Commodity"),
                        "count": e.get("Count"), "to": e.get("DestinationSystem"),
                        "expiry": e.get("Expiry")}
            else:
                item = {"kind": "cg", "ts": e.get("timestamp"), "name": e.get("Name"),
                        "to": e.get("System")}
            c["started"] = (c["started"] + [item])[-MAX_STARTED:]
    return out


def own_jump_flags(evs: List[Dict[str, Any]]) -> List[bool]:
    """
    For each event: True when it is a CarrierJump of SOMEONE ELSE's carrier
    (you were docked at it or aboard on foot). The own-carrier views must
    not take those as a jump of your carrier.
    """
    own = own_carrier_ids(evs)
    dock = DockTracker()
    flags = []
    for e in evs:
        dock.feed(e)
        foreign = False
        if e.get("event") == "CarrierJump":
            here = dock.carrier()
            if here:
                mid, cs = here.get("market_id"), here.get("name")
                foreign = not ((mid and mid == own["market_id"]) or (cs and cs == own["callsign"]))
        flags.append(foreign)
    return flags


MAX_SIGHTED = 40             # carriers only seen in passing, newest first


def _dist(a: Any, b: Any) -> Optional[float]:
    try:
        return round(math.dist([float(v) for v in a[:3]], [float(v) for v in b[:3]]), 1)
    except (TypeError, ValueError, IndexError):
        return None


def build_known(archive: Any, store: Any, live: Optional[Dict[str, Any]] = None,
                sighted: int = MAX_SIGHTED) -> Dict[str, Any]:
    """
    K4 data for /api/carriers/known: favourites first, then the carriers you
    docked at or started something from, then the newest sightings. Each
    with the last known position (journal, or the position stored with the
    favourite when the journal no longer has it), its distance from you and
    - K3 - the last market seen there.
    """
    fid, name = archive.commander()
    evs = archive.events()
    known = known_carriers(evs)
    saved = store.get(fid) if store is not None else {"favourites": {}, "markets": {}}
    favs, markets = saved["favourites"], saved["markets"]
    here = ((live or {}).get("system") or {}).get("pos")

    def item(cs: str) -> Dict[str, Any]:
        k = known.get(cs)
        f = favs.get(cs)
        it: Dict[str, Any] = dict(k) if k else {
            "callsign": cs, "docked_n": 0, "sightings": 0, "started": [], "last_docked": None,
            "first_ts": None}
        if f:
            for key in ("name", "market_id", "system", "id64", "pos", "ts", "how"):
                if it.get(key) is None and f.get(key) is not None:
                    it[key] = f[key]
            if not k:
                it["from_store"] = True     # the journal does not have it (any more)
        it["favourite"] = bool(f)
        it["note"] = (f or {}).get("note") or ""
        it["online"] = (f or {}).get("online")       # K5: last lookup at Spansh
        it["market"] = markets.get(cs)
        it["dist_ly"] = _dist(it.get("pos"), here) if here and it.get("pos") else None
        return it

    fav_items = sorted((item(cs) for cs in favs), key=lambda i: i.get("ts") or "", reverse=True)
    rest = [cs for cs in known if cs not in favs]
    met = sorted((item(cs) for cs in rest if known[cs]["docked_n"] or known[cs]["started"]
                  or known[cs]["last_docked"] or known[cs]["how"] == "jump"),
                 key=lambda i: i.get("ts") or "", reverse=True)
    met_cs = {i["callsign"] for i in met}
    seen = sorted((cs for cs in rest if cs not in met_cs),
                  key=lambda cs: known[cs].get("ts") or "", reverse=True)
    if store is not None and fid:
        # keep the stored position of a favourite current while the journal has it
        for cs in favs:
            if cs in known:
                try:
                    store.remember_position(fid, cs, known[cs])
                except OSError:
                    pass
    return {"commander": name, "favourites": fav_items, "met": met,
            "sighted": [item(cs) for cs in seen[:max(0, sighted)]],
            "counts": {"known": len(known), "favourites": len(favs), "sighted": len(seen)}}


def mark_favourite_pois(poi: List[Dict[str, Any]], favs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """K4: SYSTEM points of interest - your favourite carriers get a star and
    come first among the carriers (the view shows only the newest few).
    Returns a new list; the cached system stays untouched."""
    if not favs:
        return poi
    out = []
    for p in poi:
        if p.get("kind") == "carrier":
            nm = p.get("name") or ""
            cs = nm if is_callsign(nm) else (parse_signal(nm) or {}).get("callsign")
            if cs in favs:
                p = dict(p, favourite=True, callsign=cs)
        out.append(p)
    first = [i for i, p in enumerate(out) if p.get("kind") == "carrier"]
    if first:
        cars = [out[i] for i in first]
        cars.sort(key=lambda p: not p.get("favourite"))          # stable: newest first stays
        for i, p in zip(first, cars):
            out[i] = p
    return out
