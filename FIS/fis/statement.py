# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0 GV1: GAIN / LOSS as a business would show it - the commander as a free
trader and mercenary company, its books closed like an annual statement
(fictional, loosely after the German HGB: income statement after § 275,
balance sheet after § 266). Nerdy on purpose, honest throughout:

- income statement per ISO week, month and year: revenue per segment,
  other operating income, material, personnel (NPC crew, carrier crew and
  services), write-downs (ships lost), other operating costs, operating
  result - with the period before beside it;
- balance sheet now: ships at the game's own value, the carrier, its cargo,
  unsold data, cash and carrier bank; provisions; equity as the rest;
- segments: result per segment, the time spent on it, credits per hour;
  GV2: trade with its cost of goods, and every running cost of a ship given
  to the segment the commander mainly ran with that ship in that session
  (~, by activity time; no clear segment: unallocated) - the statement's
  totals stay, the allocation only splits them;
- outlook: how long the carrier is financed, the weekly burn against the
  income run rate, when money must come in, what a decommission returns.

Every amount comes from the journal (fis/ledger.py) or Frontier's carrier
file (fis/carriermoney.py). The carrier's upkeep per period is the PL2
estimate from its balance and carries "~", as do game values and times.
What no source states is "unknown" - nothing is guessed.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .fleet import upkeep_between
from .live import parse_ts

# segment: revenue keys of the ledger, cost keys that belong to it
SEGMENTS: List[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = [
    ("exploration", ("exploration", "codex"), ()),
    ("exobiology", ("exobiology",), ()),
    ("mining", ("mining",), ()),
    ("trade", ("trade",), ("cogs",)),
    ("combat", ("combat",), ()),
    ("missions", ("missions", "rescue", "community_goals"), ()),
    ("carrier", (), ("tritium",)),
]
# the lines of the income statement after the revenue
OTHER_INCOME = ("sales", "other", "from_balance")
MATERIAL = ("cogs", "fuel", "ammo", "limpets", "tritium")   # GV2: cost of goods sold first
PERSONNEL = ("crew",)
WRITE_DOWNS = ("ship_loss",)
KEEP = {"week": 12, "month": 12, "year": 10}
RUN_WEEKS = 4                      # the run rate: the last complete weeks
GAP_S = 15 * 60                    # activity time: longer pauses are not counted
MAIN_SHARE = 0.5                   # GV2: a session's ship runs "mainly" in a segment with more than half its time
UNALLOCATED = "unallocated"

# which segment an event puts you in (activity time, ~)
ACTIVITY = {
    "FSDJump": "exploration", "FSSDiscoveryScan": "exploration", "Scan": "exploration",
    "SAAScanComplete": "exploration", "FSSBodySignals": "exploration", "NavBeaconScan": "exploration",
    "MultiSellExplorationData": "exploration", "SellExplorationData": "exploration",
    "ScanOrganic": "exobiology", "SellOrganicData": "exobiology",
    "ProspectedAsteroid": "mining", "MiningRefined": "mining", "AsteroidCracked": "mining", "LaunchDrone": "mining",
    "MarketBuy": "trade",
    "MissionAccepted": "missions", "MissionCompleted": "missions",
    "CarrierJumpRequest": "carrier", "CarrierDepositFuel": "carrier", "CarrierBankTransfer": "carrier",
    "CarrierStats": "carrier", "CarrierTradeOrder": "carrier",
}


# ------------------------------------------------------------------ periods
def bounds(gran: str, label: str) -> Tuple[float, float]:
    """Start and end (UTC timestamps) of an ISO week "2026-W46", a month
    "2026-11" or a year "2026"."""
    if gran == "week":
        y, w = label.split("-W")
        a = datetime.fromisocalendar(int(y), int(w), 1).replace(tzinfo=timezone.utc)
        return a.timestamp(), (a + timedelta(days=7)).timestamp()
    if gran == "month":
        y, m = (int(x) for x in label.split("-"))
        a = datetime(y, m, 1, tzinfo=timezone.utc)
        b = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        return a.timestamp(), b.timestamp()
    y = int(label)
    return datetime(y, 1, 1, tzinfo=timezone.utc).timestamp(), datetime(y + 1, 1, 1, tzinfo=timezone.utc).timestamp()


def _label(gran: str, ts: float) -> str:
    d = datetime.fromtimestamp(ts, timezone.utc)
    if gran == "week":
        y, w, _d = d.isocalendar()
        return "%d-W%02d" % (y, w)
    return "%d-%02d" % (d.year, d.month) if gran == "month" else "%d" % d.year


def _take(acc: Dict[str, int], keys: Iterable[str], used: set) -> List[Dict[str, Any]]:
    rows = []
    for k in keys:
        if acc.get(k):
            rows.append({"key": k, "cr": acc[k]})
            used.add(k)
    return rows


def _line(key: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"key": key, "cr": sum(r["cr"] for r in rows), "rows": rows, "est": any(r.get("est") for r in rows)}


def _carrier_rows(up: Optional[Dict[str, Any]], share: Optional[float]) -> Tuple[list, list]:
    """The carrier's upkeep of the period (~): its crew and services under
    personnel, the core cost under other costs - split as Frontier bills it."""
    if not up or not up.get("cost"):
        return [], []
    cost = up["cost"]
    if share is None:
        return [], [{"key": "carrier_upkeep", "cr": cost, "est": True}]
    svc = round(cost * share)
    return ([{"key": "carrier_services", "cr": svc, "est": True}],
            [{"key": "carrier_core", "cr": cost - svc, "est": True}])


def statement(entry: Dict[str, Any], upkeep: Optional[Dict[str, Any]] = None,
              share: Optional[float] = None) -> Dict[str, Any]:
    """One period's income statement from the ledger's period entry
    ({label, income, costs, invest}) and the carrier's upkeep then."""
    inc, cost = entry.get("income") or {}, entry.get("costs") or {}
    used_i: set = set()
    used_c: set = set()
    revenue = [dict(_line(seg, _take(inc, keys, used_i)), seg=seg) for seg, keys, _c in SEGMENTS if keys]
    revenue = [r for r in revenue if r["cr"]]
    svc, core = _carrier_rows(upkeep, share)
    other_inc = _take(inc, OTHER_INCOME, used_i) + [{"key": k, "cr": v} for k, v in inc.items() if k not in used_i]
    lines = {"revenue": _line("revenue", [{"key": r["seg"], "cr": r["cr"]} for r in revenue]),
             "other_income": _line("other_income", other_inc),
             "material": _line("material", _take(cost, MATERIAL, used_c)),
             "personnel": _line("personnel", _take(cost, PERSONNEL, used_c) + svc),
             "write_downs": _line("write_downs", _take(cost, WRITE_DOWNS, used_c))}
    rest = [{"key": k, "cr": v} for k, v in cost.items() if k not in used_c]
    lines["other_costs"] = _line("other_costs", rest + core)
    result = (lines["revenue"]["cr"] + lines["other_income"]["cr"] - lines["material"]["cr"]
              - lines["personnel"]["cr"] - lines["write_downs"]["cr"] - lines["other_costs"]["cr"])
    invest = entry.get("invest") or {}
    return {"label": entry.get("label"), "lines": lines, "result": result, "est": bool(svc or core),
            "invest": sum(invest.values()), "invest_rows": [{"key": k, "cr": v} for k, v in invest.items()],
            "upkeep_days": (upkeep or {}).get("days")}


def _merge(entries: Iterable[Dict[str, Any]], label: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"label": label, "income": {}, "costs": {}, "invest": {}}
    for e in entries:
        for kind in ("income", "costs", "invest"):
            for k, v in (e.get(kind) or {}).items():
                out[kind][k] = out[kind].get(k, 0) + v
    return out


def statements(periods: Dict[str, List[Dict[str, Any]]], carrier: Optional[Dict[str, Any]],
               share: Optional[float], now: float) -> Dict[str, Any]:
    """The last periods of each kind (newest first), each with the one
    before for comparison, and all time."""
    bals = (carrier or {}).get("balances") or []
    trs = (carrier or {}).get("transfers") or []
    out: Dict[str, Any] = {}
    for gran, keep in KEEP.items():
        have = {e["label"]: e for e in periods.get(gran) or []}
        cur = _label(gran, now)
        labels = sorted(set(have) | {cur})[-keep:]
        rows = []
        for lab in reversed(labels):
            a, b = bounds(gran, lab)
            up = upkeep_between(bals, trs, a, min_days=2.0 if gran == "week" else 3.0, until=b) if bals else None
            st = statement(have.get(lab) or {"label": lab}, up, share)
            st.update(start=a, end=b, running=a <= now < b)
            rows.append(st)
        out[gran] = rows
    every = _merge(periods.get("year") or [], "all")
    up = upkeep_between(bals, trs, None) if bals else None
    out["all"] = statement(every, up, share)
    return out


# ------------------------------------------------------------------ activity time
# the events that name the ship flown from then on (as ledger.fly)
SHIP_ID = {"LoadGame": "ShipID", "Loadout": "ShipID", "ShipyardSwap": "ShipID", "ShipyardNew": "NewShipID"}


def _ship_id(v: Any, cur: Optional[int]) -> Optional[int]:
    try:
        return int(v) if v is not None else cur
    except (TypeError, ValueError):
        return cur


def _spans(events: Iterable[Dict[str, Any]], since: Optional[float], gap: float
           ) -> Iterable[Tuple[str, float, Optional[float], Optional[int]]]:
    """(segment, seconds, session, ship) for each counted stretch: the time
    after an event goes to the segment that event puts you in, until the
    next one. Session: the LoadGame's time; ship: as the ledger flies it."""
    seg: Optional[str] = None
    last: Optional[float] = None
    session: Optional[float] = None
    ship: Optional[int] = None
    for e in events:
        ts = parse_ts(e.get("timestamp"))
        if ts is None:
            continue
        ev = e.get("event")
        if last is not None and seg and 0 < ts - last <= gap and (since is None or ts > since):
            yield seg, ts - last, session, ship
        if last is not None and ts - last > gap:
            seg = None                    # after a pause: in no segment until the next such event
        if ev == "LoadGame":
            seg, session = None, ts
        if ev in SHIP_ID:
            ship = _ship_id(e.get(SHIP_ID[ev]), ship)
        if ev == "MarketSell":
            seg = "trade" if e.get("AvgPricePaid") else "mining"
        elif ev in ACTIVITY:
            seg = ACTIVITY[ev]
        last = ts


def activity_time(events: Iterable[Dict[str, Any]], since: Optional[float] = None,
                  gap: float = GAP_S) -> Dict[str, float]:
    """Seconds per segment (~): the time after an event goes to the segment
    that event puts you in, until the next one; pauses longer than `gap`
    and the time after a login or a pause until the first such event go to
    no segment.
    A sale at AvgPricePaid 0 is mining, with a price paid trade."""
    out: Dict[str, float] = {}
    for seg, sec, _se, _sh in _spans(events, since, gap):
        out[seg] = out.get(seg, 0.0) + sec
    return out


def main_segments(events: Iterable[Dict[str, Any]], gap: float = GAP_S) -> Dict[Tuple[Optional[float], int], str]:
    """GV2: per (session, ship) the segment the commander mainly ran with
    that ship - more than MAIN_SHARE of its activity time; none: no entry."""
    per: Dict[Tuple[Optional[float], int], Dict[str, float]] = {}
    for seg, sec, session, ship in _spans(events, None, gap):
        if ship is not None:
            acc = per.setdefault((session, ship), {})
            acc[seg] = acc.get(seg, 0.0) + sec
    out = {}
    for key, acc in per.items():
        seg, sec = max(acc.items(), key=lambda kv: kv[1])
        if sec > MAIN_SHARE * sum(acc.values()):
            out[key] = seg
    return out


def allocate(ship_costs: Iterable[Dict[str, Any]], mains: Dict[Tuple[Optional[float], int], str],
             weeks: Optional[set] = None) -> Dict[str, Dict[str, int]]:
    """GV2: the ships' running costs (ledger ship_costs) per segment - each
    session's ship to its main segment, the rest UNALLOCATED. `weeks`: only
    these ISO weeks (a period); None: all."""
    out: Dict[str, Dict[str, int]] = {}
    for r in ship_costs:
        if weeks is not None and r["week"] not in weeks:
            continue
        acc = out.setdefault(mains.get((r["session"], r["ship"]), UNALLOCATED), {})
        for k, v in r["costs"].items():
            acc[k] = acc.get(k, 0) + v
    return out


def segments(entry: Dict[str, Any], upkeep: Optional[Dict[str, Any]],
             seconds: Dict[str, float], alloc: Optional[Dict[str, Dict[str, int]]] = None) -> List[Dict[str, Any]]:
    """Result per segment: its revenue, the cost of goods (trade), its own
    costs (the carrier: tritium and ~upkeep), the ships' running costs
    given to it (GV2, ~: `alloc` from allocate()), the time spent, credits
    per hour after all of them. What no segment got is the row UNALLOCATED,
    last."""
    inc, cost = entry.get("income") or {}, entry.get("costs") or {}
    alloc = alloc or {}
    rows = []
    for seg, rkeys, ckeys in SEGMENTS:
        rev = sum(inc.get(k, 0) for k in rkeys)
        cogs = cost.get("cogs", 0) if "cogs" in ckeys else 0
        c = sum(cost.get(k, 0) for k in ckeys if k != "cogs")
        est = False
        if seg == "carrier" and upkeep and upkeep.get("cost"):
            c += upkeep["cost"]
            est = True
        ship = sum((alloc.get(seg) or {}).values())
        h = seconds.get(seg, 0.0) / 3600.0
        if not (rev or c or ship or h):
            continue
        net = rev - cogs - c - ship
        rows.append({"seg": seg, "revenue": rev, "cogs": cogs, "costs": c, "ship_costs": ship,
                     "ship_rows": alloc.get(seg) or {}, "net": net, "hours": round(h, 1),
                     "per_hour": round(net / h) if h >= 0.5 else None, "est": est or bool(ship)})
    rows.sort(key=lambda r: -r["net"])
    rest = alloc.get(UNALLOCATED) or {}
    if rest:
        ship = sum(rest.values())
        rows.append({"seg": UNALLOCATED, "revenue": 0, "cogs": 0, "costs": 0, "ship_costs": ship, "ship_rows": rest,
                     "net": -ship, "hours": None, "per_hour": None, "est": False})
    return rows


# ------------------------------------------------------------------ balance sheet
def _latest_stats(carrier: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return ((carrier or {}).get("stats") or {}).get("Finance") or {}


def balance_sheet(ships: List[Dict[str, Any]], carrier: Optional[Dict[str, Any]], frontier: Optional[Dict[str, Any]],
                  cash: Optional[int], open_: Optional[Dict[str, Any]], carrier_price: Optional[int]) -> Dict[str, Any]:
    """Assets and provisions now; equity is the rest. Unknown items are
    named and left out of the sums."""
    fin = _latest_stats(carrier)
    valued = [s for s in ships if s.get("value")]
    unsold = None
    if open_:
        unsold = (open_.get("bio") or 0) + ((open_.get("explo") or {}).get("mid") or 0) or None
    fixed = [{"key": "ships", "cr": sum(int(s["value"]) for s in valued) or None, "est": True, "n": len(valued),
              "missing": len(ships) - len(valued)}]
    if carrier:
        fixed.append({"key": "carrier", "cr": carrier_price, "est": False})
    current = [{"key": "carrier_cargo", "cr": frontier.get("cargo_value") if frontier else None, "est": False},
               {"key": "unsold_data", "cr": unsold, "est": True},
               {"key": "cash", "cr": cash, "est": False}]
    if carrier:
        current.append({"key": "carrier_bank", "cr": fin.get("CarrierBalance") or (frontier or {}).get("balance"),
                        "est": False})
    prov = []
    if frontier:
        prov.append({"key": "upkeep_due", "cr": max(0, frontier["per_week"] - frontier["week_to_date"]), "est": False})
        if frontier.get("orders_reserved"):
            prov.append({"key": "orders_reserved", "cr": frontier["orders_reserved"], "est": False})
    total = sum(x["cr"] or 0 for x in fixed + current)
    provisions = sum(x["cr"] or 0 for x in prov)
    return {"fixed": fixed, "current": current, "provisions": prov, "assets": total,
            "equity": total - provisions, "liabilities": total,
            "unknown": [x["key"] for x in fixed + current if x["cr"] is None]}


# ------------------------------------------------------------------ outlook
def _run_rate(weeks: List[Dict[str, Any]], now: float) -> Dict[str, Any]:
    """Income and running costs per week over the last RUN_WEEKS calendar
    weeks before this one - weeks without play count as nothing earned."""
    have = {w["label"]: w for w in weeks}
    start = bounds("week", _label("week", now))[0]
    labels = [_label("week", start - (i + 0.5) * 7 * 86400) for i in range(RUN_WEEKS)][::-1]
    if not weeks or labels[-1] < weeks[0]["label"]:
        return {"weeks": 0, "played": 0, "income": None, "costs": None}
    got = [have.get(lab) or {} for lab in labels]
    inc = sum(sum((w.get("income") or {}).values()) for w in got) / RUN_WEEKS
    cost = sum(sum((w.get("costs") or {}).values()) for w in got) / RUN_WEEKS
    return {"weeks": RUN_WEEKS, "played": sum(1 for w in got if w), "income": round(inc), "costs": round(cost),
            "from": labels[0], "to": labels[-1]}


def decommission(events: Iterable[Dict[str, Any]], own_id: Any) -> Optional[Dict[str, Any]]:
    """What the game said a decommission returns (CarrierDecommission:
    ScrapRefund, ScrapTime) - the last request, unless cancelled after it.
    None when the journals never asked: then it is unknown."""
    last = None
    for e in events:
        ev = e.get("event")
        if ev not in ("CarrierDecommission", "CarrierCancelDecommission"):
            continue
        if own_id is not None and e.get("CarrierID") not in (None, own_id):
            continue
        if ev == "CarrierDecommission":
            last = {"ts": parse_ts(e.get("timestamp")), "refund": e.get("ScrapRefund"),
                    "scrap_time": e.get("ScrapTime"), "cancelled": False}
        elif last:
            last["cancelled"] = True
    return last


def outlook(periods: Dict[str, List[Dict[str, Any]]], carrier: Optional[Dict[str, Any]],
            frontier: Optional[Dict[str, Any]], cash: Optional[int], events: List[Dict[str, Any]],
            now: float) -> Dict[str, Any]:
    """How long the carrier is financed, the weekly burn against the income
    run rate, when money must come in, what a decommission returns."""
    run = _run_rate(periods.get("week") or [], now)
    fin = _latest_stats(carrier)
    est = ((carrier or {}).get("upkeep") or {}).get("per_week")
    per_week = (frontier or {}).get("per_week") or est
    source = "frontier" if (frontier or {}).get("per_week") else ("estimate" if est else None)
    avail = fin.get("AvailableBalance")
    weeks_left = avail / per_week if avail is not None and per_week else None
    out: Dict[str, Any] = {"run": run, "carrier_per_week": per_week, "carrier_source": source,
                           "carrier_available": avail, "carrier_weeks": round(weeks_left, 1) if weeks_left else None,
                           "carrier_until": now + weeks_left * 7 * 86400 if weeks_left else None, "cash": cash}
    if run["income"] is not None:
        burn = run["costs"] + (per_week or 0)
        out["burn"] = burn
        out["net_run"] = run["income"] - burn
        out["coverage"] = round(100.0 * run["income"] / burn) if burn else None
        # the commander's money, if the carrier were paid from it once its own runs dry
        out["cash_weeks"] = round(cash / -out["net_run"], 1) if cash and out["net_run"] < 0 else None
    own_id = ((carrier or {}).get("stats") or {}).get("CarrierID")
    out["decommission"] = decommission(events, own_id) if carrier else None
    return out


def _course(pts: Iterable[Tuple[float, Any]], keep: int = 300) -> List[List[float]]:
    pts = [(t, b) for t, b in pts if t is not None and b is not None]
    if len(pts) > keep:
        step = len(pts) / float(keep - 1)
        pts = [pts[int(i * step)] for i in range(keep - 1)] + [pts[-1]]
    return [[round(t), int(b)] for t, b in pts]


def build(ledger: Dict[str, Any], carrier: Optional[Dict[str, Any]], frontier: Optional[Dict[str, Any]],
          ships: List[Dict[str, Any]], events: List[Dict[str, Any]], cash: Optional[int] = None,
          open_: Optional[Dict[str, Any]] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """GV1: the annual statement of the commander's company from the
    all-time ledger (build_ledger(days=None)) and the carrier."""
    now = time.time() if now is None else now
    periods = ledger.get("periods") or {}
    share = (frontier["services"] / frontier["per_week"]) if frontier and frontier.get("per_week") else None
    if cash is None and ledger.get("balances"):
        cash = ledger["balances"][-1][1]
    sts = statements(periods, carrier, share, now)
    bals = (carrier or {}).get("balances") or []
    trs = (carrier or {}).get("transfers") or []
    every = _merge(periods.get("year") or [], "all")
    d30 = now - 30 * 86400
    recent = _merge([e for e in periods.get("week") or [] if bounds("week", e["label"])[1] > d30], "30d")
    mains = main_segments(events)
    sc = ledger.get("ship_costs") or []
    rweeks = {e["label"] for e in periods.get("week") or [] if bounds("week", e["label"])[1] > d30}
    seg = {"all": segments(every, upkeep_between(bals, trs, None) if bals else None, activity_time(events),
                           allocate(sc, mains)),
           "recent": segments(recent, upkeep_between(bals, trs, d30) if bals else None, activity_time(events, d30),
                              allocate(sc, mains, rweeks))}
    carrier_price = ((ledger.get("totals") or {}).get("invest_rows") or [])
    carrier_price = next((r["cr"] for r in carrier_price if r["key"] == "carrier"), None)
    return {"generated": now, "share_services": share, "statements": sts, "segments": seg,
            "balance_sheet": balance_sheet(ships, carrier, frontier, cash, open_, carrier_price),
            "outlook": outlook(periods, carrier, frontier, cash, events, now),
            "course": {"cash": _course(ledger.get("balances") or []), "carrier": _course(bals)},
            "carrier_memo": ({"market_profit": frontier["market_profit"], "bar_profit": frontier["bar_profit"],
                              "black_profit": frontier["black_profit"]} if frontier else None),
            "first": ledger.get("first")}
