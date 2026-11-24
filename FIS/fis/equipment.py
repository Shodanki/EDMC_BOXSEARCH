# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
EQ1 (5.1.0, user 24.11.): the equipment in storage - on your own carrier, or,
without one, at the stations where it lies.

The game lists every stored module in ``StoredModules`` each time you open
Outfitting > Storage. The newest such list of the commander is read from the
journals on disk (read only; not kept in the archive - a list of 350
modules, written hundreds of times, would not fit in memory). What was
stored, retrieved, sold or sent off since then comes from the small events
(``ModuleStore``, ``MassModuleStore``, ``ModuleBuy`` with ``StoredItem``,
``ModuleRetrieve``, ``ModuleSellRemote``, ``FetchRemoteModule``).

Per module: category, slot and size, how many, where, the price paid when
the game says it, the engineering - and which of your own ships it fits by
slot and size (from each ship's last Loadout), and where it is better than
what is fitted: the same kind of module, larger or a better class, or
engineered where the fitted one is not. The game has more rules (some
modules only in some hulls); those are not checked and the page says so.

EDSY and Coriolis get links with the ship's Loadout, built the way EDMC
builds its own shipyard links: the page only opens them on a click, in your
browser - the FIS itself sends nothing.
"""
import base64
import glob
import gzip
import json
import os
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import fleet as fl
from .live import parse_ts

# the small events the archive keeps for this (fleet.EVENTS)
EVENTS = ("ModuleStore", "MassModuleStore", "ModuleBuy", "ModuleRetrieve", "ModuleSellRemote",
          "FetchRemoteModule")

_CORE = {"int_powerplant": "PowerPlant", "int_engine": "MainEngines", "int_hyperdrive": "FrameShiftDrive",
         "int_lifesupport": "LifeSupport", "int_powerdistributor": "PowerDistributor", "int_sensors": "Radar"}
_MILITARY = ("int_hullreinforcement", "int_modulereinforcement", "int_guardianhullreinforcement",
             "int_guardianmodulereinforcement")
_MOUNT = (("_small", 1), ("_medium", 2), ("_large", 3), ("_huge", 4))
GROUPS = ("core", "optional", "hardpoint", "utility", "armour")
_FAMILY_RX = re.compile(r"_size\d+_class\d|_(fixed|gimbal|turret)_(tiny|small|medium|large|huge)$"
                        r"|_(tiny|small|medium|large|huge)$")

_lock = threading.Lock()
_cache: Dict[str, Any] = {"key": None, "snap": None}


def item_key(raw: Optional[str]) -> str:
    """"$int_engine_size5_class5_name;" -> "int_engine_size5_class5"."""
    return re.sub(r"^\$|_name;$|;$", "", (raw or "").strip().lower())


def classify(item: str) -> Dict[str, Any]:
    """Category, size and class of a module from its internal name:
    {"group", "size", "cls", "core" (the core slot or None), "hull" (armour:
    the ship type it belongs to)}."""
    m = re.search(r"size(\d+)_class(\d)", item)
    size, cls = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    if "_armour_" in item:
        return {"group": "armour", "size": None, "cls": None, "core": "Armour", "hull": item.split("_armour_")[0]}
    if item.startswith("hpt_"):
        if item.startswith(fl._UTILITY_NOT_WEAPON):
            return {"group": "utility", "size": 0, "cls": cls, "core": None, "hull": None}
        size = next((v for k, v in _MOUNT if k in item), size)
        return {"group": "hardpoint", "size": size, "cls": cls, "core": None, "hull": None}
    core = next((v for k, v in _CORE.items() if item.startswith(k)), None)
    return {"group": "core" if core else "optional", "size": size, "cls": cls, "core": core, "hull": None}


def _family(item: str) -> str:
    """The kind of module, without size, class and mount: for "better than fitted"."""
    return _FAMILY_RX.sub("", item)


# ------------------------------------------------------------ the storage list
def _scan_file(path: str, fid: Optional[str]) -> Optional[Dict[str, Any]]:
    """The last StoredModules of this commander in one journal file, or None."""
    found, cur = None, None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"StoredModules"' not in line and '"Commander"' not in line and '"LoadGame"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("event") in ("Commander", "LoadGame"):
                    cur = e.get("FID") or cur
                elif e.get("event") == "StoredModules" and (fid is None or cur in (None, fid)):
                    found = e
    except OSError:
        return None
    return found


def latest_snapshot(journal_dir: Optional[str], fid: Optional[str]) -> Optional[Dict[str, Any]]:
    """The newest StoredModules of the commander in the journals on disk,
    newest file first; remembered until a newer file or line appears."""
    if not journal_dir:
        return None
    paths = sorted(glob.glob(os.path.join(journal_dir, "Journal.*.log")), reverse=True)
    sizes = []
    for p in paths:
        try:
            sizes.append((p, os.path.getsize(p)))
        except OSError:
            continue
    with _lock:
        key, snap = _cache["key"], _cache["snap"]
    for i, (p, n) in enumerate(sizes):
        if key and key[0] == fid and (p, n) == key[1]:
            return snap                            # nothing newer than the list we have
        got = _scan_file(p, fid)
        if got is not None:
            with _lock:
                _cache.update(key=(fid, (p, n)), snap=got)
            return got
    return None


# ------------------------------------------------------------ what changed since
def _from_snapshot(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for it in snap.get("Items") or []:
        raw = it.get("Name") or ""
        out.append({"item": item_key(raw), "name": fl.readable_module(it.get("Name_Localised"), raw),
                    "system": it.get("StarSystem"), "market": it.get("MarketID"),
                    "eng": it.get("EngineerModifications"), "level": it.get("Level"), "quality": it.get("Quality"),
                    "hot": bool(it.get("Hot")), "price": it.get("BuyPrice") or None, "slot_no": it.get("StorageSlot"),
                    "transit_until": (parse_ts(snap.get("timestamp")) or 0) + it["TransferTime"]
                    if it.get("InTransit") and it.get("TransferTime") else None})
    return out


def _take_out(items: List[Dict[str, Any]], item: str, market: Any = None, slot_no: Any = None,
              eng: Any = None) -> Optional[Dict[str, Any]]:
    """Remove one stored module: by storage slot, else by name at that market
    (the same engineering first)."""
    cand = [x for x in items if slot_no is not None and x["slot_no"] == slot_no]
    if not cand:
        cand = [x for x in items if x["item"] == item and (market is None or x["market"] == market)]
        cand.sort(key=lambda x: x["eng"] != eng)
    if cand:
        items.remove(cand[0])
        return cand[0]
    return None


def _stored(e: Dict[str, Any], raw: str, loc_key: str, dock: Dict[str, Any]) -> Dict[str, Any]:
    return {"item": item_key(raw), "name": fl.readable_module(e.get(loc_key), raw),
            "system": dock.get("system"), "market": e.get("MarketID") or dock.get("market"),
            "eng": e.get("EngineerModifications"), "level": e.get("Level"), "quality": e.get("Quality"),
            "hot": bool(e.get("Hot")), "price": None, "slot_no": None, "transit_until": None}


def _apply(items: List[Dict[str, Any]], e: Dict[str, Any], dock: Dict[str, Any]) -> None:
    """One event after the list."""
    ev = e["event"]
    if ev == "ModuleStore" and e.get("StoredItem"):
        items.append(_stored(e, e["StoredItem"], "StoredItem_Localised", dock))
    elif ev == "ModuleBuy" and e.get("StoredItem"):
        items.append(_stored({"MarketID": e.get("MarketID"), "StoredItem_Localised": e.get("StoredItem_Localised")},
                             e["StoredItem"], "StoredItem_Localised", dock))
    elif ev == "MassModuleStore":
        for it in e.get("Items") or []:
            items.append(_stored(dict(it, MarketID=e.get("MarketID")), it.get("Name") or "", "Name_Localised", dock))
    elif ev == "ModuleRetrieve" and e.get("RetrievedItem"):
        _take_out(items, item_key(e["RetrievedItem"]), e.get("MarketID"), eng=e.get("EngineerModifications"))
    elif ev == "ModuleSellRemote":
        _take_out(items, item_key(e.get("SellItem")), slot_no=e.get("StorageSlot"))
    elif ev == "FetchRemoteModule":
        x = _take_out(items, item_key(e.get("StoredItem")), slot_no=e.get("StorageSlot"))
        if x is not None:
            x.update(system=dock.get("system"), market=dock.get("market"), slot_no=None,
                     transit_until=(parse_ts(e.get("timestamp")) or 0) + (e.get("TransferTime") or 0))
            items.append(x)


def stored_now(snap: Optional[Dict[str, Any]], evs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The modules in storage now: the last list plus what happened since."""
    if not snap:
        return []
    items = _from_snapshot(snap)
    ts = snap.get("timestamp") or ""
    dock: Dict[str, Any] = {}
    for e in evs:
        ev = e.get("event")
        if ev == "Docked" or (ev == "Location" and e.get("Docked")):
            dock = {"system": e.get("StarSystem"), "market": e.get("MarketID")}
        if (e.get("timestamp") or "") > ts and ev in EVENTS:
            _apply(items, e, dock)
    return items


# ------------------------------------------------------------ which ship it fits
def ship_slots(lo: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The slots of a fitting that take modules: {slot, group, size, item}."""
    out = []
    for m in lo.get("Modules") or []:
        slot = m.get("Slot") or ""
        grp = fl.slot_group(slot)
        it = item_key(m.get("Item"))
        if grp == "core":
            mm = re.search(r"size(\d+)", it)
            out.append({"slot": slot, "group": "core", "size": int(mm.group(1)) if mm else None, "item": it})
        elif grp in ("optional", "hardpoints", "utility"):
            out.append({"slot": slot, "group": {"hardpoints": "hardpoint"}.get(grp, grp),
                        "size": fl.slot_size(slot), "item": it})
    return out


def fits_slot(item: str, c: Dict[str, Any], s: Dict[str, Any]) -> bool:
    """Whether a stored module goes into this slot, by slot and size."""
    if c["group"] == "armour":
        return False
    if c["core"]:
        return s["group"] == "core" and s["slot"] == c["core"] and _size_ok(c["size"], s["size"])
    if item.startswith("int_fueltank") and s["slot"] == "FuelTank":
        return _size_ok(c["size"], s["size"])
    if s["group"] != c["group"]:
        return False
    if s["slot"].startswith("Military") and not item.startswith(_MILITARY):
        return False
    return c["group"] == "utility" or _size_ok(c["size"], s["size"])


def _size_ok(size: Optional[int], slot: Optional[int]) -> bool:
    return size is None or slot is None or size <= slot


def better(item: str, c: Dict[str, Any], eng: bool, fitted: str, fitted_eng: bool) -> bool:
    """Same kind of module as the fitted one, and larger, a better class or
    engineered where the fitted one is not - never an engineered one swapped
    for a plain one."""
    if not fitted or _family(item) != _family(fitted) or (fitted_eng and not eng):
        return False
    f = classify(fitted)
    if (c["size"] or 0) != (f["size"] or 0):
        return (c["size"] or 0) > (f["size"] or 0)
    if (c["cls"] or 0) != (f["cls"] or 0):
        return (c["cls"] or 0) > (f["cls"] or 0)
    return eng and not fitted_eng


def _ship_fit(item: str, c: Dict[str, Any], eng: bool, ship: Dict[str, Any]) -> Tuple[bool, bool]:
    """(fits a slot of this ship, better than what is fitted in one of them).
    A Loadout lists only filled slots, so empty ones are not known."""
    if c["group"] == "armour":
        same = c["hull"] == ship["type"]
        return same, same and eng and not ship["eng"].get("Armour")
    fit = upg = False
    for s in ship["slots"]:
        if fits_slot(item, c, s):
            fit = True
            upg = upg or better(item, c, eng, s["item"], bool(ship["eng"].get(s["slot"])))
    return fit, upg


# ------------------------------------------------------------ links to the planners
def _encode(lo: Dict[str, Any]) -> str:
    data = {k: v for k, v in lo.items() if not k.startswith("_")}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(gzip.compress(raw, mtime=0)).decode("ascii").replace("=", "%3D")


def planner_links(lo: Dict[str, Any]) -> Dict[str, str]:
    """EDSY and Coriolis import links for a Loadout, as EDMC makes them."""
    enc = _encode(lo)
    return {"edsy": "https://edsy.org/#/I=" + enc, "coriolis": "https://coriolis.io/import?data=" + enc}


# ------------------------------------------------------------ the view
def _ships(evs: List[Dict[str, Any]], fleet_ships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Own ships with a known fitting: name, type, slots, engineered slots, links."""
    loadouts = fl._fleet_history(evs)[0]
    by_id = {s["id"]: s for s in fleet_ships if s.get("id") is not None}
    fits = fl._fittings(evs, by_id, loadouts)
    for sid, lo in loadouts.items():
        if sid in by_id and sid not in fits and (lo.get("Ship") or "").lower() == by_id[sid].get("type"):
            fits[sid] = lo
    out = []
    for sid, lo in fits.items():
        s = by_id[sid]
        out.append({"id": sid, "name": s.get("name") or lo.get("ShipName") or s.get("type_name"),
                    "type": (lo.get("Ship") or "").lower(), "type_name": s.get("type_name"),
                    "current": bool(s.get("current")), "slots": ship_slots(lo),
                    "eng": {m.get("Slot"): True for m in lo.get("Modules") or [] if m.get("Engineering")},
                    **planner_links(lo)})
    out.sort(key=lambda x: (not x["current"], x["name"] or ""))
    return out


def _where(x: Dict[str, Any], carrier_id: Any, stations: Dict[Any, str]) -> Tuple[str, str]:
    if carrier_id is not None and x["market"] == carrier_id:
        return "carrier", stations.get(carrier_id) or ""
    return "station", stations.get(x["market"]) or x["system"] or "?"


def _grade(x: Dict[str, Any]) -> Optional[str]:
    if not x["eng"]:
        return None
    bp = re.sub(r"([a-z])([A-Z])", r"\1 \2", x["eng"]).replace("_", " · ")
    return ("G%s " % x["level"] if x.get("level") else "") + bp


def _rows(items: List[Dict[str, Any]], ships: List[Dict[str, Any]], carrier_id: Any,
          stations: Dict[Any, str], now: float) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for x in items:
        place, where = _where(x, carrier_id, stations)
        k = (x["item"], x["eng"], x.get("level"), x["market"], x["hot"])
        g = groups.get(k)
        if g is None:
            c = classify(x["item"])
            mod = fl.module_name(x["item"])
            g = groups[k] = {"item": x["item"], "name": x["name"], "code": mod, "group": c["group"],
                             "mount": next((m for m in ("fixed", "gimbal", "turret") if "_%s_" % m in x["item"]), None),
                             "size": c["size"], "cls": fl._CLASS.get(str(c["cls"])) if c["cls"] else None,
                             "eng": _grade(x), "hot": x["hot"], "count": 0, "value": 0, "priced": 0,
                             "place": place, "where": where, "system": x["system"], "transit_s": 0,
                             "fits": [], "better": []}
            for s in ships:
                fit, upg = _ship_fit(x["item"], c, bool(x["eng"]), s)
                if fit:
                    g["fits"].append(s["name"])
                if upg:
                    g["better"].append(s["name"])
        g["count"] += 1
        if x["price"]:
            g["value"] += x["price"]
            g["priced"] += 1
        if x["transit_until"] and x["transit_until"] > now:
            g["transit_s"] = max(g["transit_s"], int(x["transit_until"] - now))
    rows = list(groups.values())
    rows.sort(key=lambda r: (GROUPS.index(r["group"]), r["place"] != "carrier", r["name"] or "", -(r["size"] or 0)))
    return rows


def _stations(evs: Iterable[Dict[str, Any]], snap: Dict[str, Any]) -> Dict[Any, str]:
    names: Dict[Any, str] = {}
    for e in evs:
        if e.get("MarketID") and e.get("StationName") and e.get("event") in ("Docked", "Location", "Market"):
            names[e["MarketID"]] = e["StationName"]
    if snap.get("MarketID") and snap.get("StationName"):
        names[snap["MarketID"]] = snap["StationName"]
    return names


def build_equipment(archive: Any, journal_dir: Optional[str], now: float) -> Dict[str, Any]:
    """EQUIPMENT: what lies in storage, where, and what it fits."""
    fid = archive.commander()[0]
    evs = archive.events()
    snap = latest_snapshot(journal_dir, fid)
    if not snap:
        return {"generated": now, "empty": True}
    car = archive.carrier()
    carrier_id = ((car or {}).get("stats") or {}).get("CarrierID")
    stations = _stations(evs, snap)
    if carrier_id is not None:
        cs = (car or {}).get("stats") or {}
        stations[carrier_id] = " ".join(x for x in (cs.get("Name"), cs.get("Callsign")) if x)
    ships = _ships(evs, archive.fleet()["ships"])
    rows = _rows(stored_now(snap, evs), ships, carrier_id, stations, now)
    places: Dict[str, int] = {}
    for r in rows:
        places[r["where"]] = places.get(r["where"], 0) + r["count"]
    for s in ships:
        s["fits_n"] = sum(1 for r in rows if s["name"] in r["fits"])
        s["better_n"] = sum(1 for r in rows if s["name"] in r["better"])
        s.pop("slots")
        s.pop("eng")
    return {"generated": now, "list_ts": snap.get("timestamp"), "list_at": snap.get("StationName"),
            "carrier": stations.get(carrier_id) if carrier_id is not None else None,
            "count": sum(r["count"] for r in rows), "rows": rows, "ships": ships,
            "places": sorted(places.items(), key=lambda p: -p[1])}
