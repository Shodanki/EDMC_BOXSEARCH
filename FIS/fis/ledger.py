# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0: GAIN / LOSS - what the active commander earned and spent, from the
journal alone, "like in real life" (user, 17.11.).

Three kinds of money, kept apart:
- income: data sold (exobiology, exploration, codex), goods (mining sold at
  AvgPricePaid 0, trade as its profit over the price paid), rewards;
- running costs: repairs, fuel, ammunition and vehicles, limpets, a ship
  lost (the rebuy), crew, fines;
- investment: ships, modules, transfers, on-foot gear, a carrier - buying
  counts here, selling gives it back (a negative investment).

Each sum is booked to the ship flown at the time (LoadGame, Loadout,
ShipyardSwap, ShipyardNew; module events name their ShipID). What belongs to
no ship (community goals, fines, crew, stored modules, on-foot gear) is the
commander's.

Missions and anything else the journal does not book (no MissionCompleted
in many journals) come from the credit balance: between two known balances
(LoadGame Credits, CarrierBankTransfer PlayerBalance, Status.json at the
end) the change the booked events do not explain is shown apart as "from
the balance" - more than booked: income, less: costs. Journals missing for
a stretch show up there too; it is an honest rest, not a guess.

The own carrier: transfers to and from it (CarrierBankTransfer) move money,
they are neither gain nor loss; its upkeep needs the carrier's balance
(CarrierStats) and is left for later.

Plain Python, nothing online.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

INCOME, COSTS, INVEST = "income", "costs", "invest"
WEEKS = 12                       # the weekly bars: the last twelve weeks with entries
CMDR = None                      # "no ship": the commander's own


class _Ledger:
    """The replay: books every money event to a ship or the commander."""

    def __init__(self, since: Optional[float]) -> None:
        self.since = since
        self.ship: Optional[int] = None
        self.ships: Dict[int, Dict[str, Any]] = {}
        self.cmdr = _account()
        self.totals = _account()
        self.deaths: List[Dict[str, Any]] = []
        self.weeks: Dict[str, Dict[str, float]] = {}
        self.pending_buy: Optional[Tuple[float, int]] = None   # ShipyardBuy until ShipyardNew names the ship
        self.balance: Optional[int] = None
        self.flow = 0                                        # booked cash since the last known balance
        self.rest = {"plus": 0, "minus": 0, "gaps": 0}
        self.carrier = {"deposit": 0, "withdraw": 0}

    # ---------------------------------------------------------------- booking
    def book(self, ts: Optional[float], kind: str, key: str, cr: float, ship: Any = "current") -> None:
        """One amount: cash flow (always, for the balance check) and, inside
        the period, the sums of the ship or the commander."""
        cr = float(cr or 0)
        self.flow += cr if kind == INCOME else -cr
        if ts is None or (self.since is not None and ts < self.since) or not cr:
            return
        sid = self.ship if ship == "current" else ship
        acc = self.cmdr if sid is None else self._ship(sid)["acc"]
        for a in (acc, self.totals):
            row = a[kind].setdefault(key, [0.0, 0])
            row[0] += cr
            row[1] += 1
        if kind != INVEST:
            y, w, _d = datetime.fromtimestamp(ts, timezone.utc).isocalendar()
            wk = self.weeks.setdefault("%d-W%02d" % (y, w), {INCOME: 0.0, COSTS: 0.0})
            wk[kind] += cr

    def cash(self, cr: float) -> None:
        """Money that moves without gain or loss (goods bought, carrier transfers)."""
        self.flow += float(cr or 0)

    def known_balance(self, ts: Optional[float], bal: Any) -> None:
        """A balance the game states: what the booked events do not explain
        since the last one is the rest "from the balance"."""
        try:
            bal = int(bal)
        except (TypeError, ValueError):
            return
        if self.balance is not None:
            rest = bal - self.balance - self.flow
            if abs(rest) >= 1:
                self.flow = 0.0
                if rest > 0:
                    self.book(ts, INCOME, "from_balance", rest, CMDR)
                    self._rest(ts, "plus", rest)
                else:
                    self.book(ts, COSTS, "from_balance", -rest, CMDR)
                    self._rest(ts, "minus", -rest)
        self.balance, self.flow = bal, 0.0

    def _rest(self, ts: Optional[float], sign: str, cr: float) -> None:
        if ts is not None and (self.since is None or ts >= self.since):
            self.rest[sign] += cr
            self.rest["gaps"] += 1

    def _ship(self, sid: int) -> Dict[str, Any]:
        return self.ships.setdefault(sid, {"type": None, "name": None, "acc": _account()})

    def fly(self, sid: Any, typ: Any = None, name: Any = None) -> None:
        """The ship flown from now on."""
        if sid is None:
            return
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            return
        self.ship = sid
        s = self._ship(sid)
        if typ:
            s["type"] = str(typ)
        if name:
            s["name"] = str(name)


def _account() -> Dict[str, Dict[str, List[float]]]:
    return {INCOME: {}, COSTS: {}, INVEST: {}}


def _num(e: Dict[str, Any], *keys: str) -> float:
    for k in keys:
        v = e.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return 0.0


# ------------------------------------------------------------------ handlers
# each: (ledger, event, timestamp)

def _load(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    L.fly(e.get("ShipID"), e.get("Ship"), e.get("ShipName"))
    L.known_balance(ts, e.get("Credits"))


def _loadout(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    L.fly(e.get("ShipID"), e.get("Ship"), e.get("ShipName"))


def _swap(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    L.fly(e.get("ShipID"), e.get("ShipType"))


def _ship_buy(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    # the old ship sold in the same deal gives its price back
    L.pending_buy = (_num(e, "ShipPrice") - _num(e, "SellPrice"), 0)


def _ship_new(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    L.fly(e.get("NewShipID"), e.get("ShipType"))
    if L.pending_buy is not None:
        L.book(ts, INVEST, "ships", L.pending_buy[0])
        L.pending_buy = None


def _ship_sell(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    sid = e.get("SellShipID", e.get("SellShipId"))
    L.book(ts, INVEST, "ships", -_num(e, "ShipPrice"), int(sid) if isinstance(sid, int) else CMDR)


def _module_buy(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    sid = e.get("ShipID") if isinstance(e.get("ShipID"), int) else "current"
    L.book(ts, INVEST, "modules", _num(e, "BuyPrice") - _num(e, "SellPrice"), sid)


def _module_sell(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    sid = e.get("ShipID") if e.get("event") == "ModuleSell" and isinstance(e.get("ShipID"), int) else CMDR
    L.book(ts, INVEST, "modules", -_num(e, "SellPrice"), sid)


def _transfer(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    sid = e.get("ShipID") if isinstance(e.get("ShipID"), int) else "current"
    L.book(ts, INVEST, "transfers", _num(e, "TransferPrice", "TransferCost"), sid)


def _resurrect(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    cost = _num(e, "Cost")
    L.book(ts, COSTS, "ship_loss", cost)
    if ts is not None and (L.since is None or ts >= L.since):
        s = L.ships.get(L.ship) or {}
        L.deaths.append({"ts": ts, "ship": s.get("name"), "type": s.get("type"),
                         "cost": cost, "option": e.get("Option")})


def _market_sell(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    sale, paid = _num(e, "TotalSale"), _num(e, "AvgPricePaid") * _num(e, "Count")
    if paid:
        # trade: the profit; what was paid went out with MarketBuy
        L.cash(paid)
        L.book(ts, INCOME, "trade", sale - paid)
    else:
        L.book(ts, INCOME, "mining", sale)


def _bank(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    dep, wd = _num(e, "Deposit"), _num(e, "Withdraw")
    L.cash(wd - dep)
    if ts is not None and (L.since is None or ts >= L.since):
        L.carrier["deposit"] += dep
        L.carrier["withdraw"] += wd
    L.known_balance(ts, e.get("PlayerBalance"))


def _voucher(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    typ = str(e.get("Type") or "").lower()
    key = {"codex": "codex", "bounty": "combat", "combatbond": "combat", "trade": "trade",
           "settlement": "other", "scannable": "other"}.get(typ, "other")
    L.book(ts, INCOME, key, _num(e, "Amount"))


def _bio(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    L.book(ts, INCOME, "exobiology", sum(_num(b, "Value") + _num(b, "Bonus") for b in e.get("BioData") or []))


def _simple(kind: str, key: str, fields: Tuple[str, ...], ship: Any = "current"
            ) -> Callable[[_Ledger, Dict[str, Any], Optional[float]], None]:
    """A handler that books one amount field."""
    def h(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
        L.book(ts, kind, key, _num(e, *fields), ship)
    return h


def _mission(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    L.book(ts, INCOME, "missions", _num(e, "Reward"))
    L.book(ts, COSTS, "other", _num(e, "Donated"))


def _buy_goods(L: _Ledger, e: Dict[str, Any], ts: Optional[float]) -> None:
    L.cash(-_num(e, "TotalCost"))


HANDLERS: Dict[str, Callable[[_Ledger, Dict[str, Any], Optional[float]], None]] = {
    "LoadGame": _load, "Loadout": _loadout, "ShipyardSwap": _swap,
    "ShipyardBuy": _ship_buy, "ShipyardNew": _ship_new,
    "ShipyardSell": _ship_sell, "SellShipOnRebuy": _ship_sell,
    "ModuleBuy": _module_buy, "ModuleBuyAndStore": _simple(INVEST, "modules", ("BuyPrice",), CMDR),
    "ModuleSell": _module_sell, "ModuleSellRemote": _module_sell,
    "ShipyardTransfer": _transfer, "FetchRemoteModule": _transfer,
    "BuySuit": _simple(INVEST, "onfoot", ("Price",), CMDR),
    "BuyWeapon": _simple(INVEST, "onfoot", ("Price",), CMDR),
    "UpgradeSuit": _simple(INVEST, "onfoot", ("Cost",), CMDR),
    "UpgradeWeapon": _simple(INVEST, "onfoot", ("Cost",), CMDR),
    "BuyMicroResources": _simple(INVEST, "onfoot", ("TotalCost", "Price"), CMDR),
    "SellSuit": _simple(INCOME, "sales", ("Price",), CMDR),
    "SellWeapon": _simple(INCOME, "sales", ("Price",), CMDR),
    "SellMicroResources": _simple(INCOME, "sales", ("Price",), CMDR),
    "CarrierBuy": _simple(INVEST, "carrier", ("Price",), CMDR),
    "Repair": _simple(COSTS, "repairs", ("Cost",)), "RepairAll": _simple(COSTS, "repairs", ("Cost",)),
    "RefuelAll": _simple(COSTS, "fuel", ("Cost",)), "RefuelPartial": _simple(COSTS, "fuel", ("Cost",)),
    "BuyAmmo": _simple(COSTS, "ammo", ("Cost",)), "RestockVehicle": _simple(COSTS, "ammo", ("Cost",)),
    "BuyDrones": _simple(COSTS, "limpets", ("TotalCost",)),
    "SellDrones": _simple(INCOME, "sales", ("TotalSale",)),
    "Resurrect": _resurrect,
    "PayFines": _simple(COSTS, "fines", ("Amount",), CMDR),
    "PayBounties": _simple(COSTS, "fines", ("Amount",), CMDR),
    "PayLegacyFines": _simple(COSTS, "fines", ("Amount",), CMDR),
    "NpcCrewPaidWage": _simple(COSTS, "crew", ("Amount",), CMDR),
    "CrewHire": _simple(COSTS, "crew", ("Cost",), CMDR),
    "BuyExplorationData": _simple(COSTS, "other", ("Cost",)),
    "BuyTradeData": _simple(COSTS, "other", ("Cost",)),
    "MultiSellExplorationData": _simple(INCOME, "exploration", ("TotalEarnings",)),
    "SellExplorationData": _simple(INCOME, "exploration", ("TotalEarnings",)),
    "SellOrganicData": _bio,
    "RedeemVoucher": _voucher,
    "MarketSell": _market_sell, "MarketBuy": _buy_goods,
    "MissionCompleted": _mission,
    "SearchAndRescue": _simple(INCOME, "rescue", ("Reward",)),
    "CommunityGoalReward": _simple(INCOME, "community_goals", ("Reward",), CMDR),
    "PowerplaySalary": _simple(INCOME, "other", ("Amount",), CMDR),
    "CarrierBankTransfer": _bank,
}
# the archive keeps these (fleet.EVENTS)
EVENTS = tuple(HANDLERS)


def build_ledger(events: Iterable[Dict[str, Any]], days: Optional[float] = None,
                 now: Optional[float] = None, balance_now: Any = None) -> Dict[str, Any]:
    """GAIN / LOSS of the commander whose events these are, over the last
    ``days`` (None: all). ``balance_now`` (Status.json) closes the last
    stretch of the balance check."""
    now = time.time() if now is None else now
    since = now - days * 86400 if days else None
    L = _Ledger(since)
    first = last = None
    for e in events:
        h = HANDLERS.get(e.get("event"))
        if h is None:
            continue
        ts = parse_ts(e.get("timestamp"))
        first = ts if first is None else first
        last = ts if ts is not None else last
        h(L, e, ts)
    if balance_now is not None:
        L.known_balance(now, balance_now)
    return _result(L, since, first, last)


def _rows(acc: Dict[str, List[float]]) -> List[Dict[str, Any]]:
    return sorted(({"key": k, "cr": round(v[0]), "n": v[1]} for k, v in acc.items() if round(v[0])),
                  key=lambda r: -abs(r["cr"]))


def _sum(acc: Dict[str, List[float]]) -> int:
    return round(sum(v[0] for v in acc.values()))


def _summary(acc: Dict[str, Dict[str, List[float]]]) -> Dict[str, Any]:
    inc, cost, inv = _sum(acc[INCOME]), _sum(acc[COSTS]), _sum(acc[INVEST])
    return {"income": inc, "costs": cost, "invest": inv, "net": inc - cost,
            "income_rows": _rows(acc[INCOME]), "cost_rows": _rows(acc[COSTS]), "invest_rows": _rows(acc[INVEST])}


def _result(L: _Ledger, since: Optional[float], first: Optional[float], last: Optional[float]) -> Dict[str, Any]:
    ships = []
    for sid, s in L.ships.items():
        sm = _summary(s["acc"])
        if sm["income"] or sm["costs"] or sm["invest"]:
            ships.append(dict(sm, id=sid, type=s["type"], name=s["name"], current=sid == L.ship))
    ships.sort(key=lambda s: -s["net"])
    weeks = [{"week": k, "income": round(v[INCOME]), "costs": round(v[COSTS])}
             for k, v in sorted(L.weeks.items())][-WEEKS:]
    tot = _summary(L.totals)
    return {"since": since, "first": first, "last": last, "empty": not (tot["income"] or tot["costs"] or tot["invest"]),
            "totals": tot, "cmdr": _summary(L.cmdr), "ships": ships, "deaths": L.deaths, "weeks": weeks,
            "rest": {k: round(v) for k, v in L.rest.items()}, "carrier": {k: round(v) for k, v in L.carrier.items()}}
