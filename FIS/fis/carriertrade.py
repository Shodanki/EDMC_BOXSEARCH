# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0 CT1: CARRIER TRADE - what the own carrier buys and sells and what is
still wanted: the commodity market, the bar (on-foot goods), the shipyard
and outfitting.

Two sources, both read only:
- Frontier's answer to /fleetcarrier (capi_fleetcarrier.json, written by the
  plugin while EDMC runs with a Frontier login): the orders with what is
  still open, the market's stock, the bar, the shipyard and outfitting
  stock, the market's and the bar's profit;
- the journal: CarrierTradeOrder - when an order was set, changed or
  cancelled, for the history.

Without the Companion file only the history is there; the view says so.
Nothing is sent anywhere; nothing is guessed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional

from . import capi
from .fleet import module_name
from .live import parse_ts

HISTORY = 20                     # the last trade orders from the journal


def _int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _items(v: Any) -> List[Dict[str, Any]]:
    """Frontier sends an empty list, a list or a dict keyed by id."""
    if isinstance(v, dict):
        v = list(v.values())
    return [x for x in v or [] if isinstance(x, dict)]


def _name(x: Dict[str, Any], names: Optional[Dict[str, str]] = None) -> str:
    """The game's own name; an order only names the symbol ("tritium") -
    then the market's name for it, else the symbol capitalised."""
    if x.get("locName"):
        return str(x["locName"])
    sym = str(x.get("name") or "")
    return (names or {}).get(sym.lower()) or (sym[:1].upper() + sym[1:] if sym else "?")


def _orders(block: Any, names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Sales and purchase orders of one market (goods or bar): what is set,
    what is still open, what it is worth."""
    block = block if isinstance(block, dict) else {}
    sales = [{"name": _name(x, names), "stock": _int(x.get("stock")), "price": _int(x.get("price")),
              "value": _int(x.get("stock")) * _int(x.get("price")), "black": bool(x.get("blackmarket"))}
             for x in _items(block.get("sales"))]
    buys = []
    for x in _items(block.get("purchases")):
        total, left, price = _int(x.get("total")), _int(x.get("outstanding")), _int(x.get("price"))
        buys.append({"name": _name(x, names), "total": total, "outstanding": left, "delivered": max(0, total - left),
                     "price": price, "open_cr": left * price, "black": bool(x.get("blackmarket"))})
    sales.sort(key=lambda r: -r["value"])
    buys.sort(key=lambda r: -r["open_cr"])
    return {"sales": sales, "purchases": buys,
            "sales_cr": sum(r["value"] for r in sales), "open_cr": sum(r["open_cr"] for r in buys),
            "open_units": sum(r["outstanding"] for r in buys)}


def _finances(f: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(f, dict):
        return None
    return {"cargo_value": _int(f.get("cargoTotalValue") or f.get("microresourcesTotalValue")),
            "profit": _int(f.get("allTimeProfit")), "alloc": _int(f.get("balanceAllocForPurchaseOrders")),
            "for_sale": _int(f.get("numCommodsForSale") or f.get("microresourcesForSale")),
            "purchase_orders": _int(f.get("numCommodsPurchaseOrders") or f.get("microresourcesPurchaseOrders"))}


def _market_stock(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The market as visitors see it, without the service goods (limpets)."""
    c = d.get("commodities")
    rows = _items(c.get("commodities") if isinstance(c, dict) else c)
    out = [{"name": _name(x), "stock": _int(x.get("stock")), "demand": _int(x.get("demand")),
            "buy": _int(x.get("buyPrice")), "sell": _int(x.get("sellPrice"))}
           for x in rows if str(x.get("categoryname") or "").lower() != "nonmarketable"]
    return sorted(out, key=lambda r: -(r["stock"] + r["demand"]))


def _service(d: Dict[str, Any], key: str) -> Optional[str]:
    m = d.get("market") if isinstance(d.get("market"), dict) else {}
    s = m.get("services") if isinstance(m.get("services"), dict) else {}
    return s.get(key)


def _bar(d: Dict[str, Any]) -> Dict[str, Any]:
    fin = d.get("finance") if isinstance(d.get("finance"), dict) else {}
    bt = fin.get("bartender") if isinstance(fin.get("bartender"), dict) else {}
    orders = d.get("orders") if isinstance(d.get("orders"), dict) else {}
    hist = [_int(v) for v in bt.get("profitHistory") or [] if isinstance(v, (int, float))]
    return {"status": _service(d, "bartender"), "finances": _finances(bt), "profit_history": hist,
            "capacity": _int((d.get("capacity") or {}).get("microresourceCapacityTotal")),
            "used": _int((d.get("capacity") or {}).get("microresourceCapacityUsed")),
            **_orders(orders.get("onfootmicroresources"))}


def _shipyard(d: Dict[str, Any]) -> Dict[str, Any]:
    sh = d.get("ships") if isinstance(d.get("ships"), dict) else {}
    ships = [{"name": _name(x), "stock": _int(x.get("stock")), "price": _int(x.get("basevalue") or x.get("cost"))}
             for x in _items(sh.get("shipyard_list"))]
    return {"status": _service(d, "shipyard"), "packs": _int((d.get("capacity") or {}).get("shipPacks")),
            "ships": sorted(ships, key=lambda r: r["name"])}


def _outfitting(d: Dict[str, Any]) -> Dict[str, Any]:
    mods = _items(d.get("modules"))
    rows = []
    for x in mods:
        free = bool(x.get("bundle")) or _int(x.get("stock")) < 0
        rows.append({"name": module_name(x.get("name")), "category": x.get("category"),
                     "price": _int(x.get("cost")), "stock": None if free else _int(x.get("stock")),
                     "bundle": free})
    stocked = [r for r in rows if r["stock"] is not None]
    return {"status": _service(d, "outfitting"), "packs": _int((d.get("capacity") or {}).get("modulePacks")),
            "kinds": len(rows), "units": sum(r["stock"] for r in stocked),
            "value": sum(r["stock"] * r["price"] for r in stocked),
            "modules": sorted(stocked, key=lambda r: (-r["stock"] * r["price"], r["name"])),
            "bundled": len(rows) - len(stocked)}


def history(events: Iterable[Dict[str, Any]], own_id: Any) -> List[Dict[str, Any]]:
    """CarrierTradeOrder of the own carrier, newest first: set to buy, set
    to sell or cancelled, with amount and price."""
    out = []
    for e in events:
        if e.get("event") != "CarrierTradeOrder" or (own_id is not None and e.get("CarrierID") != own_id):
            continue
        kind = "cancel" if e.get("CancelTrade") else "buy" if e.get("PurchaseOrder") else \
            "sell" if e.get("SaleOrder") else "other"
        out.append({"ts": parse_ts(e.get("timestamp")), "kind": kind,
                    "name": e.get("Commodity_Localised") or _name({"name": e.get("Commodity")}),
                    "qty": _int(e.get("PurchaseOrder") or e.get("SaleOrder")) or None,
                    "price": _int(e.get("Price")) or None, "black": bool(e.get("BlackMarket"))})
    return list(reversed(out[-HISTORY:]))


def build_trade(capi_path: Optional[str], events: Iterable[Dict[str, Any]], own_id: Any,
                now: Optional[float] = None) -> Dict[str, Any]:
    """CARRIER TRADE: Frontier's data where there is a file, the journal's
    order history always."""
    now = time.time() if now is None else now
    out: Dict[str, Any] = {"history": history(events, own_id), "capi": None}
    got = capi.read(capi_path)
    if got is None:
        return out
    saved, d = got
    orders = d.get("orders") if isinstance(d.get("orders"), dict) else {}
    cap = d.get("capacity") if isinstance(d.get("capacity"), dict) else {}
    stock = _market_stock(d)
    com = d.get("commodities") if isinstance(d.get("commodities"), dict) else {}
    names = {str(x.get("name") or "").lower(): _name(x) for x in _items(com.get("commodities"))}
    market = dict(_orders(orders.get("commodities"), names), finances=_finances(d.get("marketFinances")),
                  black=_finances(d.get("blackmarketFinances")), stock=stock,
                  status=_service(d, "commodities"),
                  for_sale_t=_int(cap.get("cargoForSale")), not_for_sale_t=_int(cap.get("cargoNotForSale")))
    out["capi"] = {"saved": saved, "age_s": round(now - saved) if saved else None, "market": market,
                   "bar": _bar(d), "shipyard": _shipyard(d), "outfitting": _outfitting(d)}
    bar = out["capi"]["bar"]
    out["demand"] = {"units": market["open_units"] + bar["open_units"], "cr": market["open_cr"] + bar["open_cr"],
                     "rows": [dict(r, where="market") for r in market["purchases"] if r["outstanding"]]
                     + [dict(r, where="bar") for r in bar["purchases"] if r["outstanding"]]}
    return out
