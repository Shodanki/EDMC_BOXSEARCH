# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0 CT2: the own carrier's money - what it earned and what it cost, as far
as the data shows it. For STATISTICS and GAIN / LOSS.

Frontier's figures (capi_fleetcarrier.json, read only) where there is a file:
- upkeep per week (core cost + the services' crew), what this week has cost
  so far, jump costs, taxes;
- per service its crew's weekly salary and the wages billed this week;
- the market's, the secure warehouse's and the bar's all-time profit.

The journal, always: your transfers to and from the carrier
(CarrierBankTransfer), services switched (CarrierCrewServices), the jumps
(CarrierJump), the balance readings (CarrierStats) and from them the upkeep
estimate over the period (PL2, fleet.upkeep_between). Frontier's numbers are
exact; the estimate carries "~". Nothing is guessed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional

from . import capi
from .fleet import upkeep_between
from .live import parse_ts


def _int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _wages(svc: Dict[str, Any]) -> Dict[str, int]:
    """This week's wages: billed so far ("current") and expected to the end."""
    out = {"current": 0, "expected": 0}
    for inv in svc.get("invoicesWeekToDate") or []:
        if isinstance(inv, dict) and inv.get("type") in out:
            out[inv["type"]] += _int(inv.get("wages"))
    return out


def crew(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per service: its crew's weekly salary, on or off, and this week's wages."""
    rows = []
    for role, svc in (d.get("servicesCrew") or {}).items():
        if not isinstance(svc, dict):
            continue
        m = svc.get("crewMember") if isinstance(svc.get("crewMember"), dict) else {}
        rows.append({"role": role, "salary": _int(m.get("salary")), "enabled": m.get("enabled") == "YES",
                     "hired_for": _int(m.get("hiringPrice")), **_wages(svc)})
    return sorted(rows, key=lambda r: -r["salary"])


def frontier(capi_path: Optional[str], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Frontier's own money figures of the carrier, or None without the file."""
    got = capi.read(capi_path)
    if got is None:
        return None
    saved, d = got
    now = time.time() if now is None else now
    fin = d.get("finance") if isinstance(d.get("finance"), dict) else {}
    bt = fin.get("bartender") if isinstance(fin.get("bartender"), dict) else {}
    mf = d.get("marketFinances") if isinstance(d.get("marketFinances"), dict) else {}
    bm = d.get("blackmarketFinances") if isinstance(d.get("blackmarketFinances"), dict) else {}
    return {"saved": saved, "age_s": round(now - saved) if saved else None,
            "per_week": _int(fin.get("maintenance")), "core": _int(fin.get("coreCost")),
            "services": _int(fin.get("servicesCost")), "week_to_date": _int(fin.get("maintenanceToDate")),
            "services_to_date": _int(fin.get("servicesCostToDate")),
            "jumps_cost": _int(fin.get("jumpsCost")), "jumps": _int(fin.get("numJumps")),
            "taxation": _int(fin.get("taxation")),
            "tax_rates": {k: _int(v) for k, v in (fin.get("service_taxation") or {}).items()},
            "balance": _int(fin.get("bankBalance")), "reserved": _int(fin.get("bankReservedBalance")),
            "debt_threshold": _int(fin.get("debtThreshold")),
            "market_profit": _int(mf.get("allTimeProfit")), "black_profit": _int(bm.get("allTimeProfit")),
            "bar_profit": _int(bt.get("allTimeProfit")),
            "bar_history": [_int(v) for v in bt.get("profitHistory") or []],
            "orders_reserved": _int(mf.get("balanceAllocForPurchaseOrders"))
            + _int(bm.get("balanceAllocForPurchaseOrders")) + _int(bt.get("balanceAllocForPurchaseOrders")),
            "cargo_value": _int(mf.get("cargoTotalValue")),
            "crew": crew(d)}


_OWN = {"CarrierCrewServices": 0, "CarrierJumpRequest": 1, "CarrierJumpCancelled": -1}


def _in(ts: Optional[float], since: Optional[float]) -> bool:
    return ts is not None and (since is None or ts >= since)


def journal(carrier: Optional[Dict[str, Any]], events: Iterable[Dict[str, Any]], own_id: Any,
            since: Optional[float]) -> Dict[str, Any]:
    """What the journal says about the carrier's money over the period."""
    tr = [x for x in (carrier or {}).get("transfers") or [] if _in(x.get("ts"), since)]
    bals = [(t, b) for t, b in (carrier or {}).get("balances") or [] if _in(t, since)]
    services, jumps = [], 0
    for e in events:
        ev = e.get("event")
        # jumps ordered less those cancelled - CarrierJump is only written aboard
        if ev not in _OWN or (own_id is not None and e.get("CarrierID") != own_id):
            continue
        ts = parse_ts(e.get("timestamp"))
        if not _in(ts, since):
            continue
        if ev == "CarrierCrewServices":
            services.append({"ts": ts, "role": e.get("CrewRole"), "op": e.get("Operation")})
        else:
            jumps += _OWN[ev]
    up = upkeep_between((carrier or {}).get("balances") or [], (carrier or {}).get("transfers") or [], since)
    return {"deposit": round(sum(x["deposit"] for x in tr)), "withdraw": round(sum(x["withdraw"] for x in tr)),
            "transfers": len(tr), "readings": len(bals),
            "balance_first": bals[0][1] if bals else None, "balance_last": bals[-1][1] if bals else None,
            "upkeep": up, "services": list(reversed(services[-10:])), "jumps": jumps}


def build(capi_path: Optional[str], carrier: Optional[Dict[str, Any]], events: Iterable[Dict[str, Any]],
          since: Optional[float] = None, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """CT2: the carrier's money - Frontier's figures and the journal's -
    or None for a commander without a carrier."""
    if not carrier:
        return None
    own_id = ((carrier.get("stats") or {}).get("CarrierID"))
    return {"frontier": frontier(capi_path, now), "journal": journal(carrier, events, own_id, since)}
