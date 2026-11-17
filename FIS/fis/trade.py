# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
TRADE (5.0, HD1): what your goods fetched, and what they are worth.

Per commodity, from the journal of the active commander:

  sold      every MarketSell - tonnes, earnings, the average price per tonne
            with the lowest and highest and the number of sales; goods you
            did not buy (AvgPricePaid 0: mined, collected) are marked
  mean      the galactic average price (MeanPrice) per commodity, kept from
            every Market.json read that had one (market_means.json next to
            fis.ini) with where and when - a comparison, not an offer. Up
            to 5.0 only the last Market.json counted: after a fleet carrier
            (no MeanPrice) the column was empty (test finding h-tab)
  here      what this market pays now (SellPrice, Demand) - only while docked
            at the very market of that Market.json, opened since docking

The hold (Cargo.json) and what you mined (MiningRefined) come first. Reads
the journal folder only; nothing is sent.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional

from .live import parse_ts


def key_of(name: Optional[str]) -> str:
    """'$tritium_name;' / 'Tritium' -> 'tritium'."""
    s = (name or "").strip().strip("$;").lower()
    return s[:-5] if s.endswith("_name") else s.replace(" ", "")


def _sales(evs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """MarketSell per commodity: tonnes, earnings, prices, sales."""
    out: Dict[str, Dict[str, Any]] = {}
    for e in evs:
        if e.get("event") != "MarketSell" or not e.get("Count"):
            continue
        k = key_of(e.get("Type"))
        n, price = int(e["Count"]), int(e.get("SellPrice") or 0)
        s = out.setdefault(k, {"key": k, "name": e.get("Type_Localised") or k.capitalize(), "t": 0, "cr": 0,
                               "sales": 0, "lo": price, "hi": price, "own": True, "last": None})
        s["t"] += n
        s["cr"] += int(e.get("TotalSale") or n * price)
        s["sales"] += 1
        s["lo"], s["hi"] = min(s["lo"], price), max(s["hi"], price)
        s["own"] = s["own"] and not e.get("AvgPricePaid")      # mined or collected, not bought
        s["last"] = parse_ts(e.get("timestamp"))
    for s in out.values():
        s["avg"] = round(s["cr"] / s["t"]) if s["t"] else None
    return out


def _read_json(path: str) -> Dict[str, Any]:
    from .shipview import _read_json as rj
    return rj(path) or {}


_MEANS_LOCK = threading.Lock()


def _load_means(path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    try:
        with open(path or "", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remember_means(path: Optional[str], market: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The galactic mean per commodity: what is kept in `path`, brought up
    to date with this Market.json's MeanPrice (newer wins; a market without
    means, a fleet carrier, changes nothing). Written only when something
    changed (temporary file + os.replace); None = keep nothing."""
    with _MEANS_LOCK:
        known = _load_means(path)
        ts = parse_ts(market.get("timestamp")) or 0
        changed = False
        for it in market.get("Items") or []:
            mean = int(it.get("MeanPrice") or 0)
            k = key_of(it.get("Name"))
            if mean <= 0 or not k or (known.get(k) or {}).get("ts", 0) >= ts:
                continue
            known[k] = {"mean": mean, "station": market.get("StationName"), "ts": ts}
            changed = True
        if changed and path:
            try:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(known, fh, indent=1, sort_keys=True)
                os.replace(tmp, path)
            except OSError:
                pass
        return known


def _docked_here(archive: Any, live: Dict[str, Any], market: Dict[str, Any]) -> bool:
    """Docked (Status.json) at the market of Market.json, opened since docking."""
    if not (int((live.get("status") or {}).get("flags") or 0) & 1) or not market.get("MarketID"):
        return False
    dock = next((e for e in reversed(archive.events())
                 if e.get("event") == "Docked" or (e.get("event") == "Location" and e.get("Docked"))), None)
    return bool(dock and dock.get("MarketID") == market.get("MarketID")
                and (market.get("timestamp") or "") >= (dock.get("timestamp") or ""))


def build_trade(archive: Any, live: Optional[Dict[str, Any]], journal_dir: Optional[str],
                means_path: Optional[str] = None) -> Dict[str, Any]:
    """The TRADE view: one row per commodity you carry, mined or sold, with
    the galactic means kept in `means_path`."""
    live = live or {}
    evs = archive.events()
    sold = _sales(evs)
    mined = {key_of(e.get("Type")): e.get("Type_Localised") for e in evs if e.get("event") == "MiningRefined"}
    cargo = _read_json(os.path.join(journal_dir, "Cargo.json")) if journal_dir else {}
    hold = {key_of(c.get("Name")): (int(c.get("Count") or 0), c.get("Name_Localised"))
            for c in (cargo.get("Inventory") or []) if cargo.get("Vessel", "Ship") == "Ship"}
    hold.pop("drones", None)
    market = _read_json(os.path.join(journal_dir, "Market.json")) if journal_dir else {}
    here = _docked_here(archive, live, market)
    items = {key_of(i.get("Name")): i for i in market.get("Items") or []}
    means = remember_means(means_path, market)
    rows = []
    for k in set(sold) | set(mined) | set(hold):
        it = items.get(k) or {}
        s = sold.get(k) or {}
        name = (s.get("name") or (hold.get(k) or (0, None))[1] or mined.get(k) or it.get("Name_Localised")
                or k.capitalize())
        mean = means.get(k) or {}
        rows.append({"key": k, "name": name, "hold": (hold.get(k) or (0, None))[0], "mined": k in mined,
                     "sold": s or None, "mean": mean.get("mean"),
                     "mean_from": {"station": mean.get("station"), "ts": mean.get("ts")} if mean else None,
                     "vs_mean": (round(100.0 * s["avg"] / mean["mean"] - 100) if s.get("avg") and mean.get("mean")
                                 else None),
                     "here": ({"price": int(it.get("SellPrice") or 0), "demand": int(it.get("Demand") or 0)}
                              if here and it else None)})
    rows.sort(key=lambda r: (-r["hold"], not r["mined"], -((r["sold"] or {}).get("cr") or 0), r["name"]))
    return {"rows": rows, "docked_here": here, "means": len(means),
            "earned": sum((r["sold"] or {}).get("cr") or 0 for r in rows),
            "sales": sum((r["sold"] or {}).get("sales") or 0 for r in rows),
            "market": {"station": market.get("StationName"), "system": market.get("StarSystem"),
                       "type": market.get("StationType"), "ts": parse_ts(market.get("timestamp"))}
            if market.get("MarketID") else None}
